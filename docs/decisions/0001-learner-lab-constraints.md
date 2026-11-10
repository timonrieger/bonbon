# 0001 Work within Learner Lab constraints

**Status:** accepted

## Context

Each team member has an AWS Academy Learner Lab account with 50 USD of credit. The lab only allows `us-east-1`, forbids creating IAM roles and policies, and provides a fixed `LabRole`. Credentials expire when the lab session ends (about 4 hours).

## Decision

- All functions use `LabRole`. No `AWS::IAM::*` resources, no SAM `Policies:`.
- Everything is deployed to `us-east-1`.
- Prefer pay-per-use services that cost nothing when idle (no NAT gateways, no always-on compute). Exception: the RDS database, see [0006](0006-postgresql-on-rds.md).

## Consequences

- Per-function least privilege is impossible; we document it as a known limitation in the report.
- A pre-commit hook (`.mise/tasks/check-no-iam.py`) blocks IAM resources.
- Credentials can't be stored in GitHub, so CI doesn't deploy (see 0004).
