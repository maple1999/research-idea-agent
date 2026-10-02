import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


def uid():
    return uuid.uuid4().hex


def now():
    return time.time()


class Conflict(Exception):
    pass


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL,
                    created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, body TEXT NOT NULL,
                    created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL,
                    kind TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS snapshots (
                    project_id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(project_id, revision));
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY, body TEXT NOT NULL, created REAL NOT NULL);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _event(self, db, project_id, kind, payload):
        db.execute("INSERT INTO events(project_id,kind,payload,created) VALUES(?,?,?,?)",
                   (project_id, kind, json.dumps(payload, ensure_ascii=False), now()))

    def event(self, project_id, kind, payload):
        with self.connection() as db:
            self._event(db, project_id, kind, payload)

    def create_project(self, fields):
        project = dict(fields, id=uid(), revision=1, sources=[], directions=[], memories=[], feedback=[],
                       selections={}, created=now())
        body = json.dumps(project, ensure_ascii=False)
        with self.connection() as db:
            db.execute("INSERT INTO projects VALUES(?,?,?,?,?)", (project["id"], 1, body, now(), now()))
            db.execute("INSERT INTO snapshots VALUES(?,?,?)", (project["id"], 1, body))
            self._event(db, project["id"], "project.created", {"summary": "课题已建立"})
        return project

    def project(self, project_id):
        with self.connection() as db:
            row = db.execute("SELECT body FROM projects WHERE id=?", (project_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def projects(self):
        with self.connection() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT body FROM projects ORDER BY updated DESC")]

    def mutate(self, project_id, expected_revision, fn, kind, summary):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM projects WHERE id=?", (project_id,)).fetchone()
            if not row:
                raise KeyError(project_id)
            project = json.loads(row[0])
            if expected_revision is not None and project["revision"] != expected_revision:
                raise Conflict("研究内容已更新，请刷新后再提交。")
            fn(project)
            project["revision"] += 1
            body = json.dumps(project, ensure_ascii=False)
            db.execute("UPDATE projects SET revision=?,body=?,updated=? WHERE id=?",
                       (project["revision"], body, now(), project_id))
            db.execute("INSERT INTO snapshots VALUES(?,?,?)", (project_id, project["revision"], body))
            self._event(db, project_id, kind, {"summary": summary, "revision": project["revision"]})
            return project

    def create_run(self, project_id, budget):
        run = dict(id=uid(), project_id=project_id, status="running", calls=0, tokens=0,
                   usage_estimated=False, elapsed=0.0, step=0, searched=False,
                   next_action="develop", search_query="", budget=budget, reason="", created=now())
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            active = [json.loads(r[0]) for r in db.execute("SELECT body FROM runs WHERE project_id=?",
                                                         (project_id,))]
            if any(r["status"] in ("running", "pausing", "paused") for r in active):
                raise Conflict("已有未结束的探索，请恢复或结束它。")
            db.execute("INSERT INTO runs VALUES(?,?,?,?)", (run["id"], project_id, json.dumps(run), now()))
            self._event(db, project_id, "run.started", {"summary": "开始探索研究问题与方法", "run_id": run["id"]})
        return run

    def run(self, run_id):
        with self.connection() as db:
            row = db.execute("SELECT body FROM runs WHERE id=?", (run_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def runs(self, project_id):
        with self.connection() as db:
            return [json.loads(r[0]) for r in db.execute(
                "SELECT body FROM runs WHERE project_id=? ORDER BY created DESC", (project_id,))]

    def update_run(self, run_id, **changes):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM runs WHERE id=?", (run_id,)).fetchone()
            run = json.loads(row[0])
            run.update(changes)
            db.execute("UPDATE runs SET body=? WHERE id=?", (json.dumps(run), run_id))
            return run

    def recover(self):
        with self.connection() as db:
            for row in db.execute("SELECT id,body FROM runs").fetchall():
                run = json.loads(row[1])
                if run["status"] in ("running", "pausing"):
                    # Reserved calls/tokens remain charged after an unknown outcome.
                    run.update(status="paused", reason="服务重启，已保存进展。可手动恢复；在途调用按预留量核算。")
                    db.execute("UPDATE runs SET body=? WHERE id=?", (json.dumps(run), row[0]))
                    self._event(db, run["project_id"], "run.recovered", {"summary": run["reason"]})

    def events(self, project_id, after=0):
        with self.connection() as db:
            return [dict(seq=r[0], kind=r[1], payload=json.loads(r[2]), created=r[3]) for r in db.execute(
                "SELECT seq,kind,payload,created FROM events WHERE project_id=? AND seq>? ORDER BY seq LIMIT 200",
                (project_id, after))]

    def history(self, project_id):
        with self.connection() as db:
            return [json.loads(r[0]) for r in db.execute(
                "SELECT body FROM snapshots WHERE project_id=? ORDER BY revision DESC LIMIT 30", (project_id,))]

    def cached(self, key, max_age=86400):
        with self.connection() as db:
            row = db.execute("SELECT body,created FROM cache WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row and now() - row[1] < max_age else None

    def cache(self, key, value):
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?)", (key, json.dumps(value), now()))
