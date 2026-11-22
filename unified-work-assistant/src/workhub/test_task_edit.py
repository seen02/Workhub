"""Task editing exercises real transforms and receipts against an isolated Outline fixture."""
import copy
import unittest
import hashlib
import hmac
import json
import time
import uuid
from fastapi import HTTPException
from . import task_edit, criteria, domain, human_tasks, store, outline, permissions
from . import test_kanban as fixture


class TaskEditTests(unittest.TestCase):
    setUp = fixture.KanbanTests.setUp
    mock = fixture.KanbanTests.mock
    set_criteria = fixture.KanbanTests.set_criteria

    def payload(self, changes=None):
        return {'collectionId': 'p', 'parentDocumentId': 'parent', 'requestId': 'edit-request',
                'edits': [{'documentId': 'task', 'revision': 1, 'updatedAt': 't1',
                           'canUpdate': True, 'changes': changes or {'due': '2026-10-15'}}]}

    def save(self, changes=None, user=fixture.USER, body=None):
        return task_edit.mutate(user, body or self.payload(changes))['results'][0]

    def test_preview_is_read_only_and_uses_real_calendar_shift(self):
        result = task_edit.preview(fixture.USER, self.payload({'shiftDays': 7, 'shiftBoth': True}))['results'][0]
        self.assertTrue(result['ok'])
        self.assertEqual(result['after']['start'], '2026-10-08')
        self.assertEqual(result['after']['due'], '2026-10-15')
        self.assertFalse(self.writes)
        self.assertIsNone(store.get('task-edit:a:edit-request'))

    def test_date_edit_preserves_notes_and_history_and_is_idempotent(self):
        result = self.save()
        self.assertTrue(result['ok'])
        self.assertEqual(result['card']['due'], '2026-10-15')
        self.assertIn('원본 메모', self.docs['task']['text'])
        self.assertIn('상태: 보류\n```', self.docs['task']['text'])
        self.assertIn('마감일: 2026-10-08 → 2026-10-15', self.docs['task']['text'])
        self.assertTrue(self.save()['ok'])
        self.assertEqual(len(self.writes), 1)

    def test_noop_does_not_write(self):
        self.assertTrue(self.save({'due': fixture.FIELDS['due']})['unchanged'])
        self.assertFalse(self.writes)

    def test_invalid_dates_and_inverted_dates_rejected(self):
        for change in ({'due': '2026-02-30'}, {'start': '2026-10-10'}, {'due': '2026-9-9'},
                       {'due': '2026-10-20', 'shiftDays': 7}):
            result = task_edit.preview(fixture.USER, self.payload(change))['results'][0]
            self.assertFalse(result['ok'])
            self.assertEqual(result['code'], 422)
        self.assertFalse(self.writes)

    def test_shift_undated_fields_stays_undated(self):
        self.docs['task']['text'] = domain.render({**fixture.FIELDS, 'due': '미정', 'start': '미정'})
        result = self.save({'shiftDays': 7, 'shiftBoth': True})
        self.assertTrue(result['unchanged'])
        self.assertFalse(self.writes)

    def test_reassignment_does_not_transfer_criteria_by_default(self):
        self.set_criteria()
        result = self.save({'owner': 'b@example.com'})
        self.assertTrue(result['ok'])
        self.assertEqual(result['card']['owner'], 'b@example.com')
        self.assertEqual(result['card']['criteria'][0]['owner'], 'a@example.com')
        self.assertTrue(self.save({'owner': 'b@example.com'})['ok'])
        self.assertEqual(len(self.writes), 1)

    def test_admin_transfers_only_previous_owners_unfinished_items(self):
        self.set_criteria()
        items = criteria.parse(self.docs['task']['text'])
        items += [{'id': 'C-33333333', 'title': '기존 완료', 'owner': 'a@example.com', 'state': '완료'}]
        self.docs['task']['text'] = criteria.replace(self.docs['task']['text'], items)
        result = self.save({'owner': 'b@example.com', 'transferCriteria': True}, user=fixture.ADMIN)
        self.assertTrue(result['ok'])
        self.assertEqual([i['owner'] for i in result['card']['criteria']], ['b@example.com', 'b@example.com', 'a@example.com'])

    def test_employee_cannot_transfer_or_edit_structure(self):
        self.set_criteria()
        for n, change in enumerate(({'criteria': []}, {'owner': 'b@example.com', 'transferCriteria': True})):
            result = self.save(body={**self.payload(change), 'requestId': 'denied-' + str(n)})
            self.assertEqual(result['code'], 403)
        self.assertFalse(self.writes)

    def test_nonowner_and_native_readonly_are_rejected(self):
        body = self.payload()
        body['edits'][0]['canUpdate'] = False
        self.assertEqual(self.save(body=body)['code'], 403)
        self.docs['task']['text'] = domain.render({**fixture.FIELDS, 'owner': 'b@example.com'})
        self.assertEqual(self.save()['code'], 403)
        self.assertFalse(self.writes)

    def test_invalid_assignee_rejected(self):
        self.assertEqual(self.save({'owner': 'outside@example.com'})['code'], 403)
        self.assertFalse(self.writes)

    def test_criteria_rename_reorder_delete_add_preserves_states_and_audit(self):
        self.set_criteria()
        old = criteria.parse(self.docs['task']['text'])
        old[0]['state'] = '완료'
        self.docs['task']['text'] = criteria.replace(self.docs['task']['text'], old)
        entries = [{'id': '', 'title': '추가한 기준', 'owner': 'b@example.com'},
                   {'id': old[0]['id'], 'title': '수정한 기준', 'owner': 'b@example.com'}]
        result = self.save({'criteria': entries}, user=fixture.ADMIN)
        self.assertTrue(result['ok'])
        self.assertEqual([i['state'] for i in result['card']['criteria']], ['예정', '완료'])
        self.assertEqual(result['card']['progress'], 50)
        self.assertIn('다른 기준', self.docs['task']['text'])  # deleted title remains in history
        self.assertEqual(len(criteria.parse(self.docs['task']['text'])), 2)

    def test_existing_criteria_cannot_all_be_deleted(self):
        self.set_criteria()
        self.assertEqual(self.save({'criteria': []}, user=fixture.ADMIN)['code'], 422)
        self.assertFalse(self.writes)
    def test_removing_unfinished_work_completes_remaining_criteria_task(self):
        self.set_criteria()
        items=criteria.parse(self.docs['task']['text'])
        items[0]['state']='완료'
        text=criteria.replace(self.docs['task']['text'],items)
        self.docs['task']['text']=domain.patch_text(outline.task_status.mark_manual(text),{'status':'진행 중'})
        result=self.save({'criteria':[{k:items[0][k] for k in ('id','title','owner')}]},user=fixture.ADMIN)
        self.assertTrue(result['ok'])
        self.assertEqual(result['card']['status'],'완료')
        self.assertEqual(result['card']['progress'],100)
    def test_reopening_completed_plain_task_with_planned_criteria_is_not_started(self):
        self.docs['task']['text']=domain.patch_text(self.docs['task']['text'],{'status':'완료','progress':'100%'})
        result=self.save({'criteria':[{'id':'','title':'새 예정 기준','owner':'a@example.com'}],'reopen':True},user=fixture.ADMIN)
        self.assertTrue(result['ok'])
        self.assertEqual(result['card']['status'],'미착수')
        self.assertEqual(result['card']['progress'],0)

    def test_duplicate_unknown_and_invalid_criteria_rejected(self):
        self.set_criteria()
        first = {'id': 'C-11111111', 'title': '정상 기준', 'owner': 'a@example.com'}
        for entries in ([first, first], [{**first, 'id': 'C-ffffffff'}], [{**first, 'title': '[잘못]'}], [{**first, 'owner': 'outside@example.com'}]):
            self.assertFalse(task_edit.preview(fixture.ADMIN, self.payload({'criteria': entries}))['results'][0]['ok'])
        self.assertFalse(self.writes)

    def test_completed_task_requires_explicit_reopen(self):
        self.set_criteria()
        old = criteria.parse(self.docs['task']['text'])
        for item in old:
            item['state'] = '완료'
        self.docs['task']['text'] = domain.patch_text(criteria.replace(self.docs['task']['text'], old), {'status': '완료'})
        entries = [{k: i[k] for k in ('id', 'title', 'owner')} for i in old] + [{'id': '', 'title': '새 기준', 'owner': 'a@example.com'}]
        self.assertEqual(self.save({'criteria': entries}, user=fixture.ADMIN)['code'], 422)
        result = self.save({'criteria': entries, 'reopen': True}, user=fixture.ADMIN, body={**self.payload({'criteria': entries, 'reopen': True}), 'requestId': 'reopen'})
        self.assertTrue(result['ok'])
        self.assertEqual(result['card']['status'], '진행 중')

    def test_automatic_completion_also_requires_reopen(self):
        self.set_criteria()
        old = criteria.parse(self.docs['task']['text'])
        for item in old:
            item['state'] = '완료'
        self.docs['task']['text'] = criteria.replace(self.docs['task']['text'], old)
        entries = [{k: i[k] for k in ('id', 'title', 'owner')} for i in old] + [{'id': '', 'title': '새 기준', 'owner': 'a@example.com'}]
        self.assertEqual(self.save({'criteria': entries}, user=fixture.ADMIN)['code'], 422)

    def test_lost_response_recovery_never_repeats_write(self):
        self.loss = True
        self.assertTrue(self.save()['ok'])
        self.assertTrue(self.save()['ok'])
        self.assertEqual(len(self.writes), 1)

    def test_uncertain_read_recovers_after_assignment_away(self):
        self.read_loss = True
        self.assertEqual(self.save({'owner': 'b@example.com'})['code'], 503)
        self.read_loss = False
        self.assertTrue(self.save({'owner': 'b@example.com'})['ok'])
        self.assertEqual(len(self.writes), 1)

    def test_changed_payload_rejected_for_entire_receipt(self):
        self.save()
        with self.assertRaises(HTTPException) as error:
            self.save({'due': '2026-10-16'})
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(self.writes), 1)

    def test_permission_rechecked_on_replay(self):
        self.save()
        body = self.payload()
        body['edits'][0]['canUpdate'] = False
        self.assertEqual(self.save(body=body)['code'], 403)
        self.assertEqual(len(self.writes), 1)

    def test_admin_role_revocation_blocks_pending_structural_write(self):
        self.set_criteria()
        old = criteria.parse(self.docs['task']['text'])
        entries = [{k: i[k] for k in ('id', 'title', 'owner')} for i in old]
        entries[0]['title'] = '변경할 기준'
        body = self.payload({'criteria': entries})
        api = outline.api.side_effect
        def unavailable(method, payload, **kwargs):
            if method == 'documents.update':
                raise TimeoutError('not written')
            return api(method, payload, **kwargs)
        with fixture.patch.object(outline, 'api', side_effect=unavailable):
            self.assertEqual(self.save(user=fixture.ADMIN, body=body)['code'], 503)
        self.assertEqual(self.save(user=fixture.USER, body=body)['code'], 403)
        self.assertFalse(self.writes)

    def test_partial_batch_and_retry_only_writes_success_once(self):
        self.docs['task2'] = {**copy.deepcopy(self.docs['task']), 'id': 'task2'}
        body = self.payload()
        body['edits'].append({**body['edits'][0], 'documentId': 'task2', 'revision': 0})
        results = task_edit.mutate(fixture.USER, body)['results']
        self.assertEqual([r['ok'] for r in results], [True, False])
        self.assertEqual(results[1]['code'], 409)
        task_edit.mutate(fixture.USER, body)
        self.assertEqual(len(self.writes), 1)

    def test_stale_version_never_writes(self):
        body = self.payload()
        body['edits'][0]['revision'] = 0
        self.assertEqual(self.save(body=body)['code'], 409)
        self.assertFalse(self.writes)

    def test_undo_restores_values_but_keeps_change_and_undo_history(self):
        self.save()
        result = task_edit.mutate(fixture.USER, self.payload(), undo=True)['results'][0]
        self.assertTrue(result['ok'])
        self.assertEqual(result['card']['due'], fixture.FIELDS['due'])
        self.assertIn('업무 빠른 수정', self.docs['task']['text'])
        self.assertIn('빠른 수정 실행 취소', self.docs['task']['text'])
        self.assertTrue(task_edit.mutate(fixture.USER, self.payload(), undo=True)['results'][0]['ok'])
        self.assertEqual(len(self.writes), 2)

    def test_undo_rejects_following_native_edit(self):
        self.save()
        self.docs['task']['text'] += '\n추가 메모'
        self.docs['task']['revision'] += 1
        result = task_edit.mutate(fixture.USER, self.payload(), undo=True)['results'][0]
        self.assertEqual(result['code'], 409)
        self.assertEqual(len(self.writes), 1)

    def test_undo_reassignment_can_be_recovered_by_original_actor(self):
        self.save({'owner': 'b@example.com'})
        result = task_edit.mutate(fixture.USER, self.payload({'owner': 'b@example.com'}), undo=True)['results'][0]
        self.assertTrue(result['ok'])
        self.assertEqual(result['card']['owner'], 'a@example.com')

    def test_uncertain_undo_reassignment_recovers_with_original_authority(self):
        body = self.payload({'owner': 'b@example.com'})
        self.save(body=body)
        # Lose the reads only after the undo write, not its initial source read.
        # Simulate a successful undo whose response is lost by failing projection.
        with fixture.patch.object(outline, 'record', side_effect=TimeoutError('lost')):
            self.assertEqual(task_edit.mutate(fixture.USER, body, undo=True)['results'][0]['code'], 503)
        result = task_edit.mutate(fixture.USER, body, undo=True)['results'][0]
        self.assertTrue(result['ok'])
        self.assertEqual(len(self.writes), 2)

    def test_deleted_moved_and_archived_tasks_rejected(self):
        for n, change in enumerate(({'deletedAt': 'now'}, {'parentDocumentId': 'other'}, {'archivedAt': 'now'})):
            original = copy.deepcopy(self.docs['task'])
            self.docs['task'].update(change)
            self.assertEqual(self.save(body={**self.payload(), 'requestId': 'invalid-' + str(n)})['code'], 409)
            self.docs['task'] = original
        self.assertFalse(self.writes)

    def test_human_template_combined_edit_preserves_body_and_derived_ids(self):
        self.mock(human_tasks, 'people', return_value=fixture.PEOPLE)
        self.mock(human_tasks, 'validate_assignment', return_value=None)
        self.docs['task']['text'] = ('담당자: 직원 A (a@example.com)\n\n시작일: 2026-10-01\n\n마감일: 2026-10-08\n\n상태: 진행 중\n\n진행률: 50%\n\n'
                                     '## 업무 내용\n\n원본 내용\n\n## 완료 기준\n\n- [x] 첫 기준 — 담당자: 직원 A (a@example.com)\n- [ ] 다른 기준 — 담당자: 직원 B (b@example.com)')
        old = criteria.parse(self.docs['task']['text'])
        entries = [{k: i[k] for k in ('id', 'title', 'owner')} for i in reversed(old)]
        entries[1]['title'] = '수정한 첫 기준'
        result = self.save({'due': '2026-10-20', 'criteria': entries}, user=fixture.ADMIN)
        self.assertTrue(result['ok'])
        self.assertEqual(result['card']['progress'], 50)
        self.assertEqual(result['card']['criteria'][1]['state'], '완료')
        self.assertIn('원본 내용', self.docs['task']['text'])


class EditBridgeTests(fixture.BridgeTests):
    def edit_request(self, action='preview', signature=True, **extra):
        body = {'collectionId': str(uuid.uuid4()), 'parentDocumentId': str(uuid.uuid4()),
                'requestId': str(uuid.uuid4()), 'actor': {'outlineUserId': 'a', 'outlineTeamId': 't'},
                'edits': [{'documentId': str(uuid.uuid4()), 'revision': 1, 'updatedAt': 't1',
                           'canUpdate': True, 'changes': {'due': '2026-10-20'}}], **extra}
        path = '/internal/outline-kanban/' + action
        raw = json.dumps(body).encode(); stamp = str(int(time.time())); nonce = str(uuid.uuid4())
        message = '\n'.join(['POST', path, stamp, nonce, hashlib.sha256(raw).hexdigest()])
        signed = hmac.new(b'kanban-test', message.encode(), hashlib.sha256).hexdigest()
        return self.client.post(path, content=raw, headers={'Content-Type': 'application/json', 'X-Workhub-Time': stamp,
                                'X-Workhub-Nonce': nonce, 'X-Workhub-Signature': signed if signature else 'invalid'})

    def test_signed_edit_preview_dispatches_without_optional_null_fields(self):
        with fixture.patch.object(task_edit, 'preview', return_value={'results': []}) as preview:
            response = self.edit_request()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(preview.call_args[0][1]['edits'][0]['changes'], {'due': '2026-10-20'})
        self.assertTrue(preview.call_args[0][1]['edits'][0]['canUpdate'])

    def test_unsigned_edit_is_rejected_before_dispatch(self):
        with fixture.patch.object(task_edit, 'preview') as preview:
            self.assertEqual(self.edit_request(signature=False).status_code, 401)
        preview.assert_not_called()

    def test_duplicate_targets_and_oversized_batches_are_rejected(self):
        item = {'documentId': str(uuid.uuid4()), 'revision': 1, 'updatedAt': 't1', 'changes': {'shiftDays': 7}}
        self.assertEqual(self.edit_request(edits=[item, item]).status_code, 422)
        self.assertEqual(self.edit_request(edits=[item] * 101).status_code, 422)

    def test_edit_schema_rejects_client_identity_and_criterion_state(self):
        from .main import KanbanBody
        from pydantic import ValidationError
        base = {'actor': {'outlineUserId': 'user', 'outlineTeamId': 'team'},
                'collectionId': '00000000-0000-4000-8000-000000000001',
                'parentDocumentId': '00000000-0000-4000-8000-000000000002',
                'edits': [{'documentId': '00000000-0000-4000-8000-000000000003', 'revision': 1, 'updatedAt': 't1',
                           'changes': {'criteria': [{'id': '', 'title': '새 기준', 'owner': 'a@example.com', 'state': '완료'}]}}]}
        with self.assertRaises(ValidationError):
            KanbanBody.model_validate(base)
