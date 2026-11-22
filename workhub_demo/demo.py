from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from .api import create_app


def run():
    with TemporaryDirectory() as directory:
        app = create_app(Path(directory) / "demo.sqlite3")
        with TestClient(app, headers={"X-Demo-User": "demo-editor"}) as client:
            draft = client.post("/reports", json={"text": "목록 화면 검토를 마쳤습니다."})
            draft.raise_for_status()
            draft = draft.json()
            before = client.get("/tasks").json()[0]
            assert client.get("/channel").json() == []

            confirm_url = f"/reports/{draft['id']}/confirm"
            receipt = client.post(confirm_url)
            receipt.raise_for_status()
            replayed = client.post(confirm_url)
            replayed.raise_for_status()
            after = client.get("/tasks").json()[0]
            channel = client.get("/channel").json()

            assert before["status"] == "in_progress" and after["status"] == "done"
            assert receipt.json() == replayed.json() and channel == [receipt.json()]
            print(f"초안 · {draft['task_id']} · {draft['source']}")
            print(f"문서 · 버전 {before['version']} {before['status']} → 버전 {after['version']} {after['status']}")
            print(f"채널 · {channel[0]['message']}")
            print(f"같은 초안을 다시 확정한 뒤 게시 수 · {len(channel)}")


if __name__ == "__main__":
    run()
