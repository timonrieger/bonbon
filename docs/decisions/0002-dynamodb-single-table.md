# 0002 DynamoDB single table

**Status:** accepted · Details: proposal chapter 2, "Begründung DynamoDB"

## Context

Reports (sums per month, category, store) would suit a relational database. Aurora Serverless v2 is blocked by Learner Lab policy; provisioned RDS/Aurora costs money while idle.

## Decision

One DynamoDB table in on-demand mode. All of a household's data lives under `PK = HH#<id>`. Monthly totals are pre-computed through DynamoDB Streams.

## Consequences

- No ad-hoc queries; every access pattern must be designed into the keys (see architecture.md#data-model).
- Aggregation logic is our own code and must be idempotent (recalculate, don't increment).
