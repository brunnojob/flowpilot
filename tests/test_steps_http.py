from __future__ import annotations

import httpx
import respx


@respx.mock
async def test_http_get_json(run_step):
    route = respx.get("https://api.test/items", params={"q": "x"}).mock(
        return_value=httpx.Response(200, json={"items": [1, 2]})
    )
    rec = await run_step(
        "http", {"url": "https://api.test/items", "params": {"q": "x"}, "headers": {"X-A": "1"}}
    )
    assert rec["status"] == "success"
    out = rec["output"]
    assert out["status"] == 200
    assert out["ok"] is True
    assert out["json"] == {"items": [1, 2]}
    assert out["text"] is None
    assert route.calls[0].request.headers["X-A"] == "1"
    assert route.calls[0].request.headers["user-agent"].startswith("flowpilot/")


@respx.mock
async def test_http_post_json_body_and_text_response(run_step):
    route = respx.post("https://api.test/hook").mock(
        return_value=httpx.Response(201, text="created")
    )
    rec = await run_step(
        "http", {"url": "https://api.test/hook", "method": "post", "json": {"a": 1}}
    )
    assert rec["output"]["text"] == "created"
    assert route.calls[0].request.content == b'{"a":1}' or b'"a"' in route.calls[0].request.content


@respx.mock
async def test_http_form_and_raw_data_and_auth(run_step):
    form = respx.post("https://api.test/form").mock(return_value=httpx.Response(200))
    await run_step(
        "http",
        {"url": "https://api.test/form", "method": "POST", "data": {"a": "1"}, "auth": ["u", "p"]},
    )
    req = form.calls[0].request
    assert req.content == b"a=1"
    assert req.headers["authorization"].startswith("Basic ")
    raw = respx.put("https://api.test/raw").mock(return_value=httpx.Response(200))
    await run_step("http", {"url": "https://api.test/raw", "method": "PUT", "data": "hello"})
    assert raw.calls[0].request.content == b"hello"


@respx.mock
async def test_http_5xx_is_retried(run_step, engine):
    route = respx.get("https://api.test/flaky").mock(
        side_effect=[httpx.Response(503, text="down"), httpx.Response(200, json={"ok": 1})]
    )
    rec = await run_step(
        "http", {"url": "https://api.test/flaky"}, retry={"attempts": 2, "delay": 0}
    )
    assert rec["status"] == "success"
    assert route.call_count == 2


@respx.mock
async def test_http_4xx_not_retried(run_step):
    route = respx.get("https://api.test/missing").mock(
        return_value=httpx.Response(404, text="nope")
    )
    rec = await run_step("http", {"url": "https://api.test/missing"}, retry=3)
    assert rec["status"] == "failed"
    assert "HTTP 404" in rec["error"]
    assert route.call_count == 1


@respx.mock
async def test_http_fail_on_error_false_and_expect_status(run_step):
    respx.get("https://api.test/x").mock(return_value=httpx.Response(500, text="err"))
    rec = await run_step("http", {"url": "https://api.test/x", "fail_on_error": False})
    assert rec["status"] == "success"
    assert rec["output"]["ok"] is False
    rec2 = await run_step("http", {"url": "https://api.test/x", "expect_status": [200, 204]})
    assert "unexpected status 500" in rec2["error"]
    rec3 = await run_step("http", {"url": "https://api.test/x", "expect_status": 500})
    assert rec3["status"] == "success"


@respx.mock
async def test_http_network_error_and_bad_json(run_step):
    respx.get("https://api.test/down").mock(side_effect=httpx.ConnectError("refused"))
    rec = await run_step("http", {"url": "https://api.test/down"})
    assert "ConnectError" in rec["error"]
    respx.get("https://api.test/badjson").mock(
        return_value=httpx.Response(
            200, content=b"{oops", headers={"content-type": "application/json"}
        )
    )
    rec2 = await run_step("http", {"url": "https://api.test/badjson"})
    assert rec2["output"]["json"] is None
    assert rec2["output"]["text"] == "{oops"


async def test_http_config_errors(run_step):
    rec = await run_step("http", {"url": "ftp://x"})
    assert "must start with http" in rec["error"]
    rec2 = await run_step("http", {"url": "https://x", "auth": ["only-user"]})
    assert "auth must be" in rec2["error"]
