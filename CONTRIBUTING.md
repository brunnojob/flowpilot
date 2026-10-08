# Contributing to flowpilot

Thanks for your interest! Bug reports, docs fixes, new step types and triggers are all welcome.

## Development setup

```bash
git clone https://github.com/mrzroot/flowpilot.git
cd flowpilot
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Before you open a pull request

```bash
ruff check .          # lint
ruff format .         # format
mypy                  # type-check
pytest --cov=flowpilot
flowpilot -p examples validate
```

CI runs the same commands on Python 3.10, 3.11 and 3.12.

## Trying workflows without a real Telegram bot

`scripts/mock_telegram.py` is a tiny fake Bot API server that prints every message:

```bash
python scripts/mock_telegram.py --port 8081 &
TELEGRAM_API_BASE=http://127.0.0.1:8081 TELEGRAM_BOT_TOKEN=test TELEGRAM_CHAT_ID=1 \
  flowpilot -p examples run crypto-digest
```

## Guidelines

- Keep the core small and dependency-light; it should run comfortably on a Raspberry Pi.
- New step types go in `src/flowpilot/steps/` and are registered with `@step`.
  Parameters are plain keyword arguments; raise `StepConfigError` for bad input
  (never retried) and `StepError` for runtime failures (retried when `retryable=True`).
- Every feature needs tests. HTTP calls are mocked with `respx`; never hit the network in tests.
- Public functions and classes get type hints and docstrings.
- Update `CHANGELOG.md` under *Unreleased*.
- Commit messages: short imperative subject line (`Add discord step`, `Fix cron DST bug`).

## Reporting security issues

Please do **not** open a public issue — see [SECURITY.md](SECURITY.md).
