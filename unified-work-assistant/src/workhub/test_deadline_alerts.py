"""Clock, durable delivery, DM authorization and report regression boundaries."""
import concurrent.futures
import copy
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

from . import deadline_alerts as alerts, my_tasks, store, bot, report_chat, reports, report_transport, chat_ui
from .test_my_tasks import USER, task, item

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=my_tasks.KST)


def inventory(*tasks):
    rows = [my_tasks.personal(t, USER, NOW.date()) for t in tasks]
    return {'rows': [r for r in rows if r], 'complete': True}


class DeadlineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.mock(store, 'DB', temp.name + '/test.db')
        store.init()
        self.messages = {}
        self.room = {'_id': 'dm', 't': 'd', 'uids': ['uid', 'bot']}
        self.mongo = MagicMock()
        self.mongo.rocketchat.rocketchat_room.find_one.side_effect = lambda query: copy.deepcopy(self.room)
        self.mongo.rocketchat.rocketchat_message.find_one.side_effect = lambda query: self.messages.get(query['_id'])
        self.mongo.rocketchat.users.find_one.return_value = {'username': 'alice', 'active': True}
        self.b = SimpleNamespace(mongo=self.mongo, bot_id='bot', headers={'fixture': 'fixture'},
                                 identity=MagicMock(return_value=USER), api=MagicMock(side_effect=self.api))
        self.mock(report_transport, 'client', lambda: self.b)
        self.collect = self.mock(my_tasks, 'collect', MagicMock(return_value=inventory(task(due='2026-10-12', items=[item()]))))
        self.mock(alerts, 'enabled', lambda: True)

    def mock(self, obj, name, value):
        p = patch.object(obj, name, value)
        p.start()
        self.addCleanup(p.stop)
        return value

    def api(self, name, body):
        if name == 'dm.create':
            self.room = {'_id': 'dm', 't': 'd', 'uids': ['uid', 'bot']}
            return {'success': True, 'room': {'rid': 'dm'}}
        self.assertEqual(name, 'chat.sendMessage')
        msg = body['message']
        self.assertNotIn(msg['_id'], self.messages)
        self.messages[msg['_id']] = {**msg, 'u': {'_id': 'bot'}}
        return {'success': True, 'message': self.messages[msg['_id']]}

    def deliver(self, now=NOW):
        return alerts.deliver('uid', USER['sub'], now)

    def test_inclusive_three_days_and_all_overdue_excluding_completed_undated(self):
        tasks = [task(str(n), due=due) for n, due in enumerate(
            ['2025-01-01', '2026-10-11', '2026-10-12', '2026-10-13', '2026-10-15', '2026-10-16', '미정'])]
        tasks += [task('complete', due='2026-10-12', status='완료'),
                  task('mine-complete', due='2026-10-12', items=[item(state='완료'), item('other@example.com')]),
                  task('other', due='2026-10-12', owner='other@example.com')]
        self.assertEqual([r['id'] for r in alerts.due_rows(inventory(*tasks), NOW.date())], ['0', '1', '2', '3', '4'])

    def test_manual_completed_task_with_unchecked_criterion_is_excluded(self):
        self.assertEqual(alerts.due_rows(inventory(task(due='2026-10-12', status='완료', items=[item()])), NOW.date()), [])

    def test_shared_owner_only_gets_their_remaining_criteria(self):
        d = inventory(task(due='2026-10-12', owner='lead@example.com', items=[item(), item('other@example.com', n=2)]))
        text = alerts.render(alerts.due_rows(d, NOW.date()), NOW.date())
        self.assertIn('내 완료 기준: 0/1 완료', text)
        self.assertNotIn('완료 기준 2', text)

    def test_clock_only_scheduled_korean_time_with_bounded_recovery(self):
        with patch.object(alerts, 'recipients', return_value=[('uid', USER['sub'])]) as recipients:
            self.assertEqual(alerts.tick(NOW - timedelta(seconds=1)), {})
            recipients.assert_not_called()
            self.assertEqual(alerts.tick(NOW.astimezone(timezone.utc)), {'SENT': 1})
            self.assertEqual(alerts.tick(NOW + timedelta(minutes=14)), {'ALREADY_CHECKED': 1})
            self.assertEqual(alerts.tick(NOW + timedelta(minutes=15)), {})
            self.assertEqual(alerts.tick(NOW + timedelta(hours=1)), {})

    def test_schedule_window_can_cross_an_hour_boundary(self):
        with patch.object(alerts, 'HOUR', 17), patch.object(alerts, 'MINUTE', 55), \
                patch.object(alerts, 'recipients', return_value=[('uid', USER['sub'])]):
            self.assertEqual(alerts.tick(NOW.replace(hour=18, minute=5)), {'SENT': 1})
            self.assertEqual(alerts.tick(NOW.replace(hour=18, minute=10)), {})

    def test_global_switch_suppresses_scheduler(self):
        with patch.object(alerts, 'enabled', return_value=False), patch.object(alerts, 'recipients') as recipients:
            self.assertEqual(alerts.tick(NOW), {})
            recipients.assert_not_called()

    def test_not_ready_waits_without_claiming_day(self):
        self.b.headers = {}
        self.assertEqual(alerts.tick(NOW), {})
        with store.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM deadline_deliveries').fetchone()[0], 0)

    def test_settings_persist_for_subject_and_exact_commands_only(self):
        self.assertTrue(alerts.preference(USER)['enabled'])
        self.assertIn('09:00', alerts.route(USER, 'uid', 'dm', '알림')[0])
        text, buttons = alerts.route(USER, 'uid', 'dm', '알림 끄기')
        self.assertIn('껐어요', text)
        self.assertEqual(buttons[0]['actions'][0]['msg'], '알림 받기')
        store.init()
        self.assertFalse(alerts.preference({**USER, 'email': 'renamed@example.com'})['enabled'])
        self.assertEqual(self.deliver(), 'SKIPPED')
        self.collect.assert_not_called()
        alerts.route(USER, 'uid', 'dm', '알림 받기')
        self.assertTrue(alerts.preference(USER)['enabled'])
        self.assertIsNone(alerts.route(USER, 'uid', 'dm', '알림 기능 검증 완료'))
        self.assertIsNone(alerts.route(USER, 'uid', 'dm', '보고'))

    def test_setting_change_requires_exact_bot_dm_and_identity(self):
        for room in [{'t': 'c', 'uids': ['uid', 'bot']}, {'t': 'd', 'uids': ['uid', 'bot', 'other']},
                     {'t': 'd', 'uids': ['other', 'bot']}]:
            self.room = {'_id': 'dm', **room}
            with self.assertRaises(HTTPException): alerts.route(USER, 'uid', 'dm', '알림 끄기')
            self.assertTrue(alerts.preference(USER)['enabled'])

    def test_daily_digest_once_even_after_restart_and_again_next_day(self):
        self.assertEqual(self.deliver(), 'SENT')
        store.init()
        self.assertEqual(self.deliver(NOW + timedelta(seconds=30)), 'ALREADY_CHECKED')
        self.assertEqual(self.deliver(NOW + timedelta(days=1)), 'SENT')
        self.assertEqual(len(self.messages), 2)

    def test_empty_day_creates_no_dm_or_message(self):
        self.collect.return_value = inventory(task(due='2026-10-16'))
        self.assertEqual(self.deliver(), 'EMPTY')
        self.b.api.assert_not_called()

    def test_partial_inventory_retries_instead_of_saying_no_work(self):
        self.collect.return_value = {'rows': [], 'complete': False}
        self.assertEqual(self.deliver(), 'RETRY')
        self.b.api.assert_not_called()
        self.assertEqual(self.deliver(NOW + timedelta(seconds=30)), 'ALREADY_CHECKED')
        self.collect.return_value = inventory(task(due='2026-10-12'))
        self.assertEqual(self.deliver(NOW + timedelta(seconds=60)), 'SENT')

    def test_failure_retries_are_bounded_and_use_same_message_id(self):
        self.b.api.side_effect = RuntimeError('unavailable')
        self.assertEqual(self.deliver(), 'RETRY')
        self.assertEqual(self.deliver(NOW + timedelta(seconds=60)), 'RETRY')
        self.assertEqual(self.deliver(NOW + timedelta(seconds=120)), 'RETRY')
        self.assertEqual(self.deliver(NOW + timedelta(seconds=180)), 'ALREADY_CHECKED')
        self.assertEqual(len({call.args[1]['message']['_id'] for call in self.b.api.call_args_list}), 1)
        self.assertEqual(self.b.api.call_count, 3)

    def test_success_false_is_not_marked_delivered(self):
        self.b.api.side_effect = None
        self.b.api.return_value = {'success': False}
        self.assertEqual(self.deliver(), 'RETRY')

    def test_lost_response_reconciles_existing_message_without_second_post(self):
        def lost(name, body):
            self.api(name, body)
            raise TimeoutError('committed but response lost')
        self.b.api.side_effect = lost
        self.assertEqual(self.deliver(), 'RETRY')
        store.init()
        self.assertEqual(self.deliver(NOW + timedelta(seconds=60)), 'SENT')
        self.assertEqual(self.b.api.call_count, 1)
        self.assertEqual(len(self.messages), 1)

    def test_concurrent_claim_and_crash_lease(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            jobs = list(pool.map(lambda _: alerts.claim('concurrent', NOW), range(4)))
        self.assertEqual(sum(job is not None for job in jobs), 1)
        self.assertIsNone(alerts.claim('concurrent', NOW + timedelta(seconds=179)))
        later = alerts.claim('concurrent', NOW + timedelta(seconds=180))
        self.assertEqual(later['message_id'], next(job for job in jobs if job)['message_id'])
        first = next(job for job in jobs if job)
        alerts.finish(first, 'SENT', NOW)
        with store.db() as c:
            self.assertEqual(c.execute('SELECT state FROM deadline_deliveries WHERE subject=?', ('concurrent',)).fetchone()[0], 'SENDING')

    def test_completed_or_rescheduled_before_send_is_rechecked(self):
        self.collect.side_effect = [inventory(task(due='2026-10-12')), inventory(task(due='2026-10-20'))]
        self.assertEqual(self.deliver(), 'EMPTY')
        self.b.api.assert_not_called()

    def test_permission_revoked_before_send_prevents_delivery(self):
        # Identity is also checked by require_dm, so revoke at the final inventory.
        self.collect.side_effect = [inventory(task(due='2026-10-12')), HTTPException(403, 'revoked')]
        self.assertEqual(self.deliver(), 'RETRY')
        self.b.api.assert_not_called()

    def test_disable_during_read_prevents_pending_send(self):
        def read(user, now):
            store.put('deadline-preference:' + USER['sub'], {'enabled': False})
            return inventory(task(due='2026-10-12'))
        self.collect.side_effect = read
        self.assertEqual(self.deliver(), 'SKIPPED')
        self.b.api.assert_not_called()

    def test_changed_sso_subject_prevents_delivery(self):
        self.b.identity.return_value = {**USER, 'sub': 'different'}
        self.assertEqual(self.deliver(), 'RETRY')
        self.collect.assert_not_called()

    def test_creates_missing_dm_then_verifies_both_participants(self):
        self.room = None
        self.assertEqual(self.deliver(), 'SENT')
        self.assertEqual(self.b.api.call_args_list[0].args, ('dm.create', {'username': 'alice'}))
        self.assertEqual(next(iter(self.messages.values()))['rid'], 'dm')

    def test_channel_or_group_or_blocked_dm_not_used(self):
        for n, room in enumerate([{'t': 'c'}, {'t': 'd', 'uids': ['uid', 'bot', 'other']},
                                  {'t': 'd', 'blocked': ['bot']}, {'t': 'd', 'encrypted': True}]):
            self.room = {'_id': 'dm', 't': 'd', 'uids': ['uid', 'bot'], **room}
            self.assertEqual(self.deliver(NOW + timedelta(days=n)), 'RETRY')
        self.b.api.assert_not_called()

    def test_recipients_skip_missing_conflicting_and_duplicated_sso_bindings(self):
        self.mongo.rocketchat.users.find.return_value = [
            {'_id': 'a', 'services': {'authentik': {'id': 'good'}}},
            {'_id': 'b', 'services': {'Authentik': {'sub': 'duplicate'}}},
            {'_id': 'c', 'services': {'authentik': {'id': 'duplicate'}}},
            {'_id': 'd', 'services': {'authentik': {'id': 'one', 'sub': 'two'}}},
            {'_id': 'e', 'services': {}},
            {'_id': 'bot', 'services': {'authentik': {'id': 'bot-sub'}}}]
        self.assertEqual(alerts.recipients(), [('a', 'good')])
        self.assertEqual(self.mongo.rocketchat.users.find.call_args.args[0], {'active': True})

    def test_bad_recipient_does_not_prevent_other_deliveries(self):
        with patch.object(alerts, 'recipients', return_value=[('bad', 'bad'), ('uid', USER['sub'])]), \
                patch.object(alerts, 'deliver', side_effect=[HTTPException(403, 'disabled'), 'SENT']):
            self.assertEqual(alerts.tick(NOW), {'UNAVAILABLE': 1, 'SENT': 1})

    def test_long_digest_is_one_bounded_message_with_overflow_count(self):
        d = inventory(*[task(str(n), due='2026-10-12', items=[{**item(), 'title': '긴 기준' * 80}]) for n in range(300)])
        text = alerts.render(d['rows'], NOW.date())
        self.assertLess(len(text), 9000)
        self.assertIn('오늘 마감 300', text)
        self.assertIn('이외 ', text)
        self.assertIn('`내 업무`', text)

    def test_grouped_digest_uses_personal_task_style_without_changing_inventory(self):
        rows = inventory(task('soon', '2026-10-15', items=[item()]),
                         task('today', '2026-10-12', items=[item(state='완료'), item(n=2)]),
                         task('late', '2026-10-10', items=[item()]))['rows']
        before = copy.deepcopy(rows)
        text = alerts.render(rows, NOW.date())
        self.assertLess(text.index('🔴 기한 초과'), text.index('오늘 마감 ·'))
        self.assertLess(text.index('오늘 마감 ·'), text.index('🔵 3일 이내 마감'))
        self.assertIn('내 완료 기준: 1/2 완료', text)
        self.assertIn('\n• 완료 기준 2 — 예정', text)
        self.assertNotIn('\n• 완료 기준 1 — 완료', text)
        self.assertIn('**2일 초과**', text)
        self.assertEqual(rows, before)

    def test_digest_sends_only_fixed_navigation_buttons(self):
        context = 'chat-context:' + USER['sub'] + ':dm'
        store.put('chat-menu:' + context, ['existing report action'])
        self.assertEqual(self.deliver(), 'SENT')
        message = next(iter(self.messages.values()))
        actions = [a for block in message['attachments'] for a in block['actions']]
        self.assertEqual([a['msg'] for a in actions], ['내 업무', '알림'])
        self.assertEqual(store.get('chat-menu:' + context), ['existing report action'])

    def test_markdown_labels_cannot_mention_others_or_inject_links(self):
        d = inventory(task(due='2026-10-12'))
        d['rows'][0].update(title='@all [제목]', url='http://outline.test/doc/a)@all')
        text = alerts.render(d['rows'], NOW.date())
        self.assertNotIn('@all', text)
        self.assertIn('%29%40all', text)
        d['rows'][0]['url'] = 'javascript:alert(1)'
        self.assertNotIn('javascript', alerts.render(d['rows'], NOW.date()))

    def test_automatic_delivery_and_settings_preserve_report_and_numbered_menu(self):
        context = 'chat-context:' + USER['sub'] + ':dm'
        keys = {context: {'reportId': 'r1', 'taskId': 'old', 'editingReport': {'id': 'r1', 'version': 2}},
                'chat-menu:' + context: ['old report command'],
                'report-v2:r1': {'id': 'r1', 'version': 2, 'groups': [], 'posting': {'state': 'NOT_POSTED'}}}
        for key, value in keys.items(): store.put(key, value)
        old = chat_ui.bind(context, '기존 보고', 'old report command', {'kind': 'report-v2', 'id': 'r1'})
        with patch.object(reports, 'submit') as submit, patch.object(report_chat, 'draft') as draft:
            self.assertEqual(self.deliver(), 'SENT')
            alerts.route(USER, 'uid', 'dm', '알림 끄기')
        submit.assert_not_called()
        draft.assert_not_called()
        for key, value in keys.items(): self.assertEqual(store.get(key), value)
        self.assertEqual(chat_ui.numbered(context, '1'), old['msg'])
        self.assertEqual(chat_ui.resolve(context, old['msg'])['id'], 'r1')

    def test_bot_handles_settings_without_report_route_or_draft(self):
        context = 'chat-context:' + USER['sub'] + ':dm'
        state = {'reportId': 'r1', 'taskId': 'old'}
        store.put(context, state)
        with patch.object(bot, 'identity', return_value=USER), patch.object(bot, 'say') as say, \
                patch.object(report_chat, 'route') as route, patch.object(report_chat, 'draft') as draft:
            bot.handle({'_id': 'setting', 'rid': 'dm', 'u': {'_id': 'uid'}, 'msg': '알림 끄기'})
        route.assert_not_called()
        draft.assert_not_called()
        self.assertIn('껐어요', say.call_args.args[1])
        self.assertEqual(store.get(context), state)

    def test_actual_report_can_be_posted_and_applied_after_digest_and_off_on(self):
        # Use real report/proposal/ACL/format code with only HTTP boundaries stubbed.
        from .test_report_submit_integration import SubmitIntegrationTests, USER as alice
        fixture = SubmitIntegrationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        # Fixture replaces transport client; restore our DM test transport for digest only.
        with patch.object(report_transport, 'client', return_value=self.b), \
                patch.object(my_tasks, 'collect', return_value=inventory(task(due='2026-10-12'))):
            self.assertEqual(self.deliver(), 'SENT')
            alerts.route(USER, 'uid', 'dm', '알림 끄기')
            alerts.route(USER, 'uid', 'dm', '알림 받기')
        result = reports.submit(alice, 'report', 1, 'room')
        self.assertEqual(result['posting']['state'], 'POSTED')
        self.assertEqual([g['state'] for g in result['groups']], ['APPLIED', 'APPLIED'])
        self.assertEqual(fixture.writes, {'login': 1, 'deploy': 1})
        self.assertEqual(len(fixture.messages), 1)


if __name__ == '__main__':
    unittest.main()
