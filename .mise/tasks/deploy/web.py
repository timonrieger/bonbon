#!/usr/bin/env -S uv run --script
# [MISE] description="Build the frontend and publish it to Amplify Hosting on prod. Only the infra owner runs this, from main"
# [MISE] confirm="Deploy the frontend to PROD (stack bonbon-prod in the current AWS account)?"
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Build packages/web against bonbon-prod and publish dist/ to the stack's Amplify app (ADR 0008).

Usage: mise run deploy:web   (stack: $BONBON_STACK, default bonbon-prod; run deploy:prod first)
"""

import io
import json
import os
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

stack = os.environ.get("BONBON_STACK", "bonbon-prod")
root = Path(__file__).resolve().parents[3]
dist = root / "packages" / "web" / "dist"


def aws(*args: str) -> dict:
    result = subprocess.run(
        ["aws", *args, "--output", "json"], check=False, capture_output=True, text=True
    )
    if result.returncode != 0:
        sys.exit(f"aws {args[0]} {args[1]} failed. Credentials expired?\n{result.stderr}")
    return json.loads(result.stdout)


stacks = aws("cloudformation", "describe-stacks", "--stack-name", stack)["Stacks"]
outputs = {o["OutputKey"]: o["OutputValue"] for o in stacks[0].get("Outputs", [])}
if "WebAppId" not in outputs:
    sys.exit(f"Stack {stack} has no WebAppId output. Only prod stacks host the frontend.")
app_id, url = outputs["WebAppId"], outputs["WebUrl"]

# .env.production.local wins over the dev .env.local in `vite build` (see env.py).
subprocess.run([root / ".mise" / "tasks" / "env.py", stack, ".env.production.local"], check=True)
subprocess.run(["mise", "run", "//packages/web:build"], cwd=root, check=True)

archive = io.BytesIO()
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
    for file in sorted(dist.rglob("*")):
        if file.is_file():
            zf.write(file, file.relative_to(dist).as_posix())

# Manual deploy: Amplify hands out an upload URL per job and publishes the zip as a whole.
deployment = aws("amplify", "create-deployment", "--app-id", app_id, "--branch-name", "main")
upload = urllib.request.Request(deployment["zipUploadUrl"], data=archive.getvalue(), method="PUT")
urllib.request.urlopen(upload).close()  # noqa: S310 (presigned https URL from Amplify)
job = deployment["jobId"]
aws("amplify", "start-deployment", "--app-id", app_id, "--branch-name", "main", "--job-id", job)

while True:
    status = aws("amplify", "get-job", "--app-id", app_id, "--branch-name", "main", "--job-id", job)
    status = status["job"]["summary"]["status"]
    print(f"Amplify job {job}: {status}")
    if status in {"SUCCEED", "FAILED", "CANCELLED"}:
        break
    time.sleep(5)

if status != "SUCCEED":
    sys.exit(f"Deployment {status.lower()}; see the Amplify console for app {app_id}.")
print(f"Live at {url}")
