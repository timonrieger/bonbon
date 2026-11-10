#!/usr/bin/env -S uv run --script
# [MISE] description="Apply database migrations on your dev stack ('status' shows tables and rows)"
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Invoke the stack's MigrateFunction, which runs inside the VPC next to the private database.

Usage: mise run db:migrate [migrate|status]   (stack: $BONBON_STACK, default bonbon-dev)
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

action = sys.argv[1] if len(sys.argv) > 1 else "migrate"
if action not in {"migrate", "status"}:
    sys.exit(f"Unknown action {action!r}; use migrate or status.")
stack = os.environ.get("BONBON_STACK", "bonbon-dev")


def aws(*args: str) -> str:
    result = subprocess.run(["aws", *args], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"aws {args[0]} {args[1]} failed. Credentials expired?\n{result.stderr}")
    return result.stdout


function = aws(
    "cloudformation",
    "describe-stacks",
    "--stack-name",
    stack,
    "--query",
    "Stacks[0].Outputs[?OutputKey=='MigrateFunctionName'].OutputValue",
    "--output",
    "text",
).strip()
if not function or function == "None":
    sys.exit(f"Stack {stack} has no MigrateFunctionName output. Deployed it with stack:up?")

with tempfile.NamedTemporaryFile(suffix=".json") as out:
    meta = json.loads(
        aws(
            "lambda",
            "invoke",
            "--function-name",
            function,
            "--cli-binary-format",
            "raw-in-base64-out",
            "--cli-read-timeout",
            "150",
            "--payload",
            json.dumps({"action": action}),
            "--output",
            "json",
            out.name,
        )
    )
    result = json.loads(Path(out.name).read_text())

print(json.dumps(result, indent=2, ensure_ascii=False))
if meta.get("FunctionError"):
    sys.exit(f"{action} failed, see above and the function's CloudWatch logs.")
