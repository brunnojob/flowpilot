"""A loaded flowpilot project: settings + plugins + workflows + engine."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from flowpilot.config import Settings
from flowpilot.engine import Engine
from flowpilot.loader import LoadResult, load_workflows
from flowpilot.registry import StepRegistry, default_registry


@dataclass
class Project:
    """Convenience bundle used by the CLI and the web server."""

    settings: Settings
    engine: Engine
    load_result: LoadResult

    @classmethod
    def load(
        cls,
        project_dir: str | Path | None = None,
        *,
        registry: StepRegistry | None = None,
        settings: Settings | None = None,
    ) -> Project:
        settings = settings or Settings.load(project_dir)
        registry = registry or default_registry
        root = str(settings.project_dir)
        if root not in sys.path:
            sys.path.insert(0, root)
        registry.ensure_builtins()
        registry.load_entry_points()
        registry.load_modules(settings.plugins)
        result = load_workflows(settings.workflows_dir, registry)
        engine = Engine(settings, registry=registry)
        engine.set_workflows(result.workflows)
        return cls(settings, engine, result)

    def reload(self) -> LoadResult:
        """Re-read workflow files from disk."""
        self.load_result = load_workflows(self.settings.workflows_dir, self.engine.registry)
        self.engine.set_workflows(self.load_result.workflows)
        return self.load_result
