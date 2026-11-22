"""Fail closed before Ollama; never truncate facts or JSON midway."""
import json
import os
from functools import lru_cache
from fastapi import HTTPException

CONTEXT = max(4096,int(os.getenv('LLM_CONTEXT_TOKENS','4096')))
INPUT_LIMIT = int(os.getenv('LLM_INPUT_TOKENS',str(CONTEXT-1296)))
RESERVE = 496

@lru_cache(maxsize=1)
def tokenizer():
    path = os.getenv('QWEN_TOKENIZER_PATH', '/models/qwen/tokenizer.json')
    if not os.path.isfile(path):
        return None
    from tokenizers import Tokenizer
    return Tokenizer.from_file(path)

def count(text):
    tok = tokenizer()
    # Byte fallback is deliberately conservative, not an exact token measurement.
    return len(tok.encode(text, add_special_tokens=False).ids) if tok else len(text.encode('utf-8'))

def measure(system, user, schema=None, output=800):
    output = min(max(1, int(output)), 1600)
    # Include ChatML framing and JSON grammar even though Ollama handles grammar separately.
    wire = '<|im_start|>system\n' + system + '<|im_end|>\n<|im_start|>user\n' + user + '<|im_end|>\n<|im_start|>assistant\n'
    tokens = count(wire) + (count(json.dumps(schema, ensure_ascii=False)) if schema else 0) + 32
    return {'estimated_input_tokens': tokens, 'output_limit': output, 'reserve_tokens': RESERVE,
            'context_limit': CONTEXT, 'counter': 'qwen-tokenizer' if tokenizer() else 'utf8-byte-upper-bound',
            'fits': tokens <= min(INPUT_LIMIT, CONTEXT-output-RESERVE)}

def enforce(system, user, schema=None, output=800):
    budget = measure(system, user, schema, output)
    if not budget['fits']:
        raise HTTPException(422, '모델 입력 예산 초과: 자료를 더 작은 부분으로 나누어 주세요. 원문은 잘라 보내지 않았습니다.')
    return budget
