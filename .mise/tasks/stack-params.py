#!/usr/bin/env -S uv run --script
# [MISE] description="Print VPC parameters for sam deploy/sync (the account's default VPC)"
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Print the VPC parameters for --parameter-overrides. Usage: stack-params.py <stack-name>

Looks up the account's default VPC with the AWS CLI so nothing account-specific is committed.
Only reads; never creates or changes anything.

CreateS3Endpoint is true unless the VPC already has an S3 gateway endpoint that this stack
didn't create (ADR 0007). Our own endpoint is recognized by its `bonbon:stack` tag; without
that check the next deploy would see it as "existing" and CloudFormation would delete it.
"""

import json
import subprocess
import sys

# Availability zones (by zone id, which is the same in every account) where Lambda can't
# create network interfaces. use1-az3 is us-east-1e in some accounts and another letter in others.
LAMBDA_UNSUPPORTED_AZ_IDS = {"use1-az3"}
S3_SERVICE = "com.amazonaws.us-east-1.s3"


def aws(*args: str) -> dict:
    result = subprocess.run(
        ["aws", *args, "--output", "json"], check=False, capture_output=True, text=True
    )
    if result.returncode != 0:
        sys.exit(
            f"aws {' '.join(args)} failed. Credentials expired? (mise run creds)\n{result.stderr}"
        )
    return json.loads(result.stdout)


if len(sys.argv) != 2:
    sys.exit("Usage: stack-params.py <stack-name>")
stack_name = sys.argv[1]

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

# All route tables of the VPC, so the endpoint covers every subnet (the default VPC has only
# its main route table).
route_tables = aws("ec2", "describe-route-tables", "--filters", f"Name=vpc-id,Values={vpc_id}")
route_table_ids = sorted(rt["RouteTableId"] for rt in route_tables["RouteTables"])

endpoints = aws(
    "ec2",
    "describe-vpc-endpoints",
    "--filters",
    f"Name=vpc-id,Values={vpc_id}",
    f"Name=service-name,Values={S3_SERVICE}",
    "Name=vpc-endpoint-type,Values=Gateway",
    "Name=vpc-endpoint-state,Values=pending,available",
)["VpcEndpoints"]
foreign_endpoints = [
    e["VpcEndpointId"]
    for e in endpoints
    if {"Key": "bonbon:stack", "Value": stack_name} not in e.get("Tags", [])
]
create_s3_endpoint = "false" if foreign_endpoints else "true"

print(
    f"VpcId={vpc_id} LambdaSubnetIds={','.join(subnet_ids)} "
    f"RouteTableIds={','.join(route_table_ids)} CreateS3Endpoint={create_s3_endpoint}"
)
