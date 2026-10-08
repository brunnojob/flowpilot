from __future__ import annotations

import sqlite3
import sys
import tarfile
import textwrap
import zipfile

import pytest

# ------------------------------------------------------------------ transform


async def test_transform_variants(run_step):
    assert (await run_step("transform", {"value": {"a": "{{ 1 + 1 }}"}}))["output"] == {"a": 2}
    assert (await run_step("transform", {"template": "x{{ 2 }}"}))["output"] == "x2"
    rec = await run_step("transform", {"data": {"a": [{"b": 1}, {"b": 2}]}, "jmespath": "a[].b"})
    assert rec["output"] == [1, 2]
    rec = await run_step("transform", {"value": {"n": 5}, "jmespath": "n"})
    assert rec["output"] == 5
    rec = await run_step("transform", {"template": '{"k": 1}', "parse_json": True})
    assert rec["output"] == {"k": 1}
    assert (await run_step("transform", {"data": [1]}))["output"] == [1]


async def test_transform_errors(run_step):
    assert (
        "invalid JMESPath"
        in (await run_step("transform", {"data": {}, "jmespath": "[[["}))["error"]
    )
    assert (
        "requires a string"
        in (await run_step("transform", {"value": 1, "parse_json": True}))["error"]
    )
    assert (
        "invalid JSON"
        in (await run_step("transform", {"template": "{", "parse_json": True}))["error"]
    )


# ---------------------------------------------------------------- control


async def test_log_and_delay(run_step, engine):
    rec = await run_step("log", {"message": "hello", "level": "warning"})
    logs = engine.store.get_logs(rec["run"].run_id)
    assert any(line["level"] == "warning" and line["message"] == "hello" for line in logs)
    assert "unknown level" in (await run_step("log", {"message": "x", "level": "loud"}))["error"]
    assert (await run_step("delay", {"seconds": 0}))["output"] == {"slept": 0.0}
    assert ">= 0" in (await run_step("delay", {"seconds": -1}))["error"]


# ------------------------------------------------------------------- python


@pytest.fixture
def user_module(settings, monkeypatch):
    (settings.project_dir / "mytasks.py").write_text(
        textwrap.dedent(
            """
            def add(a, b):
                return a + b

            async def greet(name, ctx):
                ctx.log.info("greeting")
                return f"hi {name} from {ctx.workflow}"

            class Tools:
                @staticmethod
                def upper(s):
                    return s.upper()

            NOT_CALLABLE = 1
            """
        )
    )
    yield "mytasks"
    sys.modules.pop("mytasks", None)


async def test_python_step(run_step, user_module):
    assert (await run_step("python", {"function": "mytasks:add", "args": {"a": 1, "b": 2}}))[
        "output"
    ] == 3
    rec = await run_step("python", {"function": "mytasks:greet", "args": {"name": "Ali"}})
    assert rec["output"].startswith("hi Ali from step-test-")
    assert (await run_step("python", {"function": "mytasks.Tools.upper", "args": {"s": "a"}}))[
        "error"
    ]
    assert (await run_step("python", {"function": "mytasks:Tools.upper", "args": {"s": "a"}}))[
        "output"
    ] == "A"
    assert (await run_step("python", {"function": "json.dumps", "args": {"obj": [1]}}))[
        "output"
    ] == "[1]"


async def test_python_step_errors(run_step, user_module):
    assert "cannot import" in (await run_step("python", {"function": "nope_mod:x"}))["error"]
    assert (
        "has no attribute" in (await run_step("python", {"function": "mytasks:missing"}))["error"]
    )
    assert (
        "not callable" in (await run_step("python", {"function": "mytasks:NOT_CALLABLE"}))["error"]
    )
    assert "must look like" in (await run_step("python", {"function": "nodots"}))["error"]


# -------------------------------------------------------------------- shell


async def test_shell_disabled_by_default(run_step):
    rec = await run_step("shell", {"command": "echo hi"})
    assert "shell steps are disabled" in rec["error"]


async def test_shell_enabled(run_step, engine):
    engine.settings.allow_shell = True
    rec = await run_step("shell", {"command": "echo $GREETING", "env": {"GREETING": "salam"}})
    assert rec["output"]["stdout"].strip() == "salam"
    rec = await run_step("shell", {"command": [sys.executable, "-c", "print(40 + 2)"]})
    assert rec["output"]["stdout"].strip() == "42"
    rec = await run_step("shell", {"command": "echo oops >&2; exit 3"})
    assert "exited with 3: oops" in rec["error"]
    rec = await run_step("shell", {"command": "exit 3", "check": False})
    assert rec["output"]["returncode"] == 3
    rec = await run_step("shell", {"command": "sleep 5", "timeout": 0.1})
    assert "timed out after 0.1s" in rec["error"]
    assert "empty" in (await run_step("shell", {"command": []}))["error"]


# -------------------------------------------------------------------- files


async def test_file_write_read(run_step, settings):
    rec = await run_step("file.write", {"path": "out/a.txt", "content": "one"})
    assert rec["output"]["bytes"] == 3
    await run_step(
        "file.write", {"path": "out/a.txt", "content": {"n": 1}, "mode": "append", "newline": True}
    )
    assert (settings.project_dir / "out/a.txt").read_text() == 'one{"n": 1}\n'
    assert (await run_step("file.read", {"path": "out/a.txt", "parse": "lines"}))["output"] == [
        'one{"n": 1}'
    ]
    await run_step("file.write", {"path": "d.json", "content": [1, 2]})
    assert (await run_step("file.read", {"path": "d.json", "parse": "json"}))["output"] == [1, 2]
    assert (await run_step("file.read", {"path": "d.json"}))["output"] == "[1, 2]"


async def test_file_errors(run_step):
    assert (
        "mode must be"
        in (await run_step("file.write", {"path": "x", "content": "", "mode": "x"}))["error"]
    )
    assert "does not exist" in (await run_step("file.read", {"path": "missing.txt"}))["error"]
    await run_step("file.write", {"path": "y", "content": "1"})
    assert "parse must be" in (await run_step("file.read", {"path": "y", "parse": "xml"}))["error"]


# ------------------------------------------------------------------- sqlite


async def test_sqlite_step(run_step, settings):
    db = "data/app.db"
    await run_step(
        "sqlite",
        {
            "database": db,
            "query": "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT);",
            "script": True,
        },
    )
    rec = await run_step(
        "sqlite", {"database": db, "query": "INSERT INTO t (name) VALUES (?)", "params": ["a"]}
    )
    assert rec["output"]["lastrowid"] == 1
    rec = await run_step(
        "sqlite",
        {"database": db, "query": "INSERT INTO t (name) VALUES (?)", "many": [["b"], ["c"]]},
    )
    assert rec["output"]["rowcount"] == 2
    rec = await run_step(
        "sqlite",
        {
            "database": db,
            "query": "SELECT name FROM t WHERE id > :min ORDER BY id",
            "params": {"min": 1},
        },
    )
    assert rec["output"]["rows"] == [{"name": "b"}, {"name": "c"}]
    assert (
        "sqlite:"
        in (await run_step("sqlite", {"database": db, "query": "SELECT * FROM nope"}))["error"]
    )
    with sqlite3.connect(settings.project_dir / db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 3


# -------------------------------------------------------------------- state


async def test_state_step(run_step, engine, add_wf):
    add_wf(
        {
            "name": "st",
            "steps": [
                {
                    "id": "a",
                    "type": "state",
                    "with": {"set": {"x": 1, "y": 2}, "merge": {"m": {"a": 1}}},
                },
                {
                    "id": "b",
                    "type": "state",
                    "with": {"merge": {"m": {"b": {"c": 2}}}, "delete": ["y"]},
                },
                {"id": "c", "type": "transform", "with": {"value": "{{ state }}"}},
            ],
        }
    )
    result = await engine.run("st")
    assert result.steps["c"]["output"] == {"x": 1, "m": {"a": 1, "b": {"c": 2}}}
    assert engine.store.get_state("st") == {"x": 1, "m": {"a": 1, "b": {"c": 2}}}
    assert "at least one" in (await run_step("state", {}))["error"]


# ------------------------------------------------------------------ archive


async def test_archive_tar_with_retention(run_step, settings):
    src = settings.project_dir / "data"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_text("a")
    (src / "sub" / "b.txt").write_text("b")
    (src / "skip.tmp").write_text("x")
    paths = []
    for _ in range(3):
        rec = await run_step(
            "archive", {"source": "data", "destination": "backups", "keep": 2, "exclude": ["*.tmp"]}
        )
        assert rec["status"] == "success", rec["error"]
        paths.append(rec["output"]["path"])
    out = rec["output"]
    assert out["files"] == 2
    assert len(out["removed"]) == 1
    remaining = sorted(p.name for p in (settings.project_dir / "backups").iterdir())
    assert len(remaining) == 2
    with tarfile.open(out["path"]) as tf:
        assert sorted(tf.getnames()) == ["a.txt", "sub/b.txt"]


async def test_archive_zip_single_file_and_errors(run_step, settings):
    (settings.project_dir / "one.txt").write_text("1")
    rec = await run_step(
        "archive", {"source": "one.txt", "destination": "bk", "format": "zip", "prefix": "solo"}
    )
    assert rec["output"]["name"].startswith("solo-")
    with zipfile.ZipFile(rec["output"]["path"]) as zf:
        assert zf.namelist() == ["one.txt"]
    assert (
        "format must be"
        in (await run_step("archive", {"source": "one.txt", "destination": "bk", "format": "rar"}))[
            "error"
        ]
    )
    assert (
        "does not exist"
        in (await run_step("archive", {"source": "nope", "destination": "bk"}))["error"]
    )


async def test_archive_excludes_destination_inside_source(run_step, settings):
    src = settings.project_dir / "proj"
    src.mkdir()
    (src / "f.txt").write_text("f")
    await run_step("archive", {"source": "proj", "destination": "proj/backups"})
    rec = await run_step("archive", {"source": "proj", "destination": "proj/backups"})
    assert rec["output"]["files"] == 1


# -------------------------------------------------------------------- email


class FakeSMTP:
    instances: list[FakeSMTP] = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port
        self.started_tls = False
        self.logged_in = None
        self.sent = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.started_tls = True

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg):
        self.sent.append(msg)


@pytest.fixture
def fake_smtp(monkeypatch):
    import smtplib

    FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_USER", "me@test")
    monkeypatch.setenv("SMTP_PASSWORD", "pw")
    return FakeSMTP


async def test_email_starttls(run_step, fake_smtp):
    rec = await run_step(
        "email", {"to": ["a@x", "b@x"], "subject": "Hi", "body": "text", "html": "<b>x</b>"}
    )
    assert rec["status"] == "success", rec["error"]
    smtp = fake_smtp.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.test", 587)
    assert smtp.started_tls
    assert smtp.logged_in == ("me@test", "pw")
    msg = smtp.sent[0]
    assert msg["To"] == "a@x, b@x"
    assert msg["From"] == "me@test"
    assert msg.is_multipart()


async def test_email_ssl_and_errors(run_step, fake_smtp, monkeypatch):
    rec = await run_step("email", {"to": "a@x", "subject": "s", "security": "ssl"})
    assert fake_smtp.instances[-1].port == 465
    assert not fake_smtp.instances[-1].started_tls
    assert rec["status"] == "success"
    assert (
        "security must be"
        in (await run_step("email", {"to": "a", "subject": "s", "security": "tls13"}))["error"]
    )
    monkeypatch.delenv("SMTP_HOST")
    assert "no SMTP host" in (await run_step("email", {"to": "a", "subject": "s"}))["error"]
    monkeypatch.setenv("SMTP_HOST", "h")
    monkeypatch.delenv("SMTP_USER")
    assert "no sender" in (await run_step("email", {"to": "a", "subject": "s"}))["error"]


async def test_email_smtp_failure(run_step, fake_smtp, monkeypatch):
    import smtplib

    def boom(self, msg):
        raise smtplib.SMTPRecipientsRefused({})

    monkeypatch.setattr(FakeSMTP, "send_message", boom)
    rec = await run_step("email", {"to": "a@x", "subject": "s"})
    assert "SMTPRecipientsRefused" in rec["error"]
