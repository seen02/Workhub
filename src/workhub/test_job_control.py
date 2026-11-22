import asyncio
import os
import queue
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from . import job_control as jobs, bot, store, report_chat, my_tasks_chat, report_parser, assistant, reports


class JobControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        p=patch.object(store,'DB',os.path.join(self.tmp.name,'db'));p.start();self.addCleanup(p.stop);store.init()
        with jobs.lock:jobs.active.clear();jobs.cutoffs.clear()
        self.user={'sub':'s','email':'test@example.com'}

    def test_cancel_closes_pending_coroutine_and_releases_model_lock(self):
        entered=threading.Event();closed=threading.Event();ended=threading.Event();errors=[]
        async def request():
            entered.set()
            try:await asyncio.Event().wait()
            finally:closed.set()
        def run():
            try:
                with jobs.running('u','r'):
                    with assistant.LLM_LOCK:asyncio.run(jobs.wait(request()))
            except jobs.Stopped:ended.set()
            except BaseException as e:errors.append(e)
        t=threading.Thread(target=run);t.start();self.assertTrue(entered.wait(2))
        jobs.stop('u','r','중단',time.monotonic());t.join(2)
        self.assertFalse(t.is_alive());self.assertTrue(closed.is_set());self.assertTrue(ended.is_set())
        self.assertFalse(errors);self.assertFalse(assistant.LLM_LOCK.locked())

    def test_timeout_cancels_request_instead_of_retrying(self):
        closed=[]
        async def request():
            try:await asyncio.sleep(10)
            finally:closed.append(True)
        with jobs.running('u','r') as j:
            j.deadline=time.monotonic()+.05
            with self.assertRaisesRegex(jobs.Stopped,'자동 중단'):asyncio.run(jobs.wait(request()))
            self.assertEqual(closed,[True])
            j.deadline=time.monotonic()+10

    def test_foreign_and_stale_buttons_do_not_stop_new_job(self):
        with jobs.running('u','r') as j:old=j.command
        with jobs.running('u','r') as j:
            jobs.stop('other','r',j.command,time.monotonic())
            jobs.stop('u','other',j.command,time.monotonic())
            jobs.stop('u','r',old,time.monotonic())
            self.assertFalse(j.cancelled.is_set())
        self.assertFalse(jobs.has_active('u','r'))

    def test_stop_clears_only_earlier_requests_in_same_dm(self):
        jobs.stop('u','r','중단',10)
        self.assertTrue(jobs.discarded('u','r',9));self.assertFalse(jobs.discarded('u','r',11))
        self.assertFalse(jobs.discarded('other','r',9));self.assertFalse(jobs.discarded('u','other',9))
        with self.assertRaises(jobs.Stopped):
            with jobs.running('u','r',9):pass
        with jobs.running('u','r',11):pass

    def test_cancel_uses_priority_queue_even_when_normal_queue_full(self):
        regular=queue.Queue(maxsize=1);regular.put({});urgent=queue.Queue()
        m={'_id':'stop','rid':'r','u':{'_id':'u'},'msg':'중단'}
        with patch.object(bot,'JOBS',regular),patch.object(bot,'CONTROLS',urgent),patch.object(bot,'say'):
            with self.assertRaises(jobs.Stopped):
                with jobs.running('u','r') as j:
                    bot.receive(m);self.assertEqual(urgent.qsize(),1)
                    bot.control(urgent.get_nowait());self.assertTrue(j.cancelled.is_set())
        self.assertEqual(regular.qsize(),1)

    def test_cancelled_result_is_not_posted_and_new_report_is_possible(self):
        def draft(*a):
            jobs.stop('u','r','중단',time.monotonic())
            return 'must not be delivered',None
        with patch.object(bot,'identity',return_value=self.user),patch.object(bot,'say') as say, \
             patch.object(my_tasks_chat,'route',return_value=None),patch.object(report_chat,'route',return_value=None), \
             patch.object(report_chat.report_transport,'require_dm'),patch.object(report_chat,'draft',side_effect=draft):
            bot.handle({'_id':'m','rid':'r','u':{'_id':'u'},'msg':'로그인 화면 완료했어'})
        self.assertTrue(any('긴급 취소' in c.args[1] for c in say.call_args_list))
        self.assertFalse(any('must not' in c.args[1] for c in say.call_args_list))
        with store.db() as c:self.assertEqual(c.execute('SELECT state FROM messages WHERE id="m"').fetchone()['state'],'CANCELLED')
        # Windows monotonic clocks can return the exact cancellation timestamp
        # again. Use an explicitly later event instead of relying on resolution.
        with jobs.running('u','r',jobs.cutoffs[('u','r')]+0.001):pass

    def test_cancel_prevents_draft_persistence(self):
        with self.assertRaises(jobs.Stopped):
            with jobs.running('u','r'):
                jobs.stop('u','r','중단',time.monotonic())
                reports.save({'id':'late'})
        self.assertIsNone(store.get('report-v2:late'))

    def test_plan_query_does_not_start_inference(self):
        with patch.object(bot,'identity',return_value=self.user),patch.object(bot,'say'), \
             patch.object(my_tasks_chat,'route',return_value=('내 업무 목록',None)) as route,patch.object(report_chat,'draft') as draft:
            bot.handle({'_id':'plan','rid':'r','u':{'_id':'u'},'msg':'업무 계획'})
        self.assertEqual(route.call_args.args[-2],'내 업무');draft.assert_not_called()

    def test_provider_cancellation_closes_real_http_connection(self):
        import httpx
        from .ai_runtime import DraftProvider
        async def verify():
            received=asyncio.Event();disconnected=asyncio.Event()
            async def handler(reader,writer):
                headers=await reader.readuntil(b'\r\n\r\n')
                length=next(int(line.split(b':',1)[1]) for line in headers.split(b'\r\n') if line.lower().startswith(b'content-length:'))
                await reader.readexactly(length);received.set()
                await reader.read();disconnected.set();writer.close();await writer.wait_closed()
            server=await asyncio.start_server(handler,'127.0.0.1',0)
            try:
                port=server.sockets[0].getsockname()[1]
                async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}') as client:
                    with self.assertRaises(jobs.Stopped):
                        with jobs.running('socket-user','socket-room'):
                            request=asyncio.create_task(DraftProvider(client)._post('/api/chat',{'model':'test'}))
                            await asyncio.wait_for(received.wait(),2)
                            jobs.stop('socket-user','socket-room','중단',time.monotonic())
                            try:await request
                            finally:await asyncio.wait_for(disconnected.wait(),2)
                self.assertTrue(disconnected.is_set())
            finally:server.close();await server.wait_closed()
        asyncio.run(verify())


if __name__=='__main__':unittest.main()
