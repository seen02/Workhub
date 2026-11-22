"""One-process durable task registry. Context-local progress and real cancellation."""
import asyncio
import contextvars
import json
import time
import uuid
import user_acl

event_id = contextvars.ContextVar('outline_event_id', default=None)

class TaskRuntime:
    def __init__(self, conn):
        self.conn = conn
        self.tasks = {}
        # The deployed service has exactly one uvicorn worker. Its prior tasks cannot survive boot.
        conn.execute("UPDATE events SET status='interrupted' WHERE status IN ('queued','running')")
        conn.commit()

    def update(self, **changes):
        eid = event_id.get()
        if not eid:
            return
        row = self.conn.execute('SELECT result FROM events WHERE id=?', (eid,)).fetchone()
        value = json.loads(row['result'] or '{}')
        value.update(changes, heartbeat=time.time())
        actor=user_acl.actor.get()
        if actor is not None:value['_access_documents']=sorted(actor['documents'])
        self.conn.execute('UPDATE events SET result=? WHERE id=?', (json.dumps(value, ensure_ascii=False), eid))
        self.conn.commit()

    def result(self, eid, scope):
        row = self.conn.execute('SELECT * FROM events WHERE id=? AND scope=?', (eid, scope)).fetchone()
        if not row:
            return None
        return {**json.loads(row['result'] or '{}'), 'event_id':eid, 'status':row['status'],
                'seconds':round(time.time()-row['started'], 2) if row['status'] in ('queued','running') else row['seconds']}

    def register(self, scope, tool, args):
        eid = str(uuid.uuid4())
        self.conn.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?,?)',
            (eid,scope,tool,json.dumps(args,ensure_ascii=False),'{}','queued',time.time(),0))
        self.conn.commit()
        return eid

    async def run(self, eid, scope, operation, timeout):
        token = event_id.set(eid)
        self.conn.execute("UPDATE events SET status='running' WHERE id=?", (eid,))
        self.conn.commit()
        started = time.time()
        try:
            async with asyncio.timeout(timeout):
                result = await operation()
            status = result.get('status', 'needs_input' if result.get('needs_input') else 'succeeded')
        except (asyncio.CancelledError, TimeoutError) as exc:
            result = self.result(eid, scope) or {}
            status = 'cancelled' if isinstance(exc, asyncio.CancelledError) else 'partial'
            result.pop('status', None)
            result['reason'] = '사용자가 중지했습니다.' if status=='cancelled' else '작업 시간 한도에 도달했습니다.'
            result['display'] = result.get('display', '') + '\n\n' + result['reason'] + '\n완료한 결과는 보존했습니다. “조사 이어서”로 남은 범위를 처리할 수 있습니다.'
        except Exception as exc:
            from fastapi import HTTPException
            result = self.result(eid, scope) or {}
            result.pop('status', None)
            if isinstance(exc, HTTPException):
                result.update(error=exc.detail, status_code=exc.status_code)
                status = 'needs_input' if isinstance(exc.detail,dict) and exc.detail.get('needs_input') else 'failed'
            else:
                result.update(error=f'처리 실패 ({type(exc).__name__}).', status_code=500)
                status = 'failed'
        finally:
            event_id.reset(token)
        result.pop('event_id', None)
        result.pop('status', None)
        actor=user_acl.actor.get()
        if actor is not None:
            result['_access_documents']=sorted(actor['documents'])
        self.conn.execute('UPDATE events SET result=?,status=?,seconds=? WHERE id=?',
            (json.dumps(result,ensure_ascii=False),status,round(time.time()-started,2),eid))
        self.conn.commit()
        self.tasks.pop(eid, None)
        return {**result,'event_id':eid,'status':status}

    def cancel(self, eid, scope):
        result = self.result(eid,scope)
        if result and eid in self.tasks:
            self.tasks[eid].cancel()
            if result['status']=='queued':
                self.conn.execute("UPDATE events SET status='cancelled',result=? WHERE id=?", (json.dumps({'display':'대기 중인 작업을 취소했습니다.'}),eid))
                self.conn.commit()
                self.tasks.pop(eid,None)
        return result
