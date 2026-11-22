"""Offline regressions for observed UX failures. Run inside the agent image."""
import asyncio,json,unittest,types,sys
from unittest.mock import patch
from pathlib import Path
from agent_ux import candidates,source_units,render_research,research_display,CATEGORIES
from webui_receipt import Filter

class UXTest(unittest.TestCase):
    def test_partial_names_and_ambiguity(self):
        rows=[{'id':'1','title':'[회사시연 20260916] 시연 결과'},{'id':'2','title':'다른 결과'}]
        self.assertEqual(candidates(rows,'시연결과')[0]['id'],'1')
        self.assertEqual(len(candidates(rows,'결과')),2)
        self.assertEqual(candidates(rows,''),[])
    def test_markdown_units_preserve_numbers_and_conditions(self):
        units=source_units('## 측정\nGPU 11\\.8초는 계산만이다. 전체는 43.0초다.\n|항목|결과|\n|---|---|\n|로그인|미착수|')
        self.assertIn('11.8초',units[0]['text'])
        self.assertIn('43.0초',units[1]['text'])
        self.assertTrue(any('미착수' in u['text'] for u in units))
    def test_all_report_sections_sources_and_failures_visible(self):
        r={'matched_count':2,'read_count':1,'inventory_count':3,'inventory_complete':True,'scope':'전체',
           'sources':[{'title':'원문','url':'http://local/doc/1'}],
           'failed':[{'title':'실패 자료','reason':'연결 실패'}],
           'findings':[{'number':1,'evidence':[{'category':'개요','quote':'핵심.'}]}]}
        r['report']=render_research(r);text=research_display(r)
        self.assertTrue(all('## '+c in text for c in CATEGORIES))
        self.assertIn('http://local/doc/1',text);self.assertIn('실패 자료',text)
    def test_large_history_removed_latest_source_intact(self):
        f=Filter();latest='메모: 숫자 11.8초. 아직 저장하지 마.'
        body={'model':'outline-assistant','tool_ids':['outline_read','outline_write'],
              'messages':[{'role':'user','content':'도시시설 조사'},{'role':'assistant','content':'긴 보고서'*10000},{'role':'user','content':latest}]}
        b=asyncio.run(f.inlet(body))
        self.assertLess(len(json.dumps(b,ensure_ascii=False)),1500)
        self.assertEqual(b['messages'][-1]['content'],latest)
        self.assertEqual(b['tool_ids'],['outline_write'])
    def test_full_result_restored_and_screen_event_identical(self):
        f=Filter();events=[]
        full={'status':'succeeded','research_id':'r','display':'## 개요\n전체\n## 문제점\n확인중\n### 출처\n링크'}
        async def fake(*args):return full
        async def emitter(event):events.append(event)
        f.backend=fake
        b={'model':'outline-assistant','messages':[{'role':'assistant','content':'짧은 임시 답변','output':[{'type':'function_call_output','output':[{'text':json.dumps({'status':'succeeded','fetch_result':True,'event_id':'e'})}]}]}]}
        out=asyncio.run(f.outlet(b,__event_emitter__=emitter))
        self.assertEqual(out['messages'][-1]['content'],full['display'])
        self.assertEqual(events[-1]['data']['content'],full['display'])
    def test_read_bridge_drops_invented_collection(self):
        ns={};exec('class Tools:\n'+Path('webui_read.py').read_text(encoding='utf-8-sig'),ns)
        t=ns['Tools']()
        async def capture(name,args,*_):return args
        t._run=capture
        a=asyncio.run(t.research_outline(topic='도시시설',collection_name='사업 진행 보고서',__messages__=[{'role':'user','content':'도시시설 진행 상황 알려줘'}]))
        self.assertEqual(a['collection_name'],'');self.assertEqual(a['topic'],'도시시설')
    def test_followup_uses_latest_research(self):
        ns={};exec('class Tools:\n'+Path('webui_read.py').read_text(encoding='utf-8-sig'),ns)
        t=ns['Tools']()
        async def capture(name,args,*_):return args
        t._run=capture
        a=asyncio.run(t.research_outline(topic='사업 진행 보고서',__messages__=[{'role':'user','content':'팀장에게 보고할 내용으로 정리해줘'}]))
        self.assertEqual(a['topic'],'')

    def attachment(self, count, filename):
        import base64
        records={str(i):types.SimpleNamespace(id=str(i),user_id='user',filename=f'meeting-{i}.docx',meta={},path=__file__) for i in range(count)}
        async def get_file(ident):return records[ident]
        modules={'open_webui.models.files':types.SimpleNamespace(Files=types.SimpleNamespace(get_file_by_id=get_file)),
                 'open_webui.storage.provider':types.SimpleNamespace(Storage=types.SimpleNamespace(get_file=lambda p:p))}
        ns={'Path':Path,'json':json,'asyncio':asyncio,'base64':base64}
        exec('class Tools:\n'+Path('webui_files.py').read_text(encoding='utf-8-sig'),ns)
        tool=ns['Tools']()
        async def capture(name,args,*_):return args
        tool._run=capture
        with patch.dict(sys.modules,modules):
            return asyncio.run(tool.read_outline_attachment(filename=filename,__files__=[{'id':i} for i in records],__user__={'id':'user'}))

    def test_single_attachment_ignores_guessed_filename(self):
        self.assertEqual(self.attachment(1,'모델이 추측한 이름.docx')['file_id'],'0')

    def test_multiple_attachments_offer_real_names(self):
        result=json.loads(self.attachment(2,''))
        self.assertEqual(result['status'],'needs_input')
        self.assertEqual(len(result['error']['candidates']),2)

if __name__=='__main__':unittest.main()
