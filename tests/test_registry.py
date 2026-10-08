from __future__ import annotations

import logging
from importlib.metadata import EntryPoint

import pytest

from flowpilot.errors import StepConfigError
from flowpilot.logs import JsonFormatter, TextFormatter, configure_logging
from flowpilot.registry import StepRegistry, default_registry


def test_register_and_introspect():
    reg = StepRegistry()

    @reg.step("greet", description="Say hi")
    def greet(ctx, name: str, punct: str = "!", *, times: int = 1):
        return f"hi {name}{punct}" * times

    st = reg.get("greet")
    assert st.description == "Say hi"
    assert st.params["name"] == {"required": True, "default": None, "type": "str"}
    assert st.params["punct"]["default"] == "!"
    assert st.check_params({"name": "x"}) == []
    assert "unknown parameter" in st.check_params({"name": "x", "extra": 1})[0]
    assert "missing required" in st.check_params({})[0]
    assert st.to_dict()["name"] == "greet"
    assert "greet" in reg
    assert [s.name for s in reg.all()] == ["greet"]


def test_docstring_description_and_kwargs():
    reg = StepRegistry()

    def anything(ctx, **params):
        """Accept anything.

        Long description is ignored."""
        return params

    st = reg.register("any", anything, source="tests")
    assert st.description == "Accept anything."
    assert st.accepts_any
    assert st.check_params({"whatever": 1}) == []


def test_duplicate_and_invalid_registration():
    reg = StepRegistry()
    reg.register("a", lambda ctx: 1)
    with pytest.raises(ValueError, match="already registered"):
        reg.register("a", lambda ctx: 2)
    reg.register("a", lambda ctx: 3, replace=True)
    with pytest.raises(TypeError):
        reg.register("b", lambda: 1)


async def test_call_sync_async_and_errors():
    reg = StepRegistry()

    @reg.step()
    def double(ctx, value: int):
        return value * 2

    @reg.step()
    async def triple(ctx, value: int):
        return value * 3

    assert await reg.call("double", None, {"value": 2}) == 4
    assert await reg.call("triple", None, {"value": 2}) == 6
    with pytest.raises(StepConfigError, match="unknown parameter"):
        await reg.call("double", None, {"value": 1, "x": 2})
    with pytest.raises(StepConfigError, match="unknown step type"):
        reg.get("nope")


def test_default_registry_has_builtins_and_clone_is_isolated():
    clone = default_registry.clone()
    clone.register("only_in_clone", lambda ctx: 1)
    assert "only_in_clone" in clone
    assert "only_in_clone" not in default_registry
    assert default_registry.get("http").source == "builtin"


def test_entry_points_loaded(monkeypatch):
    reg = StepRegistry()
    calls = []

    def register(registry):
        calls.append(registry)
        registry.register("ep_step", lambda ctx: "ep")

    monkeypatch.setattr("tests.test_registry.plugin_register", register, raising=False)
    ep = EntryPoint(
        name="demo", value="tests.test_registry:plugin_register", group="flowpilot.steps"
    )
    monkeypatch.setattr("flowpilot.registry.entry_points", lambda group: [ep])
    assert reg.load_entry_points() == ["demo"]
    assert "ep_step" in reg
    assert reg.load_entry_points() == []  # only once


def test_load_modules(tmp_path, monkeypatch):
    (tmp_path / "my_plugin_mod.py").write_text(
        "from flowpilot import step\n@step('from_module')\ndef f(ctx):\n    return 1\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    default_registry.load_modules(["my_plugin_mod"])
    assert default_registry.get("from_module").source == "my_plugin_mod"


def test_formatters():
    record = logging.makeLogRecord(
        {
            "msg": "hello %s",
            "args": ("x",),
            "levelname": "INFO",
            "name": "flowpilot",
            "run_id": "abc",
            "none": None,
        }
    )
    assert '"run_id": "abc"' in JsonFormatter().format(record)
    text = TextFormatter().format(record)
    assert "hello x" in text
    assert "run_id=abc" in text
    assert "none=" not in text
    configure_logging("DEBUG", "json")
    assert isinstance(logging.getLogger("flowpilot").handlers[0].formatter, JsonFormatter)
    configure_logging("INFO", "text")
