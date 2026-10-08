from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from flowpilot.config import Settings
from flowpilot.errors import WorkflowValidationError
from flowpilot.loader import discover, load_workflows, parse_workflow
from flowpilot.project import Project
from flowpilot.store import Store, utcnow

ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------- loader


def test_examples_are_valid(registry):
    project = Project.load(ROOT / "examples", registry=registry)
    assert project.load_result.errors == {}
    names = {w.name for w in project.load_result.workflows}
    assert {
        "github-release-watcher",
        "uptime-monitor",
        "crypto-digest",
        "rss-to-telegram",
        "nightly-backup",
        "contact-form",
        "disk-space-alert",
    } <= names
    assert "html_to_text" in registry


def test_scaffold_is_valid(registry):
    scaffold = ROOT / "src" / "flowpilot" / "scaffold" / "workflows"
    result = load_workflows(scaffold, registry)
    assert result.ok
    assert {w.name for w in result.workflows} == {"hello", "webhook-echo", "uptime-monitor"}


def test_load_collects_errors(tmp_path, registry):
    (tmp_path / "ok.yaml").write_text("steps:\n  - {id: a, type: log, with: {message: x}}\n")
    (tmp_path / "syntax.yaml").write_text("steps: [unclosed\n")
    (tmp_path / "list.yml").write_text("- 1\n- 2\n")
    (tmp_path / "unknown.yaml").write_text("name: u\nsteps:\n  - {id: a, type: telepathy}\n")
    (tmp_path / "param.yaml").write_text(
        "name: p\nsteps:\n  - {id: a, type: log, with: {mesage: x}}\n"
    )
    (tmp_path / "missing.yaml").write_text("name: m\nsteps:\n  - {id: a, type: http}\n")
    (tmp_path / "zdup.yaml").write_text(
        "name: ok\nsteps:\n  - {id: a, type: log, with: {message: x}}\n"
    )
    (tmp_path / "_ignored.yaml").write_text("garbage: [")
    (tmp_path / "notes.txt").write_text("ignored")
    result = load_workflows(tmp_path, registry)
    assert [w.name for w in result.workflows] == ["ok"]  # name defaults to the file stem
    errors = {Path(k).name: v for k, v in result.errors.items()}
    assert "YAML syntax error" in errors["syntax.yaml"][0]
    assert "must contain a mapping" in errors["list.yml"][0]
    assert "unknown step type 'telepathy'" in errors["unknown.yaml"][0]
    assert "unknown parameter(s) for step type 'log': mesage" in errors["param.yaml"][0]
    assert "missing required parameter(s) for 'http': url" in errors["missing.yaml"][0]
    assert "duplicate workflow name" in errors["zdup.yaml"][0]
    assert "_ignored.yaml" not in errors
    assert not result.ok


def test_validation_error_formatting(registry):
    with pytest.raises(WorkflowValidationError) as exc:
        parse_workflow(
            {"name": "x", "steps": [{"id": "bad-id", "type": "log"}]}, "x.yaml", registry
        )
    assert "steps.0.id" in exc.value.errors[0]
    assert "Invalid workflow x.yaml" in str(exc.value)


def test_python_workflows(tmp_path, registry):
    (tmp_path / "flows.py").write_text(
        "from flowpilot import define\n"
        "a = define('py-a', steps=[{'id': 's', 'type': 'log', 'with': {'message': 'x'}}])\n"
        "many = [define('py-b', steps=[{'id': 's', 'type': 'log', 'with': {'message': 'y'}}])]\n"
    )
    (tmp_path / "broken.py").write_text("raise RuntimeError('nope')\n")
    (tmp_path / "badstep.py").write_text(
        "from flowpilot import define\nw = define('w', steps=[{'id': 's', 'type': 'nope'}])\n"
    )
    result = load_workflows(tmp_path, registry)
    assert sorted(w.name for w in result.workflows) == ["py-a", "py-b"]
    errors = {Path(k.split(" ")[0]).name: v for k, v in result.errors.items()}
    assert "RuntimeError: nope" in errors["broken.py"][0]
    assert "unknown step type" in errors["badstep.py"][0]
    assert [p.suffix for p in discover(tmp_path)][:3] == [".py", ".py", ".py"]


def test_discover_missing_dir(tmp_path):
    assert discover(tmp_path / "nope") == []


# --------------------------------------------------------------------- config


def test_settings_defaults(tmp_path):
    s = Settings.load(tmp_path)
    assert s.project_dir == tmp_path.resolve()
    assert s.workflows_dir == tmp_path.resolve() / "workflows"
    assert s.database == tmp_path.resolve() / ".flowpilot" / "flowpilot.db"
    assert s.allow_shell is False
    assert s.port == 8080


def test_settings_file_env_and_overrides(tmp_path, monkeypatch):
    (tmp_path / "flowpilot.yaml").write_text(
        "port: 9000\nallow_shell: 'yes'\nplugins: mymod\nworkflows_dir: flows\n"
    )
    (tmp_path / ".env").write_text("FLOWPILOT_API_TOKEN=from-dotenv\nFLOWPILOT_HISTORY_DAYS=7\n")
    monkeypatch.delenv("FLOWPILOT_API_TOKEN", raising=False)
    monkeypatch.delenv("FLOWPILOT_HISTORY_DAYS", raising=False)
    monkeypatch.setenv("FLOWPILOT_PORT", "9100")
    monkeypatch.setenv("FLOWPILOT_PLUGINS", "a.b, c")
    s = Settings.load(tmp_path, host="0.0.0.0")
    assert s.port == 9100
    assert s.allow_shell is True
    assert s.plugins == ["a.b", "c"]
    assert s.api_token == "from-dotenv"
    assert s.history_days == 7
    assert s.host == "0.0.0.0"
    assert s.workflows_dir.name == "flows"
    monkeypatch.delenv("FLOWPILOT_PLUGINS")
    assert Settings.load(tmp_path).plugins == ["mymod"]


def test_settings_rejects_unknown_and_non_mapping(tmp_path):
    (tmp_path / "flowpilot.yaml").write_text("prot: 1\n")
    with pytest.raises(ValueError, match="unknown setting"):
        Settings.load(tmp_path)
    (tmp_path / "flowpilot.yaml").write_text("- 1\n")
    with pytest.raises(ValueError, match="mapping"):
        Settings.load(tmp_path)


def test_settings_resolve_absolute(tmp_path):
    s = Settings(project_dir=tmp_path, database="/tmp/x.db")
    assert str(s.database) == "/tmp/x.db"


# ---------------------------------------------------------------------- store


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def test_store_runs_and_stats(store):
    now = utcnow()
    store.create_run("a", "wf1", "manual", {"x": 1}, now)
    store.finish_run("a", "success", utcnow(), 100, None)
    store.create_run("b", "wf1", "cron", None, now)
    store.finish_run("b", "failed", utcnow(), 300, "boom")
    store.create_run("c", "wf2", "webhook", {}, now)
    stats = store.stats()
    assert stats["total"] == 3
    assert stats["success_rate"] == 0.5
    assert stats["running"] == 1
    assert stats["avg_duration_ms"] == 200
    summaries = store.workflow_summaries()
    assert len(summaries["wf1"]["recent"]) == 2
    assert summaries["wf2"]["last_run"]["status"] == "running"
    assert store.count_runs(workflow="wf1", status="failed") == 1
    assert [
        r["id"] for r in store.list_runs(limit=1, offset=0, workflow="wf1", status="success")
    ] == ["a"]
    assert store.mark_interrupted() == 1
    assert store.get_run("c")["status"] == "failed"
    assert store.get_run("missing") is None


def test_store_truncates_large_outputs():
    s = Store(":memory:", max_output_chars=50)
    s.create_run("r", "wf", "manual", {}, utcnow())
    row = s.start_step("r", "st", "log", utcnow())
    s.finish_step(row, "success", 1, utcnow(), 1, {"big": "x" * 500}, None)
    out = s.get_run("r")["steps"][0]["output"]
    assert out["_truncated"] is True
    assert len(out["preview"]) == 50
    s.close()


def test_store_prune(store):
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    store.create_run("old", "wf", "manual", {}, old)
    store.finish_run("old", "success", old, 1, None)
    store.add_log("old", "info", "x", None, old)
    store.create_run("new", "wf", "manual", {}, utcnow())
    assert store.prune(30) == 1
    assert store.get_run("old") is None
    assert store.get_logs("old") == []


def test_store_state_and_settings(store):
    store.set_state("wf", {"a": [1], "b": {"c": True}})
    assert store.get_state("wf") == {"a": [1], "b": {"c": True}}
    store.delete_state("wf", ["a"])
    assert store.get_state("wf") == {"b": {"c": True}}
    store.delete_state("wf")
    assert store.get_state("wf") == {}
    store.set_enabled("wf", False)
    store.set_enabled("wf", True)
    assert store.get_enabled_overrides() == {"wf": True}


def test_store_file_backed(tmp_path):
    s = Store(tmp_path / "nested" / "db.sqlite")
    s.create_run("r", "wf", "manual", {}, utcnow())
    s.close()
    assert Store(tmp_path / "nested" / "db.sqlite").get_run("r")["workflow"] == "wf"
