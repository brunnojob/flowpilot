from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from flowpilot import __version__
from flowpilot.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def project(tmp_path: Path, runner: CliRunner) -> Path:
    result = runner.invoke(cli, ["init", str(tmp_path / "proj")])
    assert result.exit_code == 0, result.output
    return tmp_path / "proj"


def test_version(runner):
    result = runner.invoke(cli, ["--version"])
    assert __version__ in result.output


def test_init_scaffolds_files(project, runner):
    assert (project / "flowpilot.yaml").is_file()
    assert (project / ".env.example").is_file()
    assert (project / ".gitignore").is_file()
    assert (project / "workflows" / "hello.yaml").is_file()
    again = runner.invoke(cli, ["init", str(project)])
    assert "exists" in again.output
    forced = runner.invoke(cli, ["init", str(project), "--force"])
    assert "+ workflows/hello.yaml" in forced.output


def test_validate(project, runner):
    result = runner.invoke(cli, ["-p", str(project), "validate"])
    assert result.exit_code == 0, result.output
    assert "all 3 workflow(s) valid" in result.output
    (project / "workflows" / "bad.yaml").write_text("name: bad\nsteps:\n  - {id: a, type: nope}\n")
    result = runner.invoke(cli, ["-p", str(project), "validate"])
    assert result.exit_code == 1
    assert "unknown step type 'nope'" in result.output


def test_validate_empty_project(tmp_path, runner):
    result = runner.invoke(cli, ["-p", str(tmp_path), "validate"])
    assert result.exit_code == 1
    assert "no workflows found" in result.output


def test_run_success_and_json(project, runner):
    result = runner.invoke(
        cli, ["-p", str(project), "run", "hello", "-q", "--payload", '{"who": "Mashhad"}']
    )
    assert result.exit_code == 0, result.output
    assert "success" in result.output
    result = runner.invoke(cli, ["-p", str(project), "run", "hello", "--json"])
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert data["steps"]["greeting"]["status"] == "success"


def test_run_failure_and_errors(project, runner):
    (project / "workflows" / "fail.yaml").write_text(
        "name: fail\nsteps:\n  - {id: bad, type: http, with: {url: 'nope'}}\n"
    )
    result = runner.invoke(cli, ["-p", str(project), "run", "fail", "-q"])
    assert result.exit_code == 1
    assert "must start with http" in result.output
    assert runner.invoke(cli, ["-p", str(project), "run", "missing"]).exit_code == 2
    bad = runner.invoke(cli, ["-p", str(project), "run", "hello", "--payload", "{nope"])
    assert bad.exit_code == 2
    assert "invalid JSON" in bad.output


def test_list_logs_steps(project, runner):
    empty_logs = runner.invoke(cli, ["-p", str(project), "logs"])
    assert "no runs yet" in empty_logs.output
    runner.invoke(cli, ["-p", str(project), "run", "hello", "-q"])
    listed = runner.invoke(cli, ["-p", str(project), "list"])
    assert "hello" in listed.output
    assert "every 5m" in listed.output
    as_json = json.loads(runner.invoke(cli, ["-p", str(project), "list", "--json"]).output)
    hello = next(r for r in as_json if r["name"] == "hello")
    assert hello["last_status"] == "success"
    assert next(r for r in as_json if r["name"] == "uptime-monitor")["enabled"] is False

    logs = runner.invoke(cli, ["-p", str(project), "logs"])
    assert "hello" in logs.output
    run_id = logs.output.split()[0]
    detail = runner.invoke(cli, ["-p", str(project), "logs", run_id[:6]])
    assert detail.exit_code == 0, detail.output
    assert "run started" in detail.output
    assert "greeting" in detail.output
    assert runner.invoke(cli, ["-p", str(project), "logs", "zzz"]).exit_code == 2

    steps = runner.invoke(cli, ["-p", str(project), "steps"])
    assert "telegram" in steps.output
    steps_json = json.loads(runner.invoke(cli, ["-p", str(project), "steps", "--json"]).output)
    assert any(s["name"] == "http" for s in steps_json)


def test_serve_invokes_uvicorn(project, runner, monkeypatch):
    called = {}

    def fake_run(app, host, port, log_level):
        called.update(host=host, port=port, app=app)

    monkeypatch.setattr("uvicorn.run", fake_run)
    result = runner.invoke(
        cli, ["-p", str(project), "serve", "--host", "0.0.0.0", "--port", "9999"]
    )
    assert result.exit_code == 0, result.output
    assert called["port"] == 9999
    assert "no FLOWPILOT_API_TOKEN" in result.output
