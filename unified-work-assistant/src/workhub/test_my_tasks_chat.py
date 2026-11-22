import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from . import my_tasks, my_tasks_chat as chat, chat_ui, store, bot, report_chat
from .test_my_tasks import USER, NOW, task, item


def data(count=4):
    tasks=[task(str(n),due=['2026-09-28','2026-09-30','2026-10-02','미정'][n%4],items=[item()]) for n in range(count)]
    rows=[my_tasks.personal(t,USER,NOW.date()) for t in tasks]
    rows.sort(key=lambda t:my_tasks.GROUPS.index(t['group']))
    return {'rows':rows,'counts':{g:sum(t['group']==g for t in rows) for g in my_tasks.GROUPS},
            'at':NOW.isoformat(),'project_count':3,'failed':0,'invalid':0,'complete':True,'all_failed':False}


class MyTaskChatTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p=patch.object(store,'DB',os.path.join(self.tmp.name,'test.db'));p.start();self.addCleanup(p.stop);store.init()
        self.context='chat-context:s:r'
        p=patch.object(chat.report_transport,'require_dm');self.dm=p.start();self.addCleanup(p.stop)

    def route(self,text='내 업무',choice=None,state=None):
        return chat.route(USER,'uid','r',self.context,state or {},text,choice)

    def actions(self,attachments):return [a for r in attachments for a in r.get('actions',[])]

    def click(self,action,state=None):
        return self.route(action['msg'],chat_ui.resolve(self.context,action['msg']),state)

    @patch.object(my_tasks,'collect',return_value=data())
    def test_all_four_groups_and_no_report_mutations(self,collect):
        fixture=data();fixture['rows'][0]['title']='[일정 시연] 로그인 오류 재검증'
        collect.return_value=fixture
        state={'reportId':'r1','editingReport':{'id':'r1','version':2},'taskId':'old','collectionId':'old-p'}
        store.put(self.context,state)
        text,buttons=self.route(state=state)
        for s in ['기한 초과','오늘 마감','앞으로 할 업무','마감일 미정','2일 초과','내 완료 기준']:self.assertIn(s,text)
        self.assertEqual(store.get(self.context),state)
        labels=[a['text'] for a in self.actions(buttons)]
        self.assertEqual(labels[0],'1. [일정 시연] 로그인 오류 재검증 · 상세')
        self.assertNotIn('\\',labels[0])
        self.assertIn('\\[일정 시연\\]',text)  # Only the Markdown body is escaped.
        for removed in ('전체','기한 초과','오늘 마감','예정','마감일 미정','새로고침','보고 현황으로 돌아가기','보고하기','더보기'):
            self.assertNotIn(removed,labels)
        self.dm.assert_called_once()

    @patch.object(my_tasks,'collect',return_value=data(11))
    def test_pagination_no_omission_and_numbers_are_current(self,collect):
        text,buttons=self.route();self.assertIn('1–8/11건',text)
        nxt=self.actions(buttons)[0];self.assertEqual(nxt['text'],'↓ 더보기')
        self.assertEqual(buttons[0]['color'],'#047857')
        self.assertEqual(buttons[1]['title'],'업무별 상세 보기')
        self.assertIn('아직 3건의 업무가 더 있어요',text)
        text,buttons=self.click(nxt);self.assertIn('9–11/11건',text)
        self.assertNotIn('↓ 더보기',[a['text'] for a in self.actions(buttons)])
        self.assertNotIn('이전 목록',[a['text'] for a in self.actions(buttons)])
        self.assertEqual(collect.call_count,2)
        command=chat_ui.numbered(self.context,'1');choice=chat_ui.resolve(self.context,command)
        self.assertEqual(choice['task_id'],data(11)['rows'][8]['id'])
        with self.assertRaises(ValueError):chat_ui.numbered(self.context,'4')

    @patch.object(my_tasks,'collect',return_value=data())
    def test_filter_text_alias_still_works_without_filter_buttons(self,collect):
        text,_=self.route('내 업무 마감일 미정');self.assertIn('업무 3',text);self.assertNotIn('업무 0',text)
        text,_=self.route('내 업무 기한 초과');self.assertIn('업무 0',text);self.assertNotIn('업무 3',text)

    def test_forty_criteria_detail_all_pages_and_source_link(self):
        d=data(1);row=d['rows'][0]
        row['mine']=[item(n=n,state='완료' if n==1 else '예정') for n in range(1,41)]
        row['remaining']=row['mine'][1:]
        with patch.object(my_tasks,'collect',return_value=d):
            _,buttons=self.route();action=self.actions(buttons)[0]
            texts=[]
            for n in range(5):
                text,buttons=self.click(action);texts.append(text)
                self.assertTrue(any(a.get('url')==row['url'] for a in self.actions(buttons)))
                if n<4:
                    action=self.actions(buttons)[0];self.assertEqual(action['text'],'↓ 더보기')
                else:self.assertNotIn('↓ 더보기',[a['text'] for a in self.actions(buttons)])
                for removed in ('전체','기한 초과','오늘 마감','예정','마감일 미정','새로고침','보고 현황으로 돌아가기'):
                    self.assertNotIn(removed,[a['text'] for a in self.actions(buttons)])
        self.assertIn('☑ 완료 기준 1 — 완료',texts[0]);self.assertIn('완료 기준 40 — 예정',texts[-1])
        self.assertTrue(all(len(t)<9500 for t in texts))

    @patch.object(my_tasks,'collect',return_value=data())
    def test_old_button_refreshes_instead_of_pointing_elsewhere(self,collect):
        _,buttons=self.route();old=self.actions(buttons)[0]
        self.route()
        text,_=self.click(old)
        self.assertIn('이전 목록이 만료',text)

    @patch.object(my_tasks,'collect',return_value=data())
    def test_expired_session_refreshes(self,collect):
        _,buttons=self.route();old=self.actions(buttons)[0]
        saved=store.get('my-tasks-session:'+self.context);saved['until']='2000-01-01T00:00:00+09:00';store.put('my-tasks-session:'+self.context,saved)
        self.assertIn('만료',self.click(old)[0])

    @patch.object(my_tasks,'collect',return_value=data())
    def test_foreign_button_rejected(self,collect):
        _,buttons=self.route();cmd=self.actions(buttons)[0]['msg']
        with self.assertRaises(ValueError):chat.route(USER,'uid','other','chat-context:s:other',{},cmd,None)

    def test_removed_or_completed_task_not_shown_from_old_data(self):
        with patch.object(my_tasks,'collect',return_value=data()):_,buttons=self.route()
        with patch.object(my_tasks,'collect',return_value=data(0)):
            text,_=self.click(self.actions(buttons)[0])
        self.assertIn('현재 내 할 일에서 확인할 수 없어',text);self.assertNotIn('완료 기준 1',text)

    def test_failure_not_reported_as_successful_empty_result(self):
        d={**data(0),'complete':False,'all_failed':True,'failed':3}
        with patch.object(my_tasks,'collect',return_value=d):text,_=self.route()
        self.assertIn('불러오지 못했어요',text);self.assertNotIn('남은 내 업무가 없어요',text)

    def test_partial_result_is_labelled(self):
        d={**data(),'complete':False,'invalid':2,'failed':1}
        with patch.object(my_tasks,'collect',return_value=d):text,_=self.route()
        self.assertIn('확인된 할 일',text);self.assertIn('문서 2건',text)

    def test_other_commands_do_not_intercept_reports(self):
        self.assertIsNone(self.route('보고'));self.assertIsNone(self.route('내 업무는 오늘 다 끝냈어'))

    @patch.object(my_tasks,'collect',return_value=data())
    def test_bot_routes_query_before_report_and_preserves_draft(self,collect):
        state={'reportId':'r1','editingReport':{'id':'r1','version':2}}
        store.put(self.context,state)
        with patch.object(bot,'identity',return_value=USER),patch.object(bot,'say') as say,patch.object(report_chat,'draft') as draft:
            bot.handle({'_id':'m1','rid':'r','u':{'_id':'uid'},'msg':'내 업무'})
        draft.assert_not_called();self.assertIn('내 업무',say.call_args.args[1]);self.assertEqual(store.get(self.context),state)


if __name__=='__main__':unittest.main()
