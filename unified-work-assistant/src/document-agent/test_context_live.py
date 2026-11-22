"""Read-only Outline checks through real Open WebUI + local Qwen."""
import contextlib,io,json,sqlite3,time
from test_agent_chat import ROOT,chat,session

def run(prompt,previous=None):
    started=time.monotonic()
    with contextlib.redirect_stdout(io.StringIO()):
        report=chat(prompt,title='[검증] 4096토큰 검색·목록',previous=previous)
    content=report['result'].get('content','')
    assert report['result'].get('done') and not report['result'].get('error'),report['result'].get('error')
    assert 'exceed_context' not in content and '요청을 완료하지' not in content,content
    with sqlite3.connect(ROOT/'data/agent.sqlite3') as db:
        row=db.execute('SELECT tool,status,result FROM events WHERE scope=? ORDER BY started DESC LIMIT 1',
                       (session['id']+':'+report['chat_id'],)).fetchone()
    assert row and row[0]=='read_request' and row[1]=='succeeded',row
    full=json.loads(row[2])
    assert content==full['display'],'Server result was lost or rewritten'
    return {'prompt':prompt,'chat_id':report['chat_id'],'seconds_total':round(time.monotonic()-started,1),
            'content':content,**{k:full[k] for k in ('topic','collection_name','matched_count','read_count','sources','reused') if k in full}}

if __name__=='__main__':
    records=[]
    r=run('‘로컬 AI 테스트’ 컬렉션에서 9월 16일 업무 메모 관련 문서를 찾아 현재 상태와 다음 할 일을 짧게 정리해줘. 읽은 문서 수와 출처도 알려줘.')
    assert r['read_count']>=1 and '](' in r['content'],r
    records.append(r)
    print(json.dumps({'test':'research',**{k:r[k] for k in ('chat_id','seconds_total','read_count')}},ensure_ascii=False),flush=True)
    r=run('그 내용에서 다음 할 일만 짧게 알려줘. 출처도 보여줘.',r['chat_id'])
    assert r['reused'] and r['read_count']==records[0]['read_count'],r
    records.append(r)
    print(json.dumps({'test':'followup','seconds_total':r['seconds_total'],'reused':r['reused']},ensure_ascii=False),flush=True)
    r=run('‘로컬 AI 테스트’ 컬렉션의 문서 목록과 사용할 수 있는 양식을 보여줘.')
    assert '작업흐름 검증 0916' in r['content'] and '사용 가능한 양식' in r['content'],r
    records.append(r)
    print(json.dumps({'test':'catalog','seconds_total':r['seconds_total'],'display_characters':len(r['content'])},ensure_ascii=False),flush=True)
    (ROOT/'data/context-budget-live.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
