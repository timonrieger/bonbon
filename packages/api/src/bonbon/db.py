"""DynamoDB access. One table for everything, see docs/architecture.md#data-model."""

import os
from functools import cache

import boto3


@cache
def table():
    return boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


def household_pk(household_id: str) -> str:
    return f"HH#{household_id}"


def member_sk(user_id: str) -> str:
    return f"MEMBER#{user_id}"


HOUSEHOLD_META_SK = "META"
