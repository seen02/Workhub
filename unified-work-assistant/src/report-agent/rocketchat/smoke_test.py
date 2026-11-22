"""Posts synthetic reports only to this installation's private test room."""
import hashlib
import json
import time
import uuid

from setup import API, LOCAL


CASES = [
    {
        "name": "완료와 진행중 분리",
        "input": "업무비서 발표자료 보완은 완료했습니다. 공간정보 Agent 검색 기능은 검토 중입니다.",
        "expected": ["(완료)", "(진행중)", "공간정보"],
        "forbidden": ["100%"],
    },
    {
        "name": "업무별 진행률과 미래 계획",
        "input": "고객관리 화면 수정은 현재 진행률 40%입니다. 내일 사용자 매뉴얼 작성을 시작할 예정입니다.",
        "expected": ["40%", "(예정)", "매뉴얼"],
        "forbidden": ["100%", "(완료)"],
    },
    {
        "name": "언급 없는 상태 및 진행률",
        "input": "이번 보고의 업무명은 로켓챗 도입 자료조사입니다. 아직 진행 상태와 진행률은 보고하지 않겠습니다.",
        "expected": ["(상태 확인 필요)"],
        "forbidden": ["100%", "(완료)"],
    },
]


def main():
    config = json.loads((LOCAL / "bot.json").read_text(encoding="utf-8"))
    credentials = json.loads((LOCAL / "credentials.json").read_text(encoding="utf-8"))
    api = API(**credentials["employee"])
    room_id = config["room_id"]
    room = api.call("GET", "groups.info", params={"roomId": room_id})["group"]
    if room["name"] != "poc-reports" or room["t"] != "p":
        raise RuntimeError("Only the private poc-reports test room is allowed.")
    results = []
    for case in CASES:
        source_id = "test" + uuid.uuid4().hex[:20]
        reply_id = "draft" + hashlib.sha256(f"{room_id}:{source_id}".encode()).hexdigest()[:24]
        started = time.perf_counter()
        api.call("POST", "chat.sendMessage", {"message": {
            "_id": source_id, "rid": room_id, "msg": "!보고 " + case["input"],
        }, "previewUrls": []})
        print(f"Submitted synthetic case: {case['name']}", flush=True)
        result_text = ""
        while time.perf_counter() - started < 300:
            response = api.client.get("/api/v1/chat.getMessage", params={"msgId": reply_id})
            if response.status_code == 200:
                text = response.json().get("message", {}).get("msg", "")
                if text.startswith("[AI 보고 초안") or text.startswith("[초안 생성 실패]"):
                    result_text = text
                    break
            time.sleep(5)
        success = (
            result_text.startswith("[AI 보고 초안")
            and all(value in result_text for value in case["expected"])
            and all(value not in result_text for value in case["forbidden"])
            and "Mock 미사용" in result_text
        )
        results.append({**case, "passed": success, "elapsed_seconds": round(time.perf_counter() - started, 1), "reply": result_text})
        (LOCAL / "smoke-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{case['name']}: {'PASS' if success else 'FAIL'} ({results[-1]['elapsed_seconds']}s)", flush=True)
    print(f"Live end-to-end cases: {sum(item['passed'] for item in results)}/{len(results)}", flush=True)
    if not all(item["passed"] for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
