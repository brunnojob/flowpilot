# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `discord` step for webhook messages and embeds, with environment configuration,
  delivery confirmation, retryable network/rate-limit errors and a notification example.

## [0.1.0] - 2026-10-08

First public release.

### Added

- **Engine**: asyncio workflow engine with sequential steps, per-step and per-workflow
  timeouts, retries with exponential backoff, `if` conditions, `for_each` loops,
  `continue_on_error`, `on_failure` handlers, per-workflow concurrency limits and
  persistent per-workflow `state`.
- **Triggers**: `cron` (with time zones), `interval`, `webhook` (shared secret or GitHub
  `X-Hub-Signature-256`), `file` (polling watcher), `feed` (RSS/Atom, one run per new
  entry) and `manual`.
- **Steps**: `http`, `telegram` (messages, long-message splitting, documents, photos,
  any Bot API method, custom API base), `email` (SMTP), `transform` (Jinja2 / JMESPath),
  `condition`, `branch`, `delay`, `log`, `python`, `shell` (opt-in), `file.write`,
  `file.read`, `sqlite`, `state`, `archive` (tar.gz/zip with retention).
- **Templates**: sandboxed Jinja2 with native-value rendering and filters including
  `jmespath`, `number`, `tojson`, `md_escape`, `jalali` (Persian calendar) and `fa_digits`.
- **Workflows in YAML or Python** (`flowpilot.define`), with static validation of step
  types and parameters.
- **Plugins**: `@step` decorator, `plugins:` setting and the `flowpilot.steps` entry point group.
- **Server**: FastAPI REST API, webhooks, Server-Sent Events, optional bearer-token auth,
  OpenAPI docs at `/api/docs`.
- **Dashboard**: dependency-free web UI with live run logs, run history, enable/disable,
  manual runs, workflow definitions and state; follows the system dark/light theme.
- **CLI**: `init`, `validate`, `list`, `run`, `serve`, `logs` (with `--follow`), `steps`.
- SQLite persistence (WAL) with automatic history pruning and crash recovery.
- Example workflows, Dockerfile, docker-compose, CI on Python 3.10–3.12.

[Unreleased]: https://github.com/mrzroot/flowpilot/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mrzroot/flowpilot/releases/tag/v0.1.0
