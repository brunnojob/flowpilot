"""``shell`` — run a command (disabled unless ``allow_shell`` is enabled).

Security: commands run with the privileges of the flowpilot process. Keep
``allow_shell`` off on shared machines, never interpolate untrusted webhook
input into commands, and prefer the list form (``command: [prog, arg]``),
which bypasses the shell entirely.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from typing import Any

from flowpilot.context import StepContext
from flowpilot.errors import StepConfigError, StepError
from flowpilot.registry import step

_POSIX = hasattr(os, "killpg")


def _kill_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill the process and (on POSIX) its whole process group."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        if _POSIX:
            os.killpg(proc.pid, signal.SIGKILL)
        else:  # pragma: no cover - Windows
            proc.kill()


@step("shell")
async def shell(
    ctx: StepContext,
    command: str | list[str],
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
    timeout: float = 300.0,
    max_output: int = 20_000,
) -> dict[str, Any]:
    """Run a shell command and capture its exit code, stdout and stderr."""
    if not ctx.settings.allow_shell:
        raise StepConfigError(
            "shell steps are disabled; set allow_shell: true in flowpilot.yaml "
            "or FLOWPILOT_ALLOW_SHELL=1 to enable them"
        )
    workdir = str(ctx.resolve_path(cwd)) if cwd else str(ctx.project_dir)
    full_env = {**os.environ, **{k: str(v) for k, v in (env or {}).items()}}
    if isinstance(command, list):
        if not command:
            raise StepConfigError("shell: command list is empty")
        proc = await asyncio.create_subprocess_exec(
            *[str(c) for c in command],
            cwd=workdir,
            env=full_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=_POSIX,
        )
        shown = " ".join(str(c) for c in command)
    else:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=workdir,
            env=full_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=_POSIX,
        )
        shown = command
    ctx.log.info(f"$ {shown}")
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        _kill_tree(proc)
        await proc.wait()
        raise StepError(f"command timed out after {timeout:g}s") from None
    except asyncio.CancelledError:
        _kill_tree(proc)
        await proc.wait()
        raise
    stdout = out.decode(errors="replace")[-max_output:]
    stderr = err.decode(errors="replace")[-max_output:]
    result = {"returncode": proc.returncode, "stdout": stdout, "stderr": stderr}
    if check and proc.returncode != 0:
        tail = (stderr or stdout).strip().splitlines()[-1:] or [""]
        raise StepError(f"command exited with {proc.returncode}: {tail[0]}", retryable=True)
    return result
