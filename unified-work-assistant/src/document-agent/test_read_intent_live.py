"""Inspect the short request interpreter using the same local model prompt."""
import ast,asyncio,json
from pathlib import Path
import app as core

async def main():
    tree=ast.parse(Path('agent_tools.py').read_text(encoding='utf-8'))
    fn=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=='read_request')
    schema=next(ast.literal_eval(n.value) for n in fn.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='schema' for t in n.targets))
    call=next(n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='llm')
    prompt='‘로컬 AI 테스트’ 컬렉션에서 간단검토0916 관련 문서를 찾아 현재 상태와 다음 할 일을 짧게 정리해줘. 읽은 문서 수와 출처도 알려줘.'
    result,metrics=await core.llm(ast.literal_eval(call.args[0]),json.dumps({'request':prompt,'previous_topic':''},ensure_ascii=False),schema,260)
    print(json.dumps({'intent':result,'metrics':metrics},ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
