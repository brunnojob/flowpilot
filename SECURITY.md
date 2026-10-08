# Security Policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 0.1.x   | ✅        |

## Reporting a vulnerability

Please report vulnerabilities **privately** through
[GitHub Security Advisories](https://github.com/mrzroot/flowpilot/security/advisories/new).
Include a description, reproduction steps and the affected version. You should get a
first response within a few days. Please do not disclose the issue publicly until a fix
is released.

## Hardening checklist for deployments

flowpilot executes automation that *you* define, so treat workflow files like code.

- **Bind to localhost** (the default) and put a reverse proxy with TLS in front if you
  need remote access.
- **Set `FLOWPILOT_API_TOKEN`** whenever the server is reachable from a network. It
  protects the REST API, the SSE streams and therefore the dashboard data.
- **Protect webhooks** with a `secret:` (shared header/query secret or GitHub
  `X-Hub-Signature-256`). Webhook payloads are untrusted input.
- **Keep `allow_shell` disabled** unless you need it. When enabled, shell steps run with
  the privileges of the flowpilot process. Never interpolate webhook or feed data into
  shell commands; prefer the list form (`command: [prog, arg1]`), which does not invoke
  a shell. Run flowpilot as an unprivileged user (the Docker image does).
- **Python steps and plugins** import and run arbitrary code from your project — only
  load code you trust.
- **Secrets** belong in environment variables or `.env` (never commit it). The Telegram
  step redacts the bot token from error messages, but anything you print in a `log`
  step or a template ends up in the run history.
- Templates are rendered in Jinja2's `ImmutableSandboxedEnvironment`, which blocks access
  to Python internals; they can still read every environment variable via `env`.
