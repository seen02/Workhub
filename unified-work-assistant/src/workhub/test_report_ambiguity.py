"""Cross-project collisions must be resolved by the reporter, never model rank."""
import copy
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from . import report_parser as parser, report_chat as ui, reports, store, chat_ui, outline, criteria

RAW = '서류 정리와 이미지 정리 완료했어.'
USER = {'sub': 'u', 'email': 'test@example.com', 'admin': False}
PROJECTS = [{'id': 'sat', 'name': '위성영상 생성'}, {'id': 'com', 'name': '의사소통 도구 선정'}]


def tasks():
    return [{'id': p['id']+'-task', 'title': '자료 정리', 'collectionId': p['id'],
             'collectionName': p['name'], 'text': '', 'criteria': [
                 {'id': p['id']+'-doc', 'title': '서류 정리'},
                 {'id': p['id']+'-image', 'title': '이미지 정리'}]} for p in PROJECTS]


def extracted(raw=RAW, task_id='sat-task', project_id='sat'):
    return parser.Extract(groups=[parser.Group(title='자료 정리', task_id=task_id,
        project_id=project_id, evidence=raw, items=[parser.Item(title=title, state='완료',
        evidence=raw, criterion_id='sat-'+suffix) for title,suffix in [('서류 정리','doc'),('이미지 정리','image')]])])


class ReportAmbiguityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.mock(store,'DB',new=os.path.join(self.tmp.name,'db'));store.init()
        self.inventory=self.mock(parser,'inventory',return_value=(PROJECTS,tasks()))
        self.extract=self.mock(parser,'extract_scoped',new=AsyncMock(return_value=extracted()))
        self.mock(parser.search,'sync_registry')
        self.search=self.mock(parser.search,'agent',return_value={'candidates':[{'id':'sat-task','score':100}], 'mode':'hybrid'})
        self.mock(ui.report_transport,'require_dm')
        self.mock(reports.permissions,'project',side_effect=lambda u,p:next(x for x in PROJECTS if x['id']==p))

    def mock(self,obj,name,**kw):
        p=patch.object(obj,name,**kw);value=p.start();self.addCleanup(p.stop);return value

    def test_model_and_recent_context_cannot_break_cross_project_tie(self):
        with patch.object(parser,'resolve_items') as resolve:
            groups,_=parser.plan(USER,RAW,{'project_id':'sat','task_id':'sat-task'})
        g=groups[0];self.assertTrue(g['needs_task_choice']);self.assertEqual(g['kind'],'unresolved')
        self.assertEqual(g['task_id'],'');self.assertEqual(g['project_id'],'')
        self.assertEqual(set(g['candidates']),{'sat-task','com-task'})
        self.assertEqual([i['title'] for i in g['items']],['서류 정리','이미지 정리'])
        self.assertTrue(all(not i.get('criterion_id') for i in g['items']));resolve.assert_not_called()

    def test_missing_model_id_and_candidate_truncation_still_check_full_inventory(self):
        extra=[{**tasks()[0],'id':f'other-{n}','title':f'서류 이미지 정리 {n}'} for n in range(20)]
        self.search.return_value={'candidates':[{'id':t['id'],'score':100} for t in extra]+[{'id':'sat-task','score':200}],'mode':'hybrid'}
        self.inventory.return_value=(PROJECTS,[tasks()[0]]+extra+[tasks()[1]])
        self.extract.return_value=extracted(task_id='',project_id='sat')
        with patch.object(parser,'resolve_items') as resolve:
            groups,_=parser.plan(USER,RAW)
        catalog=self.extract.call_args.args[2]
        self.assertNotIn('com-task',[t['id'] for t in catalog])
        self.assertEqual(set(groups[0]['candidates']),{'sat-task','com-task'});resolve.assert_not_called()

    def test_explicit_project_does_not_ask_again_or_keep_other_projects_ids(self):
        raw='의사소통 도구 선정 프로젝트의 자료 정리: '+RAW
        # Even if a model picks the wrong twin, the user's explicit clause wins.
        self.extract.return_value=extracted(raw)
        with patch.object(parser,'resolve_items') as resolve:
            groups,_=parser.plan(USER,raw)
        self.assertEqual(groups[0]['task_id'],'com-task');self.assertEqual(groups[0]['kind'],'update')
        self.assertFalse(groups[0].get('needs_task_choice'))
        self.assertTrue(all(not i.get('criterion_id') for i in groups[0]['items']));resolve.assert_called_once()

    def test_unique_task_keeps_existing_flow(self):
        self.inventory.return_value=(PROJECTS,tasks()[:1])
        with patch.object(parser,'resolve_items'):
            groups,_=parser.plan(USER,RAW)
        self.assertEqual(groups[0]['kind'],'update');self.assertFalse(groups[0].get('needs_task_choice'))

    def test_model_split_of_same_ambiguous_work_asks_only_once(self):
        parsed=extracted();second=copy.deepcopy(parsed.groups[0])
        parsed.groups[0].items=parsed.groups[0].items[:1]
        second.items=second.items[1:];second.task_id='com-task';second.project_id='com'
        parsed.groups.append(second);self.extract.return_value=parsed
        groups,_=parser.plan(USER,RAW)
        self.assertEqual(len(groups),1);self.assertTrue(groups[0]['needs_task_choice'])
        self.assertEqual([i['title'] for i in groups[0]['items']],['서류 정리','이미지 정리'])

    def test_chat_asks_then_selected_project_maps_its_own_criteria(self):
        context={};key='chat-context:u:dm'
        body,rows=ui.draft(USER,'uid','dm',key,context,RAW,'message')
        actions=[a for row in rows for a in row['actions']]
        self.assertIn('어느 프로젝트',body);self.assertNotIn('**업무목록**',body)
        self.assertEqual([a['text'] for a in actions[:2]],[p['name'] for p in PROJECTS])
        self.assertNotIn('보고 및 반영',[a['text'] for a in actions])
        r=reports.get(USER,context['reportId']);self.assertEqual(r['raw'],RAW)
        with patch.object(ui.report_transport,'send') as send:
            with self.assertRaisesRegex(ValueError,'프로젝트를 먼저'):reports.publish(USER,r['id'],1)
        send.assert_not_called()
        doc={'id':'com-task','collectionId':'com','title':'자료 정리','text':'live source','revision':3,'updatedAt':'now','url':'/doc/com-task'}
        with patch.object(outline,'document',return_value=doc),patch.object(outline,'projected',return_value=tasks()[1]), \
             patch.object(outline,'can_report'),patch.object(outline,'authorize_changes'), \
             patch.object(criteria,'parse',return_value=tasks()[1]['criteria']),patch.object(outline,'api') as api:
            choice=chat_ui.resolve(key,actions[1]['msg'])
            body,rows=ui.route(USER,'uid','dm',key,context,actions[1]['msg'],choice)
        api.assert_not_called()
        r=reports.get(USER,r['id']);g=r['groups'][0]
        self.assertEqual(r['raw'],RAW);self.assertEqual(g['task_id'],'com-task')
        self.assertEqual([i['id'] for i in g['items']],['com-doc','com-image'])
        self.assertTrue(all(i['state']=='완료' for i in g['items']))
        self.assertIn('자료 정리 (의사소통 도구 선정)',body)
        self.assertIn('보고 및 반영',[a['text'] for row in rows for a in row['actions']])
        with self.assertRaises(HTTPException):reports.choose(USER,r['id'],1,0,'candidate','sat-task')

    def test_unknown_candidate_or_revoked_access_cannot_be_selected(self):
        r=reports.create(USER,RAW,'draft','uid','dm')
        with self.assertRaises(ValueError):reports.choose(USER,r['id'],1,0,'candidate','not-offered')
        with patch.object(outline,'document',side_effect=HTTPException(403,'권한 없음')):
            with self.assertRaises(HTTPException):reports.choose(USER,r['id'],1,0,'candidate','com-task')
        self.assertTrue(reports.get(USER,r['id'])['groups'][0]['needs_task_choice'])

    def test_multiple_ambiguous_groups_ask_one_at_a_time(self):
        r=reports.create(USER,RAW,'draft','uid','dm')
        r['groups'].append(copy.deepcopy(r['groups'][0]))
        r['groups'][0].update(needs_task_choice=False,kind='update',project_id='sat',project_name=PROJECTS[0]['name'])
        body,rows=ui.view('u:dm',r)
        first=chat_ui.resolve('u:dm',rows[0]['actions'][0]['msg'])
        self.assertEqual(first['index'],1);self.assertNotIn('**업무목록**',body)

    def test_same_project_twins_still_require_a_choice_and_choices_paginate(self):
        twins=[{**tasks()[0],'id':f'twin-{n}'} for n in range(8)]
        self.inventory.return_value=(PROJECTS,twins)
        self.extract.return_value=extracted(task_id='twin-0')
        r=reports.create(USER,RAW,'draft','uid','dm')
        self.assertEqual(len(r['groups'][0]['options']),8)
        body,rows=ui.view('u:dm',r)
        actions=[a for row in rows for a in row['actions']]
        self.assertIn('1/2쪽',body);self.assertEqual(len({a['text'] for a in actions}),len(actions))
        nxt=next(a for a in actions if a['text']=='다음')
        body,rows=ui.route(USER,'uid','dm','u:dm',{},nxt['msg'],chat_ui.resolve('u:dm',nxt['msg']))
        self.assertIn('2/2쪽',body)
        targets=[chat_ui.resolve('u:dm',a['msg']) for row in rows for a in row['actions']]
        self.assertEqual([a['target'] for a in targets if a['op']=='candidate'],['twin-6','twin-7'])


if __name__=='__main__':unittest.main()
