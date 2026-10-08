"""The ``flowpilot`` command-line interface."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import time
from datetime import datetime
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

import click

from flowpilot import __version__
from flowpilot.config import Settings
from flowpilot.logs import configure_logging

STATUS_COLORS = {
    "success": "green",
    "failed": "red",
    "running": "cyan",
    "skipped": "bright_black",
    "cancelled": "yellow",
}
SCAFFOLD_RENAMES = {"env.example": ".env.example", "gitignore": ".gitignore"}


def _local(ts: str | None) -> str:
    """Format an ISO UTC timestamp in the local timezone."""
    if not ts:
        return ""
    return datetime.fromisoformat(ts).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _status(status: str) -> str:
    return click.style(status, fg=STATUS_COLORS.get(status, "white"), bold=True)


def _load_project(ctx: click.Context, *, quiet: bool = False) -> Any:
    from flowpilot.project import Project

    project = Project.load(ctx.obj["project_dir"])
    if project.load_result.errors and not quiet:
        for path, errs in project.load_result.errors.items():
            click.secho(f"✗ {path}", fg="red", err=True)
            for e in errs:
                click.echo(f"    {e}", err=True)
    return project


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version", prog_name="flowpilot")
@click.option(
    "-p",
    "--project",
    "project_dir",
    type=click.Path(file_okay=False, path_type=Path),
    envvar="FLOWPILOT_PROJECT",
    default=None,
    help="Project directory (default: current directory).",
)
@click.pass_context
def cli(ctx: click.Context, project_dir: Path | None) -> None:
    """flowpilot — lightweight, self-hosted workflow automation."""
    ctx.ensure_object(dict)
    ctx.obj["project_dir"] = project_dir


@cli.command()
@click.argument("directory", type=click.Path(file_okay=False, path_type=Path), default=".")
@click.option("--force", is_flag=True, help="Overwrite existing files.")
def init(directory: Path, force: bool) -> None:
    """Scaffold a new project with example workflows."""
    directory.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    skipped: list[str] = []
    with as_file(files("flowpilot") / "scaffold") as src_root:
        for src in sorted(Path(src_root).rglob("*")):
            if not src.is_file() or "__pycache__" in src.parts:
                continue
            rel = src.relative_to(src_root)
            rel = rel.with_name(SCAFFOLD_RENAMES.get(rel.name, rel.name))
            dest = directory / rel
            if dest.exists() and not force:
                skipped.append(str(rel))
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            created.append(str(rel))
    for c in created:
        click.echo(f"  {click.style('+', fg='green')} {c}")
    for s in skipped:
        click.echo(f"  {click.style('=', fg='yellow')} {s} (exists, use --force to overwrite)")
    click.echo()
    click.secho("✓ Project ready.", fg="green", bold=True)
    where = "" if directory.resolve() == Path.cwd().resolve() else f"cd {directory} && "
    click.echo(f"  Next: {where}flowpilot validate && flowpilot run hello && flowpilot serve")


@cli.command()
@click.pass_context
def validate(ctx: click.Context) -> None:
    """Validate all workflow files."""
    project = _load_project(ctx)
    for wf in project.load_result.workflows:
        click.echo(
            f"{click.style('✓', fg='green')} {wf.name}  ({len(wf.steps)} steps, {wf.trigger.type})"
        )
    n_err = len(project.load_result.errors)
    if n_err:
        click.secho(f"\n{n_err} file(s) with errors", fg="red", bold=True)
        sys.exit(1)
    if not project.load_result.workflows:
        click.secho(f"no workflows found in {project.settings.workflows_dir}", fg="yellow")
        sys.exit(1)
    click.secho(f"\nall {len(project.load_result.workflows)} workflow(s) valid", fg="green")


@cli.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
@click.pass_context
def list_cmd(ctx: click.Context, as_json: bool) -> None:
    """List workflows with their trigger and last run."""
    from flowpilot.server.app import _describe_trigger

    project = _load_project(ctx)
    engine = project.engine
    summaries = engine.store.workflow_summaries(per_workflow=1)
    rows = []
    for wf in engine.workflows.values():
        last = summaries.get(wf.name, {}).get("last_run")
        rows.append(
            {
                "name": wf.name,
                "enabled": engine.is_enabled(wf.name),
                "trigger": _describe_trigger(wf),
                "steps": len(wf.steps),
                "last_status": last["status"] if last else None,
                "last_started": last["started_at"] if last else None,
            }
        )
    if as_json:
        click.echo(json.dumps(rows, indent=2))
        return
    if not rows:
        click.echo("no workflows")
        return
    width = max(len(r["name"]) for r in rows) + 2
    for r in rows:
        dot = click.style("●", fg="green" if r["enabled"] else "bright_black")
        last = _status(r["last_status"]) if r["last_status"] else click.style("never run", dim=True)
        click.echo(f"{dot} {r['name']:<{width}} {r['trigger']:<34} {last}")


@cli.command()
@click.argument("name")
@click.option("--payload", default=None, help="JSON payload available as `trigger`.")
@click.option("--json", "as_json", is_flag=True, help="Print the result as JSON.")
@click.option("-q", "--quiet", is_flag=True, help="Do not stream logs.")
@click.pass_context
def run(ctx: click.Context, name: str, payload: str | None, as_json: bool, quiet: bool) -> None:
    """Run a workflow once and print the result."""
    project = _load_project(ctx)
    settings = project.settings
    configure_logging("WARNING" if quiet or as_json else "INFO", settings.log_format)
    try:
        data = json.loads(payload) if payload else {}
    except ValueError as exc:
        raise click.BadParameter(f"invalid JSON: {exc}", param_hint="--payload") from None
    if name not in project.engine.workflows:
        click.secho(f"workflow {name!r} not found", fg="red", err=True)
        sys.exit(2)

    async def main() -> Any:
        await project.engine.start()
        try:
            return await project.engine.run(name, "manual", data)
        finally:
            await project.engine.close()

    result = asyncio.run(main())
    if as_json:
        click.echo(json.dumps(result.to_dict(), indent=2, default=str))
    else:
        click.echo()
        for sid, rec in result.steps.items():
            line = f"  {_status(rec['status']):<20} {sid}"
            if rec.get("error"):
                line += click.style(f"  — {rec['error']}", fg="red")
            click.echo(line)
        click.echo(
            f"\n{_status(result.status)} in {result.duration_ms} ms  "
            + click.style(f"run {result.run_id[:12]}", dim=True)
        )
        if result.error:
            click.secho(result.error, fg="red")
    sys.exit(0 if result.ok else 1)


@cli.command()
@click.option("--host", default=None, help="Bind address (default from settings: 127.0.0.1).")
@click.option("--port", type=int, default=None, help="Port (default 8080).")
@click.option("--no-triggers", is_flag=True, help="Serve API/dashboard without starting triggers.")
@click.pass_context
def serve(ctx: click.Context, host: str | None, port: int | None, no_triggers: bool) -> None:
    """Start the web server, dashboard and all triggers."""
    import uvicorn

    from flowpilot.server import create_app

    project = _load_project(ctx)
    settings = project.settings
    configure_logging(settings.log_level, settings.log_format)
    app = create_app(project, start_triggers=not no_triggers)
    bind_host = host or settings.host
    bind_port = port or settings.port
    click.secho(f"flowpilot {__version__}", fg="cyan", bold=True)
    click.echo(f"  workflows : {len(project.engine.workflows)} from {settings.workflows_dir}")
    click.echo(f"  dashboard : http://{bind_host}:{bind_port}/")
    click.echo(f"  api docs  : http://{bind_host}:{bind_port}/api/docs")
    if not settings.api_token and bind_host not in {"127.0.0.1", "localhost"}:
        click.secho(
            "  warning   : no FLOWPILOT_API_TOKEN set while listening publicly", fg="yellow"
        )
    uvicorn.run(app, host=bind_host, port=bind_port, log_level="warning")


@cli.command()
@click.argument("run_id", required=False)
@click.option("-w", "--workflow", default=None, help="Filter runs by workflow.")
@click.option("-n", "--limit", default=20, show_default=True, help="Number of runs to list.")
@click.option("-f", "--follow", is_flag=True, help="Keep printing new log lines of RUN_ID.")
@click.pass_context
def logs(
    ctx: click.Context, run_id: str | None, workflow: str | None, limit: int, follow: bool
) -> None:
    """Show recent runs, or the steps and logs of one run (prefix ids work)."""
    from flowpilot.store import Store

    settings = Settings.load(ctx.obj["project_dir"])
    store = Store(settings.database)
    if not run_id:
        runs = store.list_runs(workflow=workflow, limit=limit)
        if not runs:
            click.echo("no runs yet")
            return
        for r in runs:
            dur = f"{r['duration_ms']} ms" if r["duration_ms"] is not None else "…"
            click.echo(
                f"{r['id'][:12]}  {_local(r['started_at'])}  "
                f"{_status(r['status']):<20} {r['workflow']:<28} {r['trigger_type']:<9} {dur}"
            )
        return
    matches = [r for r in store.list_runs(limit=1000) if r["id"].startswith(run_id)]
    if not matches:
        click.secho(f"run {run_id!r} not found", fg="red", err=True)
        sys.exit(2)
    run_data = store.get_run(matches[0]["id"])
    assert run_data is not None
    click.echo(f"{click.style(run_data['workflow'], bold=True)}  {_status(run_data['status'])}")
    click.echo(
        f"run {run_data['id']}  trigger={run_data['trigger_type']}"
        f"  started={_local(run_data['started_at'])}"
    )
    if run_data["error"]:
        click.secho(run_data["error"], fg="red")
    click.echo()
    for s in run_data["steps"]:
        click.echo(
            f"  {_status(s['status']):<20} {s['step_id']} ({s['type']}, {s['duration_ms']} ms)"
        )
    click.echo()
    last_id = 0
    while True:
        for line in store.get_logs(run_data["id"], after_id=last_id):
            last_id = line["id"]
            level = line["level"]
            color = {"error": "red", "warning": "yellow", "debug": "bright_black"}.get(level)
            step = f"[{line['step_id']}] " if line["step_id"] else ""
            tag = click.style(f"{level.upper():<7}", fg=color)
            click.echo(f"{_local(line['ts'])[11:]} {tag} {step}{line['message']}")
        current = store.get_run(run_data["id"])
        if not follow or (current and current["status"] != "running"):
            break
        time.sleep(1)


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
@click.pass_context
def steps(ctx: click.Context, as_json: bool) -> None:
    """List available step types (built-in and plugins)."""
    project = _load_project(ctx, quiet=True)
    types = project.engine.registry.all()
    if as_json:
        click.echo(json.dumps([t.to_dict() for t in types], indent=2))
        return
    for t in types:
        src = "" if t.source == "builtin" else click.style(f"  [{t.source}]", fg="magenta")
        click.echo(f"{click.style(t.name, fg='cyan', bold=True):<30} {t.description}{src}")


def main() -> None:
    """Console-script entry point."""
    cli(obj={})


if __name__ == "__main__":  # pragma: no cover
    main()
