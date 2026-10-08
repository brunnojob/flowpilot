"""Discover, parse and validate workflow files (YAML or Python)."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from flowpilot.config import CONFIG_FILENAME
from flowpilot.errors import WorkflowValidationError
from flowpilot.models import WorkflowSpec, iter_steps
from flowpilot.registry import StepRegistry, default_registry

YAML_SUFFIXES = {".yaml", ".yml"}


@dataclass
class LoadResult:
    """Workflows that loaded successfully plus per-file errors."""

    workflows: list[WorkflowSpec] = field(default_factory=list)
    errors: dict[str, list[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def _format_validation(exc: ValidationError) -> list[str]:
    out = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"] if not str(p).startswith("function-after"))
        msg = err["msg"].removeprefix("Value error, ")
        out.append(f"{loc}: {msg}" if loc else msg)
    return out


def check_steps(wf: WorkflowSpec, registry: StepRegistry) -> list[str]:
    """Static checks: every step type exists and receives only known parameters."""
    problems: list[str] = []
    for spec in iter_steps(wf.steps) + iter_steps(wf.on_failure):
        if spec.type not in registry:
            problems.append(f"step '{spec.id}': unknown step type '{spec.type}'")
            continue
        for p in registry.get(spec.type).check_params(spec.with_):
            problems.append(f"step '{spec.id}': {p}")
    return problems


def parse_workflow(data: Any, source: str, registry: StepRegistry | None = None) -> WorkflowSpec:
    """Validate a mapping (e.g. parsed YAML) into a :class:`WorkflowSpec`."""
    registry = registry or default_registry
    if not isinstance(data, dict):
        raise WorkflowValidationError(source, ["workflow file must contain a mapping"])
    try:
        wf = WorkflowSpec.model_validate(data)
    except ValidationError as exc:
        raise WorkflowValidationError(source, _format_validation(exc)) from None
    problems = check_steps(wf, registry)
    if problems:
        raise WorkflowValidationError(source, problems)
    wf.source = source
    return wf


def load_yaml_file(path: Path, registry: StepRegistry | None = None) -> WorkflowSpec:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise WorkflowValidationError(str(path), [f"YAML syntax error: {exc}"]) from None
    if isinstance(data, dict) and "name" not in data:
        data = {"name": path.stem, **data}
    return parse_workflow(data, str(path), registry)


def load_python_file(path: Path, registry: StepRegistry | None = None) -> list[WorkflowSpec]:
    """Import a Python file and collect the ``WorkflowSpec`` objects it defines."""
    registry = registry or default_registry
    mod_name = f"flowpilot_user_{path.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise WorkflowValidationError(str(path), ["cannot import file"])
    module = importlib.util.module_from_spec(spec)
    parent = str(path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    try:
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
    except Exception as exc:
        raise WorkflowValidationError(str(path), [f"{type(exc).__name__}: {exc}"]) from None
    found: list[WorkflowSpec] = []
    for value in vars(module).values():
        if isinstance(value, WorkflowSpec):
            found.append(value)
        elif (
            isinstance(value, (list, tuple))
            and value
            and all(isinstance(v, WorkflowSpec) for v in value)
        ):
            found.extend(value)
    unique = list({id(w): w for w in found}.values())
    for wf in unique:
        problems = check_steps(wf, registry)
        if problems:
            raise WorkflowValidationError(f"{path} ({wf.name})", problems)
        wf.source = str(path)
    return unique


def discover(directory: Path) -> list[Path]:
    """List workflow files in ``directory`` (non-recursive; Python files first)."""
    if not directory.is_dir():
        return []
    files = [
        p
        for p in directory.iterdir()
        if p.is_file()
        and not p.name.startswith(("_", "."))
        and p.name != CONFIG_FILENAME
        and (p.suffix in YAML_SUFFIXES or p.suffix == ".py")
    ]
    # Python files first: they may register custom steps used by YAML workflows.
    return sorted(files, key=lambda p: (p.suffix != ".py", p.name))


def load_workflows(directory: Path, registry: StepRegistry | None = None) -> LoadResult:
    """Load every workflow in ``directory``, collecting errors instead of raising."""
    result = LoadResult()
    names: dict[str, str] = {}
    for path in discover(directory):
        try:
            loaded = (
                load_python_file(path, registry)
                if path.suffix == ".py"
                else [load_yaml_file(path, registry)]
            )
        except WorkflowValidationError as exc:
            result.errors[str(path)] = exc.errors
            continue
        for wf in loaded:
            if wf.name in names:
                result.errors[str(path)] = [
                    f"duplicate workflow name {wf.name!r} (already defined in {names[wf.name]})"
                ]
                continue
            names[wf.name] = str(path)
            result.workflows.append(wf)
    return result
