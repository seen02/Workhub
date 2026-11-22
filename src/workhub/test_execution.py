"""Security/lifetime boundaries of request reuse, plus actual pooled transports."""
import concurrent.futures
import json
import threading
import unittest
from unittest.mock import patch
import httpx
from fastapi import HTTPException
from . import execution as ex, http_pool, outline, permissions, reports

ALICE={'sub':'alice','email':'alice@example.com','admin':False}
BOB={'sub':'bob','email':'bob@example.com','admin':False}


class ExecutionTests(unittest.TestCase):
    def transport(self, fn):
        def request(service,method,url,**kw):
            return httpx.Response(200,json={'data':fn(url.rsplit('/',1)[-1],kw.get('json',{}))})
        return patch.object(http_pool,'request',side_effect=request)

    def test_same_read_once_per_request_but_fresh_on_next_request(self):
        with self.transport(lambda name,body:{'id':body['id'],'items':[]}) as network:
            for _ in range(2):
                with ex.request('test',ALICE):
                    first=outline.api('documents.info',{'id':'a'})
                    first['items'].append('must not leak')
                    self.assertEqual(outline.api('documents.info',{'id':'a'})['items'],[])
                    outline.api('documents.info',{'id':'b'})
            self.assertEqual(network.call_count,4)

    def test_actor_change_and_exception_cannot_reuse_previous_cache(self):
        with self.transport(lambda *args:{'id':'a'}) as network:
            with self.assertRaises(ValueError):
                with ex.request('test',ALICE):
                    outline.api('documents.info',{'id':'a'})
                    with ex.request('test',BOB):outline.api('documents.info',{'id':'a'})
                    outline.api('documents.info',{'id':'a'})
                    raise ValueError('test')
            self.assertIsNone(ex.current.get())
            self.assertIsNone(permissions.request_snapshots.get())
            with ex.request('test',ALICE):outline.api('documents.info',{'id':'a'})
            self.assertEqual(network.call_count,4)

    def test_parallel_requests_do_not_share_results(self):
        barrier=threading.Barrier(2)
        with self.transport(lambda *args:{'id':'a'}) as network:
            def run(user):
                with ex.request('test',user):
                    outline.api('documents.info',{'id':'a'});barrier.wait(timeout=5)
                    outline.api('documents.info',{'id':'a'})
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(run,[ALICE,BOB]))
            self.assertEqual(network.call_count,2)

    def test_missing_and_failed_reads_are_not_cached(self):
        results=[httpx.Response(404),httpx.Response(200,json={'data':{'id':'a'}})]
        with patch.object(http_pool,'request',side_effect=results) as network, ex.request('test',ALICE):
            self.assertIsNone(outline.api('documents.info',{'id':'a'},missing_ok=True))
            self.assertEqual(outline.api('documents.info',{'id':'a'},missing_ok=True)['id'],'a')
        with patch.object(http_pool,'request',side_effect=[httpx.ConnectError('offline'),results[1]]) as network, ex.request('test',ALICE):
            with self.assertRaises(HTTPException):outline.api('documents.info',{'id':'a'})
            self.assertEqual(outline.api('documents.info',{'id':'a'})['id'],'a')
            self.assertEqual(network.call_count,2)

    def test_write_timeout_invalidates_all_reads_and_never_retries_write(self):
        calls=[]
        def send(service,method,url,**kw):
            name=url.rsplit('/',1)[-1];calls.append(name)
            if name=='documents.update':raise httpx.ReadTimeout('unknown result')
            return httpx.Response(200,json={'data':{'revision':len(calls)}})
        with patch.object(http_pool,'request',side_effect=send),ex.request('test',ALICE):
            self.assertEqual(outline.api('documents.info',{'id':'a'})['revision'],1)
            permissions.request_snapshots.get()['old']='stale'
            with self.assertRaises(HTTPException):outline.api('documents.update',{'id':'a'})
            self.assertNotIn('old',permissions.request_snapshots.get())
            self.assertEqual(outline.api('documents.info',{'id':'a'})['revision'],3)
        self.assertEqual(calls,['documents.info','documents.update','documents.info'])

    def test_fresh_phase_rechecks_live_acl_and_does_not_restore_old_grant(self):
        granted=True
        def respond(name,body):
            if name=='users.list':return [{'id':'a','email':ALICE['email'],'role':'member'}]
            if name=='collections.list':return [{'id':'p','name':'P','permission':None}]
            if name=='collections.memberships':return {'memberships':[{'userId':'a','permission':'read'}] if granted else []}
            if name=='collections.group_memberships':return {'groupMemberships':[]}
            raise AssertionError(name)
        with self.transport(respond),patch.object(permissions,'active',return_value=True),ex.request('test',ALICE):
            permissions.Access(ALICE).require('p')
            granted=False
            permissions.Access(ALICE).require('p')
            with ex.fresh():
                with self.assertRaises(HTTPException):permissions.Access(ALICE).require('p')
            with self.assertRaises(HTTPException):permissions.Access(ALICE).require('p')

    def test_preflight_rejects_changed_document_despite_outer_cache(self):
        revision=1
        def respond(name,body):
            return {'id':'a','text':'before' if revision==1 else 'edited','revision':revision,'updatedAt':str(revision)}
        with self.transport(respond),ex.request('test',ALICE):
            outline.api('documents.info',{'id':'a'});revision=2
            def document(did,user):return outline.api('documents.info',{'id':did})
            group={'state':'PENDING','kind':'update','task_id':'a','before':'before','revision':1,'updatedAt':'1'}
            with patch.object(outline,'document',side_effect=document),patch.object(outline,'authorize_changes'),patch.object(reports,'changes_for',return_value={}):
                with self.assertRaises(HTTPException) as error:reports.preflight(ALICE,group,{})
                self.assertEqual(error.exception.status_code,409)

    def test_metrics_have_no_user_or_report_content(self):
        with self.assertLogs(ex.log,level='INFO') as logs:
            with ex.request('report_plan',ALICE):
                with ex.span('ai'):pass
        payload=json.loads(logs.output[0].split('request_metrics ',1)[1])
        self.assertEqual(payload['counts']['ai'],1)
        self.assertNotIn('alice',logs.output[0]);self.assertIn('elapsed_seconds',payload)


class HttpPoolTests(unittest.TestCase):
    def tearDown(self):http_pool.close()

    def test_client_reuse_credentials_cookie_isolation_and_close(self):
        http_pool.close();created=[];requests=[]
        real_client=httpx.Client
        def factory(**kwargs):
            c=real_client(transport=httpx.MockTransport(lambda req:(requests.append(req) or httpx.Response(200,headers={'set-cookie':'session=private'},json={'ok':True}))),**kwargs)
            created.append(c);return c
        with patch.object(http_pool.httpx,'Client',side_effect=factory):
            for token in ['first','second']:
                http_pool.request('test','POST','http://service/api',metric='api',headers={'Authorization':token},timeout=7,json={})
            self.assertEqual(len(created),1)
            self.assertEqual([r.headers['authorization'] for r in requests],['first','second'])
            self.assertTrue(all('cookie' not in r.headers for r in requests))
            self.assertEqual(requests[0].extensions['timeout']['read'],7)
            http_pool.close();self.assertTrue(created[0].is_closed)

    def test_real_http_connection_is_reused_and_server_close_reconnects(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        peers=[]
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def do_GET(self):
                peers.append(self.client_address)
                body=b'{}'
                self.send_response(200);self.send_header('Content-Length',str(len(body)))
                if self.path=='/close':self.send_header('Connection','close')
                self.end_headers();self.wfile.write(body)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            for path in ['/first','/close','/after-close']:
                response=http_pool.request('local-test','GET',f'http://127.0.0.1:{server.server_port}'+path,metric='probe',timeout=3)
                self.assertEqual(response.status_code,200)
            self.assertEqual(peers[0],peers[1])
            self.assertNotEqual(peers[1],peers[2])
        finally:
            http_pool.close();server.shutdown();server.server_close();worker.join(timeout=3)
