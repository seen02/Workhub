import copy
import unittest
from unittest.mock import AsyncMock, patch
from . import report_parser as parser, report_registration as registration, reports, criteria

RAW='위성영상 생성 프로젝트에 생성 기술 파악 업무 추가해 줘. 완료 기준은 Sat3DGen 사용, Sat2City 조사 이 두 가지야.'
TITLES=['Sat3DGen 사용','Sat2City 조사']


def row():
    return {'title':'생성 기술 파악','kind':'create','task_id':'','project_id':'p','project_name':'위성영상 생성',
            'evidence':RAW,'state':'PENDING','items':[{'title':title,'state':'완료','evidence':RAW} for title in TITLES]}


class RegistrationTests(unittest.TestCase):
    def normalized(self,raw):
        g=row();registration.normalize(raw,g,TITLES);return [i['state'] for i in g['items']]

    def test_definition_is_not_a_completion_report(self):
        self.assertEqual(self.normalized(RAW),['예정','예정'])
        self.assertEqual(self.normalized('완료 기준: Sat3DGen 사용, Sat2City 조사'),['예정','예정'])
        self.assertEqual(self.normalized('새 업무 추가해줘. Sat3DGen 사용, Sat2City 조사'),['예정','예정'])

    def test_explicit_status_is_per_item_not_whole_sentence(self):
        self.assertEqual(self.normalized('업무 추가해줘. 완료 기준은 Sat3DGen 사용은 완료했고, Sat2City 조사야.'),['완료','예정'])
        self.assertEqual(self.normalized('업무 추가해줘. 완료 기준은 Sat3DGen 사용, Sat2City 조사는 진행 중이야.'),['예정','진행 중'])
        self.assertEqual(self.normalized('업무 추가해줘. Sat3DGen 사용은 예정이고, Sat2City 조사는 진행 중이야.'),['예정','진행 중'])
        self.assertEqual(self.normalized('업무 추가해줘. Sat3DGen 사용은 진행 중이고, Sat2City 조사는 완료했어.'),['진행 중','완료'])

    def test_shared_list_predicate_and_prefix_state(self):
        self.assertEqual(self.normalized('업무 추가해줘. 완료 기준은 Sat3DGen 사용과 Sat2City 조사를 완료했어.'),['완료','완료'])
        self.assertEqual(self.normalized('업무 추가해줘. 완료 기준은 이미 완료한 Sat3DGen 사용, Sat2City 조사.'),['완료','예정'])
        self.assertEqual(self.normalized('업무 추가해줘. 완료 기준은 Sat3DGen 사용, Sat2City 조사야. 두 항목 다 완료했어.'),['완료','완료'])

    def test_future_negative_and_uncertain_are_not_completed(self):
        for status in ('완료할 예정이야','아직 완료하지 않았어','아직 못 끝냈어','완료인지 모르겠어','미완료야'):
            with self.subTest(status=status):
                self.assertEqual(self.normalized('업무 추가해줘. Sat3DGen 사용은 '+status+'. Sat2City 조사.'),['예정','예정'])

    def test_unrelated_completion_does_not_leak_across_sentence(self):
        self.assertEqual(self.normalized(RAW+' 이전 보고서 작성은 완료했어.'),['예정','예정'])

    def test_ordinary_report_is_unchanged(self):
        g=row();g['task_id']='existing';before=copy.deepcopy(g)
        registration.normalize('Sat3DGen 사용을 끝냈어.',g,TITLES)
        self.assertEqual(g,before)

    def test_item_title_containing_complete_is_not_a_state(self):
        g=row();g['items']=[{'title':'배포 완료 확인','state':'완료'}]
        registration.normalize('새 업무 추가해줘. 완료 기준은 배포 완료 확인이야.',g,['배포 완료 확인'])
        self.assertEqual(g['items'][0]['state'],'예정')

    def test_wrong_model_result_is_corrected_before_preview_and_storage(self):
        g=row();parsed=parser.Extract(groups=[parser.Group(project_id='p',title=g['title'],evidence=RAW,
            items=[parser.Item(**i) for i in g['items']])])
        with patch.object(parser,'inventory',return_value=([{'id':'p','name':'위성영상 생성'}],[])), \
             patch.object(parser,'extract_scoped',new=AsyncMock(return_value=parsed)):
            groups,_=parser.plan({'sub':'s','email':'test@example.com'},RAW)
        self.assertEqual(groups[0]['kind'],'create')
        self.assertEqual([i['state'] for i in groups[0]['items']],['예정','예정'])
        report={'id':'r','when':'2026-09-30T06:10:00+00:00','groups':groups}
        preview=reports.text(report)
        self.assertNotIn('✅',preview);self.assertEqual(preview.count('🕒 예정'),2)
        with patch.object(reports.human_tasks,'label',return_value='홍길동 (test@example.com)'):
            source=reports.new_text({'email':'test@example.com'},groups[0],report)
        self.assertNotIn('- [x]',source);self.assertIn('상태: 미착수',source)
        with patch.object(reports.human_tasks,'resolve',return_value='test@example.com'):
            self.assertEqual([i['state'] for i in criteria.parse(source)],['예정','예정'])


if __name__=='__main__':unittest.main()
