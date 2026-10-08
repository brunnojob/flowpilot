"""Project settings.

Settings are resolved in this order (later wins):

1. built-in defaults
2. ``flowpilot.yaml`` in the project directory
3. ``.env`` in the project directory (loaded into the process environment,
   never overriding variables that are already set)
4. ``FLOWPILOT_*`` environment variables
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

CONFIG_FILENAME = "flowpilot.yaml"

_TRUE = {"1", "true", "yes", "on"}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _TRUE


@dataclass
class Settings:
    """Runtime configuration for a flowpilot project."""

    project_dir: Path = field(default_factory=Path.cwd)
    workflows_dir: Path = Path("workflows")
    database: Path = Path(".flowpilot/flowpilot.db")
    host: str = "127.0.0.1"
    port: int = 8080
    allow_shell: bool = False
    api_token: str | None = None
    plugins: list[str] = field(default_factory=list)
    log_level: str = "INFO"
    log_format: str = "text"
    max_output_chars: int = 20_000
    history_days: int = 30
    telegram_api_base: str = "https://api.telegram.org"
    http_user_agent: str = "flowpilot"

    def __post_init__(self) -> None:
        self.project_dir = Path(self.project_dir).resolve()
        self.workflows_dir = self.resolve(self.workflows_dir)
        self.database = self.resolve(self.database)

    def resolve(self, path: str | Path) -> Path:
        """Resolve ``path`` relative to the project directory."""
        p = Path(path).expanduser()
        return p if p.is_absolute() else (self.project_dir / p)

    @classmethod
    def load(cls, project_dir: str | Path | None = None, **overrides: Any) -> Settings:
        """Load settings for the project at ``project_dir`` (default: CWD)."""
        root = Path(project_dir or os.environ.get("FLOWPILOT_PROJECT") or Path.cwd()).resolve()
        env_file = root / ".env"
        if env_file.is_file():
            load_dotenv(env_file, override=False)

        data: dict[str, Any] = {}
        cfg = root / CONFIG_FILENAME
        if cfg.is_file():
            loaded = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            if not isinstance(loaded, dict):
                raise ValueError(f"{cfg} must contain a mapping")
            data.update(loaded)

        env_map: dict[str, str] = {
            "workflows_dir": "FLOWPILOT_WORKFLOWS_DIR",
            "database": "FLOWPILOT_DATABASE",
            "host": "FLOWPILOT_HOST",
            "port": "FLOWPILOT_PORT",
            "allow_shell": "FLOWPILOT_ALLOW_SHELL",
            "api_token": "FLOWPILOT_API_TOKEN",
            "log_level": "FLOWPILOT_LOG_LEVEL",
            "log_format": "FLOWPILOT_LOG_FORMAT",
            "history_days": "FLOWPILOT_HISTORY_DAYS",
            "telegram_api_base": "TELEGRAM_API_BASE",
        }
        for key, var in env_map.items():
            if os.environ.get(var):
                data[key] = os.environ[var]
        if os.environ.get("FLOWPILOT_PLUGINS"):
            data["plugins"] = [p.strip() for p in os.environ["FLOWPILOT_PLUGINS"].split(",") if p]

        data.update({k: v for k, v in overrides.items() if v is not None})
        known = set(cls.__dataclass_fields__)
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"unknown setting(s) in {CONFIG_FILENAME}: {', '.join(unknown)}")

        if "port" in data:
            data["port"] = int(data["port"])
        if "history_days" in data:
            data["history_days"] = int(data["history_days"])
        if "allow_shell" in data:
            data["allow_shell"] = _as_bool(data["allow_shell"])
        if isinstance(data.get("plugins"), str):
            data["plugins"] = [data["plugins"]]
        data["project_dir"] = root
        return cls(**data)
