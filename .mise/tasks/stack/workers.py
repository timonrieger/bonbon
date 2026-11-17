#!/usr/bin/env -S uv run --script
# [MISE] description="Re-enable the queue triggers of the worker Lambdas (default: bonbon-dev)"
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Re-enable a stack's SQS event source mappings. Usage: mise run stack:workers [stack]

When a Learner Lab session ends, LabRole loses its permissions for a moment. Lambda's SQS
poller then fails with AccessDenied and disables the mapping for good (CloudTrail event
`LambdaESMDisabled`). The next session doesn't turn it back on, and neither does a deploy,
because the template didn't change. Without this, uploads stay `uploaded` forever.
"""

import json
import subprocess
import sys


def aws(*args: str) -> dict:
    result = subprocess.run(
        ["aws", *args, "--output", "json"], check=False, capture_output=True, text=True
    )
    if result.returncode != 0:
        sys.exit(f"aws {' '.join(args[:2])} failed. Credentials expired?\n{result.stderr}")
    return json.loads(result.stdout)


stack = sys.argv[1] if len(sys.argv) > 1 else "bonbon-dev"
stacks = subprocess.run(
    ["aws", "cloudformation", "describe-stacks", "--stack-name", stack],
    check=False,
    capture_output=True,
    text=True,
)
if stacks.returncode != 0:
    if "does not exist" in stacks.stderr:
        print(f"Stack {stack} doesn't exist yet; nothing to enable.")
        sys.exit(0)
    sys.exit(f"Could not read stack {stack}. Credentials expired?\n{stacks.stderr}")

resources = aws("cloudformation", "describe-stack-resources", "--stack-name", stack)
mappings = [
    r for r in resources["StackResources"] if r["ResourceType"] == "AWS::Lambda::EventSourceMapping"
]
for mapping in mappings:
    name, uuid = mapping["LogicalResourceId"], mapping["PhysicalResourceId"]
    state = aws("lambda", "get-event-source-mapping", "--uuid", uuid)["State"]
    if state == "Disabled":
        aws("lambda", "update-event-source-mapping", "--uuid", uuid, "--enabled")
        print(f"{name}: re-enabled")
    else:
        print(f"{name}: {state}")
