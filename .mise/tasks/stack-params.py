#!/usr/bin/env -S uv run --script
# [MISE] description="Print VPC parameters for sam deploy/sync (the account's default VPC)"
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Print `VpcId=… LambdaSubnetIds=…` for --parameter-overrides. Usage: stack-params.py

Looks up the account's default VPC with the AWS CLI so nothing account-specific is committed.
Only reads; never creates or changes anything.
"""

import json
import subprocess
import sys

# Availability zones (by zone id, which is the same in every account) where Lambda can't
# create network interfaces. use1-az3 is us-east-1e in some accounts and another letter in others.
LAMBDA_UNSUPPORTED_AZ_IDS = {"use1-az3"}


def aws(*args: str) -> dict:
    result = subprocess.run(
        ["aws", *args, "--output", "json"], check=False, capture_output=True, text=True
    )
    if result.returncode != 0:
        sys.exit(
            f"aws {' '.join(args)} failed. Credentials expired? (mise run creds)\n{result.stderr}"
        )
    return json.loads(result.stdout)


vpcs = aws("ec2", "describe-vpcs", "--filters", "Name=is-default,Values=true")["Vpcs"]
if not vpcs:
    sys.exit("This account has no default VPC; the Learner Lab normally has one.")
vpc_id = vpcs[0]["VpcId"]

subnets = aws("ec2", "describe-subnets", "--filters", f"Name=vpc-id,Values={vpc_id}")["Subnets"]
subnet_ids = sorted(
    s["SubnetId"] for s in subnets if s["AvailabilityZoneId"] not in LAMBDA_UNSUPPORTED_AZ_IDS
)
if len(subnet_ids) < 2:
    sys.exit(f"Expected at least two usable subnets in {vpc_id}, found {subnet_ids}.")

print(f"VpcId={vpc_id} LambdaSubnetIds={','.join(subnet_ids)}")
