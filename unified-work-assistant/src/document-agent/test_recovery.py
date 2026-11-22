"""Integration fault tests: real Outline, controlled model output to isolate retries.

Run in the agent container with DATA_DIR=/app/data/recovery-tests.
Creates explicitly named test documents only in the test collection.
"""
import asyncio
import json
import os
import uuid
from pathlib import Path
from unittest.mock import patch

os.environ['DATA_DIR'] = '/app/data/recovery-tests'
import app as agent

COL = json.loads(Path('/app/data/test-collection.json').read_text())['id']
REAL = agent.outline
RUN = str(uuid.uuid4())[:8]


async def model_fixture(*args, **kwargs):
    return {'title': '재시도 테스트', 'items': [{'index': 1, 'organized': '검토 3건이 진행 중입니다.'}]}, {'fixture': True}


async def main():
    report = []
    for mode in ('lost_response', 'before_send'):
        calls = 0

        async def fault(method, payload, read=False):
            nonlocal calls
            if method == 'documents.create':
                calls += 1
                if calls == 1:
                    if mode == 'lost_response':
                        await REAL(method, payload, read)
                    raise agent.HTTPException(503, 'Injected connection failure')
            return await REAL(method, payload, read)

        req = agent.NoteRequest(text='검토 3건 진행 중', title=f'[복구 시험 {RUN}] {mode}',
                                collection_id=COL, request_id=f'{RUN}-{mode}')
        with patch.object(agent, 'outline', fault), patch.object(agent, 'llm', model_fixture):
            result = await agent.organize_note(req)
            duplicate = await agent.organize_note(req)
            new_id = await agent.organize_note(req.model_copy(update={'request_id': req.request_id + '-new'}))
        assert result['id'] == duplicate['id'] == new_id['id']
        assert duplicate['duplicate'] and new_id['duplicate']
        assert calls == (1 if mode == 'lost_response' else 2)
        try:
            await agent.organize_note(req.model_copy(update={'text': '내용 변경'}))
            raise AssertionError('request ID conflict was accepted')
        except agent.HTTPException as e:
            assert e.status_code == 409
        report.append({'test': mode, 'passed': True, 'create_calls': calls, 'document_id': result['id']})

    target = result['id']
    update_calls = 0

    async def patch_fixture(*args, **kwargs):
        return {'find_text': '검토 3건이 진행 중입니다.', 'replacement': '검토 3건이 완료되었습니다.'}, {'fixture': True}

    async def lost_update(method, payload, read=False):
        nonlocal update_calls
        value = await REAL(method, payload, read)
        if method == 'documents.update':
            update_calls += 1
            raise agent.HTTPException(503, 'Injected lost update response')
        return value

    req = agent.ReviseRequest(document_id=target, instruction='검토를 완료로 변경', request_id=RUN+'-update')
    with patch.object(agent, 'outline', lost_update), patch.object(agent, 'llm', patch_fixture):
        revised = await agent.revise_document(req)
        repeated = await agent.revise_document(req)
    assert update_calls == 1 and repeated['duplicate']
    assert '검토 3건이 완료되었습니다.' in revised['text']
    report.append({'test': 'lost_update_response', 'passed': True, 'update_calls': update_calls})

    # Server-side optimistic revision check must reject stale writes.
    doc = await agent.info(target)
    await REAL('documents.update', {'id': target, 'title': doc['title'] + ' (충돌 시험)', 'lastRevision': doc['revision']})
    try:
        await REAL('documents.update', {'id': target, 'text': '덮어쓰면 안 되는 값', 'lastRevision': doc['revision']})
        raise AssertionError('stale revision accepted')
    except agent.HTTPException as e:
        assert e.status_code == 409
    current = await agent.info(target)
    assert '덮어쓰면 안 되는 값' not in current['text']
    report.append({'test': 'stale_revision_conflict', 'passed': True})

    # Read-only connection errors are retried at HTTP transport boundary.
    real_post = agent.httpx.AsyncClient.post
    read_calls = 0

    async def flaky_post(self, url, **kwargs):
        nonlocal read_calls
        if url.endswith('/documents.info'):
            read_calls += 1
            if read_calls == 1:
                raise agent.httpx.ConnectError('Injected read failure')
        return await real_post(self, url, **kwargs)

    with patch.object(agent.httpx.AsyncClient, 'post', flaky_post):
        assert (await agent.info(target))['id'] == target
    assert read_calls == 2
    report.append({'test': 'read_retry', 'passed': True, 'read_calls': read_calls})
    Path('/app/data/recovery-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


asyncio.run(main())
