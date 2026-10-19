#!/usr/bin/env -S uv run --script
# [MISE] description="Fail if template.yaml would create IAM roles or policies (Learner Lab)"
# /// script
# requires-python = ">=3.14"
# dependencies = ["pyyaml"]
# ///
"""Fail if template.yaml would create IAM roles or policies, which the Learner Lab forbids."""

import sys

import yaml


class Loader(yaml.SafeLoader):
    pass


# Accept CloudFormation tags (!Ref, !Sub, …); their values don't matter here.
Loader.add_multi_constructor("!", lambda loader, suffix, node: None)

ROLE_CREATING = {"AWS::Serverless::Function", "AWS::Serverless::StateMachine"}

errors = []
for path in sys.argv[1:] or ["template.yaml"]:
    with open(path) as f:
        template = yaml.load(f, Loader=Loader)
    global_function = template.get("Globals", {}).get("Function", {})
    if "Policies" in global_function:
        errors.append(f"{path}: Globals.Function.Policies creates IAM roles")
    for name, resource in template.get("Resources", {}).items():
        kind = resource.get("Type", "")
        props = resource.get("Properties") or {}
        if kind.startswith("AWS::IAM::"):
            errors.append(f"{path}: {name} is an IAM resource ({kind})")
        if kind in ROLE_CREATING and "Policies" in props:
            errors.append(f"{path}: {name} has Policies, which creates an IAM role")
        if kind in ROLE_CREATING and "Role" not in props and "Role" not in global_function:
            errors.append(f"{path}: {name} has no Role, so SAM would create one")

if errors:
    print("Learner Lab: we cannot create IAM roles, every function uses LabRole.")
    print("\n".join(errors))
    sys.exit(1)
