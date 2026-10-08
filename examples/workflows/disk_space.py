"""A workflow defined in Python, together with its own custom step.

Any ``WorkflowSpec`` object found at module level is loaded, so you can build
workflows programmatically (loops, shared constants, generated steps…).
"""

from __future__ import annotations

import shutil

from flowpilot import StepContext, define, step


@step("disk_usage", description="Report disk usage of a path")
def disk_usage(ctx: StepContext, path: str = "/") -> dict:
    total, used, free = shutil.disk_usage(path)
    return {
        "path": path,
        "percent": round(used / total * 100, 1),
        "free_gb": round(free / 1024**3, 1),
    }


workflow = define(
    "disk-space-alert",
    description="Warn on Telegram when a disk is almost full.",
    tags=["monitoring", "python"],
    trigger={"type": "cron", "cron": "*/15 * * * *"},
    vars={"threshold": 90, "paths": ["/"]},
    steps=[
        {
            "id": "usage",
            "type": "disk_usage",
            "for_each": "{{ vars.paths }}",
            "with": {"path": "{{ item }}"},
        },
        {
            "id": "alert",
            "type": "telegram",
            "for_each": "{{ steps.usage.output }}",
            # Plain expressions (no braces) are allowed in `if`.
            "if": "item.percent >= vars.threshold",
            "with": {
                "text": "💾 <b>{{ item.path }}</b> is {{ item.percent }}% full "
                "({{ item.free_gb }} GB free)"
            },
        },
    ],
)
