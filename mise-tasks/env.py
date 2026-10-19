#!/usr/bin/env -S uv run --script
# [MISE] description="Write packages/web/.env.local from a stack's outputs (default: bonbon-dev)"
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Write packages/web/.env.local from a deployed stack's outputs. Usage: mise run env [stack]"""

import json
import subprocess
import sys
from pathlib import Path

stack = sys.argv[1] if len(sys.argv) > 1 else "bonbon-dev"
result = subprocess.run(
    [
        "aws",
        "cloudformation",
        "describe-stacks",
        "--stack-name",
        stack,
        "--output",
        "json",
    ],
    check=False,
    capture_output=True,
    text=True,
)
if result.returncode != 0:
    sys.exit(f"Could not read stack {stack}. Deployed it? Credentials expired?\n{result.stderr}")
outputs = {
    o["OutputKey"]: o["OutputValue"] for o in json.loads(result.stdout)["Stacks"][0]["Outputs"]
}

env = {
    "VITE_API_URL": outputs["ApiUrl"],
    "VITE_USER_POOL_ID": outputs["UserPoolId"],
    "VITE_USER_POOL_CLIENT_ID": outputs["UserPoolClientId"],
}
path = Path(__file__).resolve().parent.parent / "packages" / "web" / ".env.local"
path.write_text("".join(f"{k}={v}\n" for k, v in env.items()))
print(f"Wrote {path}")
