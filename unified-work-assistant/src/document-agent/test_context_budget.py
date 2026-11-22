"""Long tool output stays out of Qwen's 4096-token conversation."""
import asyncio,json,unittest
from unittest.mock import patch
import httpx
from webui_bridge import Tools

class ContextBudgetTest(unittest.TestCase):
    def test_catalog_read_and_error_payloads_are_constant_size_receipts(self):
        async def run(tool,full):
            client=httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,json=full)))
            with patch('webui_bridge.httpx.AsyncClient',return_value=client):
                return json.loads(await Tools()._run(tool,{}, {'id':'u'},{'chat_id':'c'},None))
        for tool,payload in [('catalog',{'collections':[{'name':'목록'*1000}]*2000}),
                             ('read_document',{'text':'문서'*10000,'id':'doc','revision':2}),
                             ('research_documents',{'error':{'message':'오류'*10000}})]:
            with self.subTest(tool=tool):
                result=asyncio.run(run(tool,{'event_id':'e','status':'succeeded',**payload}))
                self.assertTrue(result['fetch_result'])
                self.assertLess(len(json.dumps(result,ensure_ascii=False)),600)
                self.assertNotIn('collections',result);self.assertNotIn('text',result);self.assertNotIn('error',result)
                if tool=='read_document':self.assertEqual(result['id'],'doc');self.assertEqual(result['revision'],2)

if __name__=='__main__':unittest.main()
