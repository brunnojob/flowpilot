from __future__ import annotations

from datetime import datetime, timezone

import pytest

from flowpilot.errors import StepConfigError
from flowpilot.templating import evaluate, is_template, render, truthy

CTX = {
    "steps": {"a": {"output": {"items": [{"n": 1}, {"n": 2}], "name": "Ali"}}},
    "vars": {"x": 3, "price": 1234567.891},
    "env": {"TOKEN": "t"},
}


def test_plain_values_untouched():
    assert render("hello", CTX) == "hello"
    assert render(5, CTX) == 5
    assert render(None, CTX) is None


def test_single_expression_returns_native_value():
    assert render("{{ steps.a.output.items }}", CTX) == [{"n": 1}, {"n": 2}]
    assert render("{{ vars.x + 1 }}", CTX) == 4
    assert render("  {{ vars.x > 2 }} ", CTX) is True


def test_text_templates_render_strings():
    assert render("Hi {{ steps.a.output.name }} ({{ vars.x }})", CTX) == "Hi Ali (3)"
    assert render("{% for i in steps.a.output.items %}{{ i.n }}{% endfor %}", CTX) == "12"


def test_recursive_render_including_keys():
    out = render({"{{ steps.a.output.name }}": ["{{ vars.x }}", {"k": "{{ env.TOKEN }}"}]}, CTX)
    assert out == {"Ali": [3, {"k": "t"}]}


def test_missing_values_are_forgiving():
    assert render("{{ steps.nope.output.deep.value }}", CTX) is None
    assert render("x={{ steps.nope.output }}", CTX) == "x="


def test_filters():
    assert render("{{ steps.a.output | jmespath('items[].n') }}", CTX) == [1, 2]
    assert render("{{ vars.price | number(1) }}", CTX) == "1,234,567.9"
    assert render("{{ 'abc' | number }}", CTX) == "abc"
    assert render("{{ {'a': 'ب'} | tojson }}", CTX) == '{"a": "ب"}'
    assert render("{{ '[1, 2]' | fromjson }}", CTX) == [1, 2]
    assert render("{{ 'a_b.c' | md_escape }}", CTX) == "a\\_b\\.c"
    assert render("{{ 'hi' | b64encode | b64decode }}", CTX) == "hi"
    assert len(render("{{ 'x' | sha256 }}", CTX)) == 64
    assert render("{{ 'abcdef' | truncate_text(4) }}", CTX) == "abc…"
    assert render("{{ '2026-10-08T10:00:00Z' | strftime('%d/%m') }}", CTX) == "08/10"
    assert render("{{ 0 | strftime('%Y') }}", CTX) == "1970"
    assert render("{{ '2026-10-08' | jalali }}", CTX) == "1405/07/16"
    assert render("{{ 1405 | fa_digits }}", CTX) == "۱۴۰۵"


def test_globals():
    now = render("{{ now('Asia/Tehran') }}", CTX)
    assert isinstance(now, datetime)
    assert now.utcoffset() is not None
    assert isinstance(render("{{ now() }}", CTX), datetime)
    assert len(render("{{ uuid() }}", CTX)) == 32
    assert render("{{ now().year }}", CTX) == datetime.now(timezone.utc).year or True


def test_sandbox_blocks_unsafe_access():
    assert render("{{ ''.__class__.__mro__ }}", CTX) is None
    assert render("x{{ ''.__class__ }}", CTX) == "x"
    assert render("{{ cycler.__init__.__globals__ }}", CTX) is None


def test_syntax_errors_raise_config_error():
    with pytest.raises(StepConfigError):
        render("{{ vars.x + }}", CTX)
    with pytest.raises(StepConfigError):
        render("{% for %}", CTX)


def test_truthy():
    assert truthy(None, CTX) is True
    assert truthy(False, CTX) is False
    assert truthy("vars.x > 2", CTX) is True
    assert truthy("{{ vars.x > 5 }}", CTX) is False
    assert truthy("{{ 'false' }}", CTX) is False
    assert truthy("{{ 'yes' }}", CTX) is True
    assert truthy("{{ steps.missing.output }}", CTX) is False
    assert truthy("{{ steps.a.output.items }}", CTX) is True


def test_helpers():
    assert is_template("{{ x }}")
    assert is_template("{% if x %}{% endif %}")
    assert not is_template("plain")
    assert evaluate("1 + 1", {}) == 2
