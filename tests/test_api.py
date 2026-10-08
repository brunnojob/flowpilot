from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flowpilot.config import Settings
from flowpilot.project import Project
from flowpilot.server import create_app

WORKFLOWS = {
    "hello.yaml": """
name: hello
description: Say hi
tags: [demo]
steps:
  - id: greet
    type: transform
    with:
      template: "hi {{ trigger.who or 'there' }}"
  - id: count
    type: state
    with:
      set: {n: "{{ (state.n or 0) + 1 }}"}
""",
    "hook.yaml": """
name: hook
trigger:
  type: webhook
  path: in/hook
  methods: [POST, GET]
  wait: true
steps:
  - id: echo
    type: transform
    with:
      value: "{{ trigger.body }}"
""",
    "secure.yaml": """
name: secure
trigger:
  type: webhook
  secret: "{{ env.HOOK_SECRET }}"
steps:
  - id: ok
    type: log
    with: {message: "{{ trigger.body }}"}
""",
    "broken.yaml": """
name: broken
steps:
  - id: fail
    type: http
    with: {url: "not-a-url"}
""",
    "cron.yaml": """
name: nightly
trigger: {type: cron, cron: "0 3 * * *", timezone: Asia/Tehran}
steps:
  - {id: a, type: log, with: {message: x}}
""",
}


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch) -> Path:
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    for name, body in WORKFLOWS.items():
        (wf_dir / name).write_text(body)
    monkeypatch.setenv("HOOK_SECRET", "s3cret")
    return tmp_path


def make_client(project_dir: Path, registry, **settings_kw) -> TestClient:
    settings = Settings(
        project_dir=project_dir, database=project_dir / "db.sqlite", history_days=0, **settings_kw
    )
    project = Project.load(settings=settings, registry=registry)
    return TestClient(create_app(project, start_triggers=True))


@pytest.fixture
def client(project_dir, registry):
    with make_client(project_dir, registry) as c:
        yield c


def wait_for(client: TestClient, run_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.02)
    raise AssertionError("run did not finish")


def test_dashboard_and_static(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "flowpilot" in res.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/api/openapi.json").json()["info"]["title"] == "flowpilot"


def test_health_info_stats_steps(client):
    assert client.get("/api/health").json()["workflows"] == 5
    info = client.get("/api/info").json()
    assert info["allow_shell"] is False
    stats = client.get("/api/stats").json()
    assert stats["workflows"] == 5
    assert stats["enabled"] == 5
    assert stats["success_rate"] is None
    names = {s["name"] for s in client.get("/api/steps").json()}
    assert {"http", "telegram", "transform", "branch"} <= names


def test_list_and_get_workflows(client):
    wfs = {w["name"]: w for w in client.get("/api/workflows").json()}
    assert wfs["hello"]["trigger_label"] == "manual"
    assert wfs["hook"]["webhook_path"] == "/hooks/in/hook"
    assert wfs["hook"]["trigger_label"] == "POST/GET /hooks/in/hook"
    assert wfs["secure"]["trigger"]["secret"] == "***"
    assert wfs["nightly"]["trigger_label"] == "cron 0 3 * * * (Asia/Tehran)"
    assert wfs["nightly"]["trigger_active"] is True
    assert wfs["nightly"]["next_run"] is not None
    detail = client.get("/api/workflows/hello").json()
    assert "type: transform" in detail["definition"]
    assert detail["source"] == "workflows/hello.yaml"
    assert client.get("/api/workflows/nope").status_code == 404


def test_run_with_wait_and_history(client):
    res = client.post("/api/workflows/hello/run", json={"payload": {"who": "Sara"}, "wait": True})
    assert res.status_code == 202
    body = res.json()
    assert body["status"] == "success"
    run = client.get(f"/api/runs/{body['run_id']}").json()
    assert run["steps"][0]["output"] == "hi Sara"
    assert run["logs"][0]["message"].startswith("run started")
    logs = client.get(
        f"/api/runs/{body['run_id']}/logs", params={"after": run["logs"][0]["id"]}
    ).json()
    assert len(logs) == len(run["logs"]) - 1
    detail = client.get("/api/workflows/hello").json()
    assert detail["state"] == {"n": 1}
    assert detail["last_run"]["status"] == "success"
    assert client.delete("/api/workflows/hello/state").json()["state"] == {}


def test_background_run_and_filters(client):
    run_id = client.post("/api/workflows/hello/run").json()["run_id"]
    assert wait_for(client, run_id)["status"] == "success"
    failed = client.post("/api/workflows/broken/run", json={"wait": True}).json()
    assert failed["status"] == "failed"
    assert "must start with http" in failed["error"]
    all_runs = client.get("/api/runs").json()
    assert all_runs["total"] == 2
    only_failed = client.get("/api/runs", params={"status": "failed"}).json()
    assert [r["workflow"] for r in only_failed["runs"]] == ["broken"]
    assert client.get("/api/runs", params={"workflow": "hello"}).json()["total"] == 1
    stats = client.get("/api/stats").json()
    assert stats["total"] == 2
    assert stats["success_rate"] == 0.5
    assert client.get("/api/runs/unknown").status_code == 404
    assert client.get("/api/runs/unknown/logs").status_code == 404
    assert client.post("/api/workflows/nope/run").status_code == 404


def test_enable_disable(client):
    assert client.post("/api/workflows/nightly/disable").json() == {
        "name": "nightly",
        "enabled": False,
    }
    wf = client.get("/api/workflows/nightly").json()
    assert wf["enabled"] is False
    assert wf["trigger_active"] is False
    assert client.get("/api/stats").json()["enabled"] == 4
    client.post("/api/workflows/nightly/enable")
    assert client.get("/api/workflows/nightly").json()["trigger_active"] is True
    assert client.post("/api/workflows/nope/enable").status_code == 404


def test_run_stream_replays_logs_for_finished_run(client):
    run_id = client.post("/api/workflows/hello/run", json={"wait": True}).json()["run_id"]
    with client.stream("GET", f"/api/runs/{run_id}/stream") as res:
        assert res.headers["content-type"].startswith("text/event-stream")
        text = "".join(res.iter_text())
    assert "event: log" in text
    assert "run started" in text
    assert text.rstrip().endswith("data: {}")
    assert client.get("/api/runs/nope/stream").status_code == 404


def test_webhook_json_wait(client):
    res = client.post("/hooks/in/hook", json={"a": 1}, headers={"Authorization": "Bearer x"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"
    assert body["output"] == {"a": 1}
    run = client.get(f"/api/runs/{body['run_id']}").json()
    assert run["trigger_type"] == "webhook"
    assert "authorization" not in run["trigger_payload"]["headers"]
    get = client.get("/hooks/in/hook?x=1")
    assert get.status_code == 200
    assert (
        client.post(
            "/hooks/in/hook", content=b"{bad", headers={"content-type": "application/json"}
        ).status_code
        == 400
    )


def test_webhook_errors(client):
    assert client.post("/hooks/missing").status_code == 404
    assert client.put("/hooks/in/hook").status_code == 405
    client.post("/api/workflows/hook/disable")
    assert client.post("/hooks/in/hook", json={}).status_code == 409


def test_webhook_secrets(client):
    assert client.post("/hooks/secure", data={"m": "1"}).status_code == 401
    assert (
        client.post(
            "/hooks/secure", data={"m": "1"}, headers={"X-Flowpilot-Secret": "nope"}
        ).status_code
        == 401
    )
    ok = client.post("/hooks/secure", data={"m": "1"}, headers={"X-Flowpilot-Secret": "s3cret"})
    assert ok.status_code == 202
    run = wait_for(client, ok.json()["run_id"])
    assert run["trigger_payload"]["body"] == {"m": "1"}
    assert client.post("/hooks/secure?secret=s3cret", content=b"raw text").status_code == 202
    raw = json.dumps({"action": "published"}).encode()
    sig = "sha256=" + hmac.new(b"s3cret", raw, hashlib.sha256).hexdigest()
    gh = client.post(
        "/hooks/secure",
        content=raw,
        headers={"X-Hub-Signature-256": sig, "content-type": "application/json"},
    )
    assert gh.status_code == 202
    bad = client.post("/hooks/secure", content=raw, headers={"X-Hub-Signature-256": "sha256=00"})
    assert bad.status_code == 401


def test_webhook_empty_secret_rejected(client, monkeypatch):
    monkeypatch.setenv("HOOK_SECRET", "")
    assert client.post("/hooks/secure", headers={"X-Flowpilot-Secret": ""}).status_code == 401


def test_reload_picks_up_new_files(client, project_dir):
    (project_dir / "workflows" / "new.yaml").write_text(
        "name: fresh\nsteps:\n  - {id: a, type: log, with: {message: x}}\n"
    )
    (project_dir / "workflows" / "bad.yaml").write_text("name: bad\nsteps: []\n")
    res = client.post("/api/reload").json()
    assert "fresh" in res["workflows"]
    assert any("bad.yaml" in k for k in res["errors"])
    assert client.get("/api/workflows/fresh").status_code == 200


def test_api_token_auth(project_dir, registry):
    with make_client(project_dir, registry, api_token="tok") as c:
        assert c.get("/api/health").status_code == 200  # health stays public
        assert c.get("/api/workflows").status_code == 401
        assert c.get("/api/workflows", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert c.get("/api/workflows", headers={"Authorization": "Bearer tok"}).status_code == 200
        assert c.get("/api/workflows", headers={"X-Flowpilot-Token": "tok"}).status_code == 200
        assert c.get("/api/workflows?token=tok").status_code == 200
        assert c.get("/api/info?token=tok").json()["auth"] is True
        assert c.get("/").status_code == 200  # the dashboard shell itself is static
