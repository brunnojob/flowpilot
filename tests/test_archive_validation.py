import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from flowpilot.errors import StepConfigError
from flowpilot.steps.archive import archive


def test_validation_precedes_filesystem_changes(tmp_path: Path):
    (tmp_path / "source.txt").write_text("content")
    context = SimpleNamespace(
        resolve_path=lambda value: tmp_path / value,
        log=logging.getLogger("test"),
    )
    for options in (
        {"prefix": "../escape"},
        {"prefix": "*"},
        {"keep": 1.5},
        {"keep": True},
        {"keep": 0},
    ):
        with pytest.raises(StepConfigError):
            archive(context, "source.txt", "backups", **options)
        assert not (tmp_path / "backups").exists()
    result = archive(context, "source.txt", "backups", prefix="source", keep=2)
    assert result["files"] == 1
    assert Path(result["path"]).is_file()
