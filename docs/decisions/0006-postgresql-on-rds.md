# 0006 PostgreSQL on RDS instead of DynamoDB

**Status:** proposed · Supersedes [0002](0002-dynamodb-single-table.md) · Amends [0001](0001-learner-lab-constraints.md)

## Context

The reports (totals per month, category and store, receipt lists, household membership) are relational queries. In DynamoDB every access pattern has to be designed into the keys, and monthly totals would need our own Streams aggregation. Aurora Serverless v2 is blocked in the Learner Lab (0002). The team decided to switch to SQL anyway and accept the cost of an always-on instance.

A feasibility test in the Learner Lab (2026-11-02) showed:

- RDS PostgreSQL 18 on `db.t4g.micro` (Single-AZ) can be created. Only the default DB subnet group can be used.
- A Lambda with `LabRole` can run in the default VPC and connects to the database (TCP 20 ms, login plus first query 216 ms on a cold start).
- `max_connections` is 79.
- Secrets Manager can hold the master password (RDS-managed secret).
- From inside the VPC, Textract is not reachable without a NAT gateway or VPC endpoint (connect timeout).

SQL options without a VPC were tested too, since the VPC causes most of the follow-up work:

- Aurora Serverless v2 with the Data API: blocked by policy (SW5, see 0002).
- Aurora DSQL (2026-11-03): blocked. Neither the `voclabs` role nor `LabRole` has `dsql:CreateCluster`; tried via CLI, CloudFormation (`AWS::DSQL::Cluster`, also fails on `dsql:TagResource`) and from a Lambda.
- RDS publicly accessible: possible, but Lambdas have no fixed IPs, so port 5432 would be open to the internet with only password and TLS as protection.

## Decision

- Amazon RDS for PostgreSQL, `db.t4g.micro`, Single-AZ, encrypted storage, not publicly accessible, default DB subnet group.
- PostgreSQL rather than MySQL: `date_trunc` and `FILTER` for reports, native `uuid`, `CHECK` constraints, `jsonb` for raw Textract output, transactional schema migrations. Rather than Aurora: the smallest Aurora instance (`db.t3.medium`) costs several times more and its extras (Serverless, fast failover) are blocked or not needed.
- Lambdas that use the database run in the VPC. The database security group allows port 5432 only from the Lambda security group.
- Normalized tables instead of a single table. Monthly totals are computed with SQL `GROUP BY` at query time; the planned DynamoDB Streams aggregation is dropped. Invite codes expire via an `expires_at` column instead of DynamoDB TTL.
- No RDS Proxy. Connections are reused across invocations and reserved concurrency keeps the total below the connection limit.

## Alternatives considered

- **Keep DynamoDB, aggregate at read time.** Drop the Streams aggregation; each receipt stores its store, date, total and per-category sums, and the dashboard sums one month's receipts per household in the Lambda. No VPC, no idle cost, no migrations, moto tests stay, and it matches the proposal. Downsides: no ad-hoc queries, no foreign keys, and the "receipts by month" index and the user-to-households lookup still have to be designed.

## Consequences

- The instance costs money while idle (roughly 12 USD/month plus storage per account). Dev databases are stopped or deleted when not in use.
- Lambdas in the VPC have no internet access. The worker needs a way to reach Textract and SNS (VPC endpoints or a worker split into a Textract part outside the VPC and a database part inside). To be decided with infra and worker owners in a separate ADR.
- Tests can no longer fake the database with moto; they need a local PostgreSQL without Docker (0004). To be decided separately.
- Schema changes are SQL migrations, applied on deploy from inside the VPC.
- The database is a single instance that does not scale automatically. Multi-AZ, read replicas and RDS Proxy are the production upgrade path and are documented as a known limitation.
