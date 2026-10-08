"""``archive`` — create timestamped .tar.gz/.zip backups with retention."""

from __future__ import annotations

import fnmatch
import tarfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from flowpilot.context import StepContext
from flowpilot.errors import StepConfigError
from flowpilot.registry import step


def _iter_files(root: Path, exclude: list[str]) -> list[Path]:
    files = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(path.name, pat) for pat in exclude):
            continue
        if path.is_file():
            files.append(path)
    return files


@step("archive")
def archive(
    ctx: StepContext,
    source: str,
    destination: str,
    format: str = "tar.gz",
    prefix: str | None = None,
    exclude: list[str] | None = None,
    keep: int | None = None,
) -> dict[str, Any]:
    """Archive ``source`` into ``destination/<prefix>-YYYYmmdd-HHMMSS.<format>``.

    ``keep`` deletes the oldest archives with the same prefix beyond that count.
    """
    if format not in {"tar.gz", "zip"}:
        raise StepConfigError("archive: format must be 'tar.gz' or 'zip'")
    src = ctx.resolve_path(source)
    if not src.exists():
        raise StepConfigError(f"archive: source {src} does not exist")
    dest_dir = ctx.resolve_path(destination)
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = prefix or src.name or "backup"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = dest_dir / f"{name}-{stamp}.{format}"
    counter = 1
    while target.exists():
        target = dest_dir / f"{name}-{stamp}-{counter}.{format}"
        counter += 1

    files = [src] if src.is_file() else _iter_files(src, exclude or [])
    files = [f for f in files if dest_dir.resolve() not in f.resolve().parents]
    base = src.parent if src.is_file() else src
    if format == "zip":
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                zf.write(f, f.relative_to(base).as_posix())
    else:
        with tarfile.open(target, "w:gz") as tf:
            for f in files:
                tf.add(f, arcname=f.relative_to(base).as_posix())

    removed: list[str] = []
    if keep is not None and keep > 0:
        existing = sorted(
            (p for p in dest_dir.glob(f"{name}-*.{format}") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in existing[keep:]:
            old.unlink()
            removed.append(old.name)
    size = target.stat().st_size
    ctx.log.info(f"archived {len(files)} file(s) into {target.name} ({size} bytes)")
    return {
        "path": str(target),
        "name": target.name,
        "files": len(files),
        "size": size,
        "removed": removed,
    }
