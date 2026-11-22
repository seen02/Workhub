import concurrent.futures
import json
import os
import tempfile
import unittest
import uuid
from datetime import date, datetime, timedelta
from unittest.mock import patch
from fastapi import HTTPException
from . import domain, human_tasks, outline, outline_bridge, permissions, store, task_creation
from . import recurring_schedule as schedule, recurring_service as service
from . import recurring_store as records, recurring_worker as worker

CID, PARENT, OUTLINE_ID, OTHER_ID, TEAM = [str(uuid.uuid4()) for _ in range(5)]
USER = {'sub': str(uuid.uuid4()), 'email': 'owner@example.com', 'name': '담당자', 'admin': True}
IDENTITY = {'outlineUserId': OUTLINE_ID, 'outlineTeamId': TEAM}
PEOPLE = [{'id': 'outline:' + OUTLINE_ID, 'name': '담당자', 'email': USER['email']},
          {'id': 'outline:' + OTHER_ID, 'name': '동료', 'email': 'other@example.com'}]
AT = datetime(2026, 10, 28, 8, 30, tzinfo=schedule.KST)


def settings(**changes):
    return {'title': '주간 점검', 'ownerId': PEOPLE[0]['id'], 'notes': '결과를 기록하세요.',
            'criteria': [{'title': '점검 완료', 'assigneeId': PEOPLE[0]['id']}],
            'frequency': 'weekly', 'weekday': 2, 'monthDay': 1, 'startDate': '2026-10-28',
            'dueOffset': 4, 'unfinishedPolicy': 'create', **changes}


class RecurringCalendarTests(unittest.TestCase):
    def test_seven_am_boundary(self):
        for hour, minute, expected in [(6, 59, '2026-10-28'), (7, 0, '2026-11-04'), (7, 1, '2026-11-04')]:
            at = AT.replace(hour=hour, minute=minute)
            self.assertEqual(schedule.preview(settings(), at)[0]['date'], expected)

    def test_immediate_retains_today_and_original_due(self):
        row = schedule.preview(settings(), AT, include_today=True)[0]
        self.assertTrue(row['immediate']); self.assertEqual(row['date'], '2026-10-28')
        self.assertEqual(row['dueDate'], '2026-11-01')

    def test_short_month_reverts_to_original_day(self):
        body = settings(frequency='monthly', monthDay=31, startDate='2026-01-01')
        rows = schedule.preview(body, AT.replace(month=1, day=1))
        self.assertEqual([r['date'] for r in rows], ['2026-01-31', '2026-02-28', '2026-03-31'])

    def test_leap_year_and_last_day(self):
        body = settings(frequency='monthly', monthDay='last', startDate='2028-01-01')
        self.assertEqual(schedule.next_date(body, date(2028, 2, 1)), date(2028, 2, 29))

    def test_year_boundary(self):
        rows = schedule.preview(settings(frequency='monthly', monthDay=1, startDate='2026-12-01'), AT.replace(month=12, day=2))
        self.assertEqual(rows[0]['date'], '2027-01-01')

    def test_calendar_days_do_not_move_weekend(self):
        row = schedule.preview(settings(dueOffset=0), AT, include_today=True)[0]
        self.assertEqual(row['date'], row['dueDate'])

    def test_invalid_rules_fail(self):
        for changes in [{'dueOffset': -1}, {'dueOffset': 366}, {'weekday': 7}, {'weekday': True},
                        {'repeatCount': 0}, {'repeatCount': 521}, {'repeatCount': True},
                        {'taskStartOffset': 7, 'dueOffset': 1},
                        {'frequency': 'daily'}, {'startDate': '2026-02-29'},
                        {'frequency': 'monthly', 'monthDay': 0}]:
            with self.assertRaises(ValueError): schedule.validate(settings(**changes))

    def test_weekly_end_aligns_first_slot_before_counting(self):
        body = settings(weekday=0, repeatCount=4)
        self.assertEqual(schedule.first_date(body), date(2026, 11, 2))
        self.assertEqual(schedule.end_date(body), date(2026, 11, 23))

    def test_monthly_end_keeps_original_day_through_short_month(self):
        body = settings(frequency='monthly', monthDay=31, startDate='2028-01-01', repeatCount=3)
        self.assertEqual(schedule.end_date(body), date(2028, 3, 31))
        self.assertEqual(schedule.next_date(body, date(2028, 2, 1)), date(2028, 2, 29))

    def test_single_occurrence_has_no_following_slot(self):
        body = settings(repeatCount=1)
        self.assertEqual(len(schedule.preview(body, AT, include_today=True)), 1)
        self.assertIsNone(schedule.next_date(body, date(2026, 10, 29)))
        self.assertFalse(schedule.matches(body, date(2026, 11, 4)))

    def test_task_dates_are_independently_optional(self):
        day = date(2026, 10, 28)
        self.assertEqual(schedule.task_dates(settings(taskStartOffset=None, dueOffset=None), day),
                         {'startDate': None, 'dueDate': None})
        self.assertEqual(schedule.task_dates(settings(taskStartOffset=None, dueOffset=7), day),
                         {'startDate': None, 'dueDate': '2026-11-04'})


class RecurringExecutionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.patch(store, 'DB', os.path.join(self.folder.name, 'test.sqlite3'), value=True)
        store.init()
        environment = patch.dict(os.environ, {'OUTLINE_RECURRING_ENABLED': 'true', 'OUTLINE_WORKHUB_TEAM_ID': TEAM})
        environment.start(); self.addCleanup(environment.stop)
        self.patch(schedule, 'now', AT)
        self.patch(service, 'context', None)
        self.patch(task_creation, 'context', None)
        self.patch(permissions, 'assignees', PEOPLE)
        self.patch(human_tasks, 'people', PEOPLE)
        self.patch(outline_bridge, 'actor', USER)
        self.docs = {}; self.requests = []
        self.native = self.patch(worker, 'native_request', self.create, side=True)
        self.patch(outline, 'document', lambda key: self.docs[key], side=True)
        self.patch(outline, 'record', {'id': 'projected'})

    def patch(self, module, name, result, *, value=False, side=False):
        p = patch.object(module, name, result) if value else patch.object(module, name, side_effect=result) if side else patch.object(module, name, return_value=result)
        mock = p.start(); self.addCleanup(p.stop); return mock

    def create(self, payload):
        self.assertEqual(uuid.UUID(payload['documentId']).version, 4)
        self.requests.append(payload)
        self.docs.setdefault(payload['documentId'], {'id': payload['documentId'], 'text': payload['text'],
            'collectionId': CID, 'parentDocumentId': PARENT, 'publishedAt': 'now', 'url': '/doc/' + payload['documentId']})
        return {'id': payload['documentId'], 'title': payload['title'], 'url': self.docs[payload['documentId']]['url']}

    def save(self, *, body=None, mode='next', **changes):
        payload = {'collectionId': CID, 'parentDocumentId': PARENT, 'requestId': str(uuid.uuid4()),
                   'settings': settings(**changes), 'todayMode': mode, **(body or {})}
        return service.save(USER, IDENTITY, payload)

    def occurrences(self, rule_id):
        return service.history(USER, CID, PARENT, rule_id)['occurrences']

    def test_new_next_does_not_create_any_document(self):
        result = self.save()
        self.assertEqual(records.rule(result['id'])['next_date'], '2026-11-04')
        self.assertFalse(self.docs)

    def test_immediate_generates_one_standard_task(self):
        result = self.save(mode='now')
        self.assertEqual(len(self.docs), 1)
        doc = next(iter(self.docs.values()))
        fields = domain.parse(doc['text'])
        self.assertEqual(fields['status'], '미착수'); self.assertEqual(fields['progress'], '0%')
        self.assertEqual(fields['due'], '2026-11-01')
        self.assertEqual(self.occurrences(result['id'])[0]['status'], 'created')

    def test_last_occurrence_finishes_and_cannot_generate_more(self):
        result = self.save(mode='now', repeatCount=1)
        self.assertEqual(records.rule(result['id'])['state'], 'completed')
        self.assertEqual(records.rule(result['id'])['next_date'], '')
        worker.tick(at=AT + timedelta(weeks=3))
        self.assertEqual(len(self.docs), 1)

    def test_optional_dates_remain_unset_in_created_task(self):
        self.save(mode='now', repeatCount=1, taskStartOffset=None, dueOffset=None)
        fields = domain.parse(next(iter(self.docs.values()))['text'])
        self.assertEqual(fields['start'], '미정')
        self.assertEqual(fields['due'], '미정')

    def test_last_failed_write_can_be_retried_after_end(self):
        self.native.side_effect = HTTPException(403, '권한 확인')
        result = self.save(mode='now', repeatCount=1)
        self.assertEqual(records.rule(result['id'])['state'], 'needs_attention')
        occurrence = self.occurrences(result['id'])[0]
        self.native.side_effect = self.create
        service.process_occurrence(USER, {'collectionId': CID, 'parentDocumentId': PARENT,
            'ruleId': result['id'], 'occurrenceId': occurrence['id'], 'requestId': str(uuid.uuid4())}, 'retry')
        self.assertEqual(records.rule(result['id'])['state'], 'completed')
        self.assertEqual(len(self.docs), 1)

    def test_request_retry_returns_same_rule_and_document(self):
        body = {'requestId': str(uuid.uuid4())}
        first = self.save(body=body, mode='now'); second = self.save(body=body, mode='now')
        self.assertEqual(first, second); self.assertEqual(len(self.docs), 1)

    def test_changed_retry_is_rejected(self):
        body = {'requestId': str(uuid.uuid4())}; self.save(body=body)
        with self.assertRaises(HTTPException) as caught: self.save(body=body, title='다른 내용')
        self.assertEqual(caught.exception.status_code, 409)

    def test_preview_has_no_side_effects(self):
        service.preview(USER, CID, PARENT, settings())
        with store.db() as c: self.assertEqual(c.execute('SELECT COUNT(*) FROM recurring_rules').fetchone()[0], 0)
        self.assertFalse(self.docs)

    def test_employee_cannot_assign_other_owner(self):
        with self.assertRaises(HTTPException) as caught: service.clean_settings({**USER, 'admin': False}, CID, settings(ownerId=PEOPLE[1]['id']))
        self.assertEqual(caught.exception.status_code, 403)

    def test_criterion_outsider_rejected(self):
        with self.assertRaises(HTTPException): self.save(criteria=[{'title': '확인', 'assigneeId': 'outsider'}])

    def test_two_claimants_only_one_lease(self):
        result = self.save()
        row = records.reserve(records.rule(result['id']), '2026-11-04')
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            claims = list(pool.map(lambda _: records.claim(row['id']), range(2)))
        self.assertEqual(sum(bool(c) for c in claims), 1)

    def test_duplicate_reservation_keeps_one_v4_document_id(self):
        result = self.save(); rule = records.rule(result['id'])
        first = records.reserve(rule, '2026-11-04')
        second = records.reserve(rule, '2026-11-04')
        self.assertEqual(uuid.UUID(first['document_id']).version, 4)
        self.assertEqual(first['document_id'], second['document_id'])

    def test_legacy_frozen_v5_id_is_repaired_once_under_lease(self):
        result = self.save(); row = records.reserve(records.rule(result['id']), '2026-11-04')
        legacy_id = str(uuid.uuid5(uuid.NAMESPACE_URL, 'workhub-recurring-document:' + row['id']))
        payload = {'documentId': legacy_id, 'title': '원래 제목'}
        with store.db() as c:
            c.execute('UPDATE recurring_occurrences SET document_id=?,payload=? WHERE id=?',
                      (legacy_id, store.dump(payload), row['id']))
        lease = records.claim(row['id'])
        repaired = records.prepare_document_id(row['id'], lease)
        self.assertEqual(uuid.UUID(repaired['document_id']).version, 4)
        self.assertEqual(json.loads(repaired['payload']), {**payload, 'documentId': repaired['document_id']})
        self.assertEqual(records.prepare_document_id(row['id'], lease)['document_id'], repaired['document_id'])
        self.assertEqual(repaired['id'], row['id'])

    def test_stale_lease_cannot_repair_legacy_id(self):
        result = self.save(); row = records.reserve(records.rule(result['id']), '2026-11-04')
        legacy_id = str(uuid.uuid5(uuid.NAMESPACE_URL, 'workhub-recurring-document:' + row['id']))
        with store.db() as c:
            c.execute('UPDATE recurring_occurrences SET document_id=? WHERE id=?', (legacy_id, row['id']))
        records.claim(row['id'])
        with self.assertRaises(ValueError): records.prepare_document_id(row['id'], 'stale')
        self.assertEqual(records.occurrence(row['id'])['document_id'], legacy_id)

    def test_restart_reclaims_expired_lease(self):
        result = self.save(); row = records.reserve(records.rule(result['id']), '2026-11-04')
        first = records.claim(row['id'])
        with store.db() as c: c.execute('UPDATE recurring_occurrences SET lease_until=0 WHERE id=?', (row['id'],))
        self.assertNotEqual(records.claim(row['id']), first)

    def test_response_loss_reuses_frozen_uuid(self):
        def lost(payload): self.create(payload); raise TimeoutError('response lost')
        self.native.side_effect = lost
        result = self.save(mode='now'); occurrence = self.occurrences(result['id'])[0]
        self.assertEqual(occurrence['status'], 'reconciling')
        self.native.side_effect = self.create
        with store.db() as c: c.execute('UPDATE recurring_occurrences SET retry_at=0 WHERE id=?', (occurrence['id'],))
        worker.execute(occurrence['id'])
        self.assertEqual(len(self.docs), 1)
        self.assertEqual(self.requests[0], self.requests[1])
        self.assertEqual(self.occurrences(result['id'])[0]['status'], 'created')

    def test_projection_failure_does_not_create_another_doc(self):
        with patch.object(outline, 'record', return_value=None): result = self.save(mode='now')
        occurrence = self.occurrences(result['id'])[0]
        with store.db() as c: c.execute('UPDATE recurring_occurrences SET retry_at=0 WHERE id=?', (occurrence['id'],))
        worker.execute(occurrence['id']); self.assertEqual(len(self.docs), 1)

    def test_current_permission_loss_stops_rule(self):
        self.native.side_effect = HTTPException(403, '권한 회수')
        result = self.save(mode='now')
        self.assertEqual(records.rule(result['id'])['state'], 'needs_attention'); self.assertFalse(self.docs)

    def test_same_day_scheduler_and_manual_request_do_not_duplicate(self):
        result = self.save(mode='now')
        for _ in range(3): worker.tick(at=AT)
        self.assertEqual(len(self.docs), 1); self.assertEqual(len(self.occurrences(result['id'])), 1)

    def test_prior_dates_become_missed_without_mass_creation(self):
        result = self.save(startDate='2026-10-28')
        rule = records.rule(result['id']); body = json.loads(rule['body']); body['startDate'] = '2026-10-01'
        with store.db() as c: c.execute('UPDATE recurring_rules SET next_date=?,body=? WHERE id=?', ('2026-10-21', store.dump(body), rule['id']))
        worker.tick(at=AT)
        rows = self.occurrences(rule['id'])
        self.assertEqual({r['status'] for r in rows}, {'missed', 'created'}); self.assertEqual(len(self.docs), 1)

    def test_paused_rule_does_not_generate(self):
        result = self.save()
        with store.db() as c: c.execute("UPDATE recurring_rules SET state='paused',next_date=? WHERE id=?", ('2026-10-28', result['id']))
        worker.tick(at=AT); self.assertFalse(self.docs)

    def test_unfinished_previous_skips_following_occurrence(self):
        result = self.save(mode='now', unfinishedPolicy='skip')
        worker.tick(at=AT + timedelta(days=7))
        self.assertEqual(len(self.docs), 1)
        self.assertEqual(self.occurrences(result['id'])[0]['status'], 'skipped')

    def test_malformed_previous_needs_attention_instead_of_skipping(self):
        result = self.save(mode='now', unfinishedPolicy='skip')
        next(iter(self.docs.values()))['text'] = '업무 형식 삭제'
        worker.tick(at=AT + timedelta(days=7))
        self.assertEqual(self.occurrences(result['id'])[0]['status'], 'needs_attention')

    def test_revision_conflict_rejected(self):
        result = self.save()
        with self.assertRaises(HTTPException) as caught: self.save(body={'ruleId': result['id'], 'expectedRevision': 90})
        self.assertEqual(caught.exception.status_code, 409)

    def test_cross_collection_rule_lookup_denied(self):
        result = self.save()
        with self.assertRaises(HTTPException) as caught: service.get(USER, str(uuid.uuid4()), PARENT, result['id'])
        self.assertEqual(caught.exception.status_code, 404)

    def test_schema_is_additive_and_repeatable(self):
        records.init(); records.init()
        with store.db() as c: self.assertIsNotNone(c.execute("SELECT name FROM sqlite_master WHERE name='tasks'").fetchone())

    def test_feature_off_generates_nothing(self):
        with patch.dict(os.environ, {'OUTLINE_RECURRING_ENABLED': 'false'}):
            worker.tick(at=AT)
        self.assertFalse(self.docs)

    def test_now_option_before_seven_still_waits_until_seven(self):
        with patch.object(schedule, 'now', return_value=AT.replace(hour=6, minute=59)):
            result = self.save(mode='now')
        self.assertFalse(result['immediate']); self.assertFalse(self.docs)
        self.assertEqual(records.rule(result['id'])['next_date'], '2026-10-28')

    def test_pause_and_resume_preserve_documents_and_skip_paused_time(self):
        result = self.save(mode='now')
        common = {'collectionId': CID, 'parentDocumentId': PARENT, 'ruleId': result['id']}
        service.change(USER, IDENTITY, {**common, 'requestId': str(uuid.uuid4()), 'expectedRevision': 1}, 'pause')
        service.change(USER, IDENTITY, {**common, 'requestId': str(uuid.uuid4()), 'expectedRevision': 2}, 'resume')
        self.assertEqual(len(self.docs), 1)
        self.assertEqual(records.rule(result['id'])['next_date'], '2026-11-04')

    def test_manual_skip_response_loss_is_idempotent(self):
        result = self.save(); row = records.reserve(records.rule(result['id']), '2026-10-21', status='missed')
        body = {'collectionId': CID, 'parentDocumentId': PARENT, 'ruleId': result['id'],
                'occurrenceId': row['id'], 'requestId': str(uuid.uuid4())}
        first = service.process_occurrence(USER, body, 'skip')
        self.assertEqual(service.process_occurrence(USER, body, 'skip'), first)
        self.assertEqual(records.occurrence(row['id'])['status'], 'skipped')

    def test_unknown_write_cannot_be_silently_skipped(self):
        self.native.side_effect = TimeoutError('unknown')
        result = self.save(mode='now'); row = self.occurrences(result['id'])[0]
        body = {'collectionId': CID, 'parentDocumentId': PARENT, 'ruleId': result['id'],
                'occurrenceId': row['id'], 'requestId': str(uuid.uuid4())}
        with self.assertRaises(HTTPException) as caught: service.process_occurrence(USER, body, 'skip')
        self.assertEqual(caught.exception.status_code, 409)

    def test_explicit_admin_handover_updates_pending_execution_identity(self):
        self.native.side_effect = HTTPException(403, '권한 회수')
        result = self.save(mode='now'); row = self.occurrences(result['id'])[0]
        manager = {**USER, 'sub': str(uuid.uuid4())}
        service.change(manager, {**IDENTITY, 'outlineUserId': OTHER_ID},
                       {'collectionId': CID, 'parentDocumentId': PARENT, 'ruleId': result['id'],
                        'requestId': str(uuid.uuid4()), 'expectedRevision': 2}, 'adopt')
        pending = records.occurrence(row['id'])
        self.assertEqual(json.loads(pending['snapshot'])['executor_sub'], manager['sub'])
        self.assertEqual(json.loads(pending['payload'])['executorId'], OTHER_ID)
        self.assertEqual(records.rule(result['id'])['state'], 'paused')
