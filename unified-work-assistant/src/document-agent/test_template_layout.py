import unittest
from unittest.mock import patch
import test_ux_backend as backend
from template_layout import clean_slot_text,render_slots

HEADINGS=['## [기본 정보]','## [예정 사항]','## [문제 및 확인 필요]']


class LayoutTest(unittest.TestCase):
    def test_echo_variants(self):
        for prefix in ('## [기본 정보]','- ## [기본 정보]','**[기본 정보]**','기본 정보','[기본 정보]'):
            self.assertEqual(clean_slot_text(prefix+'\n회의 기록',HEADINGS,'회의 기록'),'회의 기록')
        self.assertEqual(clean_slot_text('[예정 사항]: 내부 시연은 17시 예정.',HEADINGS),'내부 시연은 17시 예정.')

    def test_source_and_prose_and_links_survive(self):
        for text in ('[기본 정보]를 확인할 예정.','[기본 정보](http://local/doc/test)','기본 정보는 미확정.'):
            self.assertEqual(clean_slot_text(text,HEADINGS,text),text)
        self.assertEqual(clean_slot_text('[기본 정보]\n원문 제목',HEADINGS,'[기본 정보]\n원문 제목'),'[기본 정보]\n원문 제목')

    def test_repeated_template_sections_are_not_deduplicated(self):
        body=render_slots(['[업무목록]','[업무목록]'],[['오전 업무'],['오후 업무']])
        self.assertEqual(body.count('[업무목록]'),2)


class BackendLayoutTest(unittest.TestCase):
    setUp=backend.BackendUXTest.setUp
    tearDown=backend.BackendUXTest.tearDown
    execute=backend.BackendUXTest.execute

    def test_model_echo_is_removed_before_validation(self):
        self.docs.append({'id':'template','title':'진행 기록 템플릿','text':'\n\n'.join(HEADINGS)})
        async def llm(system,user,schema,*args):
            if 'issues' in schema['properties']:return {'issues':[]},{}
            return {'f1':{'section':1,'text':'## [기본 정보]\n회의 기록'},
                    'f2':{'section':2,'text':'## [예정 사항]\n내부 시연은 17시 예정.'},
                    'f3':{'section':3,'text':'## [문제 및 확인 필요]\n고객 일정은 미확정.'}},{}
        with patch.object(backend.core,'llm',llm):
            r=self.execute('prepare_document',{'text':'회의 기록\n내부 시연은 17시 예정.\n고객 일정은 미확정.','template_name':'진행 기록 템플릿'})
        self.assertEqual(r['status'],'succeeded',r)
        for h in HEADINGS:self.assertEqual(r['markdown'].count(h),1)
        self.assertIn('17시 예정',r['markdown']);self.assertIn('고객 일정은 미확정',r['markdown'])

    def test_multiple_chunks_render_one_template(self):
        import json
        self.docs.append({'id':'template','title':'진행 기록 템플릿','text':'\n\n'.join(HEADINGS)})
        async def llm(system,user,schema,*args):
            if 'issues' in schema['properties']:return {'issues':[]},{}
            data=json.loads(user)
            return {key:{'section':1,'text':text} for key,text in data['원문기록'].items()},{}
        with patch.object(backend.core,'llm',llm):
            r=self.execute('prepare_document',{'text':'가'*1800+'나'*100,'template_name':'진행 기록 템플릿'})
        self.assertEqual(r['status'],'succeeded',r)
        for h in HEADINGS:self.assertEqual(r['markdown'].count(h),1)
        self.assertIn('나'*100,r['markdown'])


if __name__=='__main__':unittest.main()
