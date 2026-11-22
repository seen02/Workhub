import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from uuid import uuid4

from .interpreters import Interpreter, explicit_report
from .models import Actor, Draft, Publication, Status, Task


SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('in_progress', 'done')),
    version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS access (
    actor TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    can_update INTEGER NOT NULL CHECK (can_update IN (0, 1)),
    PRIMARY KEY (actor, task_id)
);
CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY,
    actor TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    status TEXT NOT NULL,
    summary TEXT NOT NULL,
    source TEXT NOT NULL,
    expected_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS publications (
    draft_id TEXT PRIMARY KEY REFERENCES drafts(id),
    task_id TEXT NOT NULL REFERENCES tasks(id),
    status TEXT NOT NULL,
    summary TEXT NOT NULL,
    document_version INTEGER NOT NULL,
    channel TEXT NOT NULL,
    message TEXT NOT NULL
);
"""


class ReportError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class ReportWorkflow:
    def __init__(self, database: Path, interpreter: Interpreter):
        self.database = database
        self.interpreter = interpreter

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.database, timeout=5)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            yield db

    def initialize(self):
        with self.connect() as db:
            db.executescript(SCHEMA)
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM tasks LIMIT 1").fetchone():
                return
            db.executemany(
                "INSERT INTO tasks VALUES (?, ?, 'in_progress', 1)",
                [("DEMO-101", "목록 화면 검토"), ("DEMO-202", "알림 문구 검토")],
            )
            db.executemany(
                "INSERT INTO access VALUES (?, ?, ?)",
                [
                    ("demo-editor", "DEMO-101", 1),
                    ("demo-observer", "DEMO-101", 0),
                    ("demo-observer", "DEMO-202", 1),
                ],
            )

    def tasks(self, actor: Actor) -> list[Task]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT t.* FROM tasks t JOIN access a ON a.task_id = t.id
                   WHERE a.actor = ? ORDER BY t.id""",
                (actor,),
            ).fetchall()
        return [Task(**dict(row)) for row in rows]

    def create_draft(self, actor: Actor, text: str) -> Draft:
        with self.connect() as db:
            editable = db.execute(
                """SELECT t.* FROM tasks t JOIN access a ON a.task_id = t.id
                   WHERE a.actor = ? AND a.can_update = 1 ORDER BY t.id""",
                (actor,),
            ).fetchall()
        candidates = {row["id"]: Task(**dict(row)) for row in editable}
        if not candidates:
            raise ReportError(403, "수정할 수 있는 업무가 없습니다.")

        proposal = explicit_report(text)
        source = "explicit"
        if proposal is None:
            proposal = self.interpreter.interpret(text, list(candidates.values()))
            source = self.interpreter.source
        if proposal is None or proposal.task_id not in candidates:
            raise ReportError(422, "수정 가능한 업무와 상태를 하나로 정할 수 없습니다.")

        # Keep the version seen before interpretation, even if the model took time.
        draft = Draft(
            **proposal.model_dump(),
            id=uuid4().hex,
            source=source,
            expected_version=candidates[proposal.task_id].version,
        )
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._editable_version(db, actor, draft.task_id)
            db.execute(
                """INSERT INTO drafts (id, actor, task_id, status, summary, source, expected_version)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (draft.id, actor, draft.task_id, draft.status, draft.summary, source, draft.expected_version),
            )
        return draft

    def confirm(self, actor: Actor, draft_id: str) -> Publication:
        with self.connect() as db:
            # Serialize confirmations and make the simulated document and channel updates atomic.
            db.execute("BEGIN IMMEDIATE")
            draft = db.execute(
                "SELECT * FROM drafts WHERE id = ? AND actor = ?", (draft_id, actor)
            ).fetchone()
            if draft is None:
                raise ReportError(404, "보고 초안을 찾을 수 없습니다.")
            version = self._editable_version(db, actor, draft["task_id"])
            previous = db.execute(
                "SELECT * FROM publications WHERE draft_id = ?", (draft_id,)
            ).fetchone()
            if previous is not None:
                return Publication(**dict(previous))
            if version != draft["expected_version"]:
                raise ReportError(409, "초안을 만든 뒤 문서가 바뀌었습니다. 새 초안을 작성하세요.")

            status_word = "완료" if draft["status"] == Status.DONE else "진행 중"
            publication = Publication(
                draft_id=draft_id,
                task_id=draft["task_id"],
                status=draft["status"],
                summary=draft["summary"],
                document_version=version + 1,
                channel="demo-reports",
                message=f"[{draft['task_id']}] {status_word} · {draft['summary']}",
            )
            db.execute(
                "UPDATE tasks SET status = ?, version = ? WHERE id = ?",
                (publication.status, publication.document_version, publication.task_id),
            )
            db.execute(
                """INSERT INTO publications
                   (draft_id, task_id, status, summary, document_version, channel, message)
                   VALUES (:draft_id, :task_id, :status, :summary, :document_version, :channel, :message)""",
                publication.model_dump(),
            )
            return publication

    def publications(self, actor: Actor) -> list[Publication]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT p.* FROM publications p JOIN drafts d ON d.id = p.draft_id
                   JOIN access a ON a.actor = d.actor AND a.task_id = p.task_id
                   WHERE d.actor = ? ORDER BY p.rowid""",
                (actor,),
            ).fetchall()
        return [Publication(**dict(row)) for row in rows]

    @staticmethod
    def _editable_version(db: sqlite3.Connection, actor: Actor, task_id: str) -> int:
        row = db.execute(
            """SELECT t.version FROM tasks t JOIN access a ON a.task_id = t.id
               WHERE t.id = ? AND a.actor = ? AND a.can_update = 1""",
            (task_id, actor),
        ).fetchone()
        if row is None:
            raise ReportError(403, "이 업무를 수정할 권한이 없습니다.")
        return row["version"]
