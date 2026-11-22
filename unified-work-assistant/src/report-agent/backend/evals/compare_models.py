"""Reproducible, DB-free evaluation using the application's current provider.

Run from repository root: .venv/Scripts/python.exe backend/evals/compare_models.py
Outputs are generated artifacts; no report is saved or shared.
"""
import asyncio
import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.llm.local import LocalProvider
from app.logic import calculate_progress_from_text
from app.services import normalize_parsed

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'comparison_50.json'
OUT = ROOT / 'results'
MODELS = ['qwen3:4b', 'gemma3:4b']


class EvaluationClient(httpx.AsyncClient):
    async def post(self, url, **kwargs):
        body = kwargs.get('json')
        if body and body.get('model', '').startswith('gemma'):
            body = dict(body)
            body.pop('think', None)
            kwargs['json'] = body
        return await super().post(url, **kwargs)


def score(parsed, expected):
    checks = {key: parsed.get(key) == expected[key] for key in
              ['progress', 'status', 'start_time', 'end_time', 'duration_hours'] if key in expected}
    for field, spec in [('task', 'task_any'), ('issue', 'issue_any'), ('next_action', 'next_action_any')]:
        words = expected[spec]
        value = parsed.get(field)
        checks[field] = value is None if words is None else any(w.casefold() in (value or '').casefold() for w in words)
    return checks


def summarize(rows):
    result = {}
    for model in MODELS:
        selected = [r for r in rows if r['model'] == model]
        good = [r for r in selected if 'raw' in r]
        item = {'cases': len(selected), 'successes': len(good), 'errors': len(selected)-len(good)}
        for stage in ['raw', 'normalized']:
            item[stage] = {field: {'passed': sum(r.get(stage+'_checks', {}).get(field, False) for r in selected),
                                   'total': sum(field in r['expected'] or field in ['task','issue','next_action'] for r in selected)}
                           for field in ['progress','status','task','issue','next_action','start_time','end_time','duration_hours']}
            item[stage]['all_fields_passed'] = sum(all(r[stage+'_checks'].values()) for r in good)
        seconds = sorted(r['elapsed_seconds'] for r in good)
        item['latency_seconds'] = {'mean': round(statistics.mean(seconds),2), 'p95': seconds[math.ceil(len(seconds)*.95)-1]} if seconds else {}
        item['attempts'] = sum(len(r['calls']) for r in selected)
        result[model] = item
    return result


async def main():
    OUT.mkdir(exist_ok=True)
    cases = json.loads(DATA.read_text(encoding='utf-8'))['cases']
    assert cases and len({c['id'] for c in cases}) == len(cases)
    rows = []
    metadata = {'started_at': datetime.now(timezone.utc).isoformat(), 'dataset_sha256': hashlib.sha256(DATA.read_bytes()).hexdigest(),
                'method': 'Sequential model blocks; same app prompt/schema/temperature/retries; no Mock fallback; first request includes cold load. Gemma receives no think field because it is not a thinking model. Single run, keyword scoring is a proxy, not semantic accuracy.'}
    async with httpx.AsyncClient(base_url='http://127.0.0.1:11434', timeout=180) as control:
        metadata['version'] = (await control.get('/api/version')).json()
        metadata['models'] = (await control.get('/api/tags')).json()
        installed = {m['name'] for m in metadata['models'].get('models', [])}
        if not set(MODELS).issubset(installed):
            raise RuntimeError(f'Models not installed: {set(MODELS) - installed}')
        for model in MODELS:
            calls = []
            async def on_response(response):
                await response.aread()
                payload = response.json()
                calls.append({key: payload.get(key) for key in ['error','total_duration','load_duration','prompt_eval_count','eval_count','eval_duration']})
            async with EvaluationClient(base_url='http://127.0.0.1:11434', timeout=120,
                                         event_hooks={'response':[on_response]}) as client:
                provider = LocalProvider(client)
                provider.model = model
                for case in cases:
                    calls.clear()
                    row = {'model':model, **case, 'deterministic_progress':calculate_progress_from_text(case['raw'])}
                    row['input'] = row.pop('raw')
                    started = time.perf_counter()
                    try:
                        parsed = await provider.parse_report(case['raw'], '평가직원', '평가 프로젝트')
                        row['raw'] = parsed.model_dump()
                        row['normalized'] = normalize_parsed(parsed, case['raw'], '평가직원', '평가 프로젝트').model_dump()
                        for stage in ['raw','normalized']:
                            row[stage+'_checks'] = score(row[stage], case['expected'])
                    except Exception as exc:
                        row['error'] = f'{type(exc).__name__}: {exc}'
                    row['elapsed_seconds'] = round(time.perf_counter()-started,3)
                    row['calls'] = list(calls)
                    rows.append(row)
                    (OUT/'comparison.json').write_text(json.dumps({'metadata':metadata,'rows':rows,'summary':summarize(rows)},ensure_ascii=False,indent=2),encoding='utf-8')
                    print(f"{model} {case['id']} {row['elapsed_seconds']}s progress={row.get('raw',{}).get('progress')} -> {row.get('normalized',{}).get('progress')} expected={case['expected']['progress']} error={row.get('error','')}",flush=True)
            # Release one model before loading the other to reduce memory competition.
            await control.post('/api/generate', json={'model':model,'keep_alive':0})
    print(json.dumps(summarize(rows),ensure_ascii=False,indent=2),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--models', nargs='+', default=MODELS)
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--dataset', type=Path, default=DATA)
    args = parser.parse_args()
    MODELS = args.models
    OUT = args.output.resolve()
    DATA = args.dataset.resolve()
    asyncio.run(main())
