# 0006 PostgreSQL on RDS instead of DynamoDB

**Status:** accepted · Supersedes [0002](0002-dynamodb-single-table.md) · Amends [0001](0001-learner-lab-constraints.md) · Network and credentials: [0007](0007-worker-split-and-db-credentials.md)

## Context

The reports (totals per month, category and store, receipt lists, household membership) are relational queries. In DynamoDB every access pattern has to be designed into the keys, and monthly totals would need our own Streams aggregation. The team decided to switch to SQL and accept the cost of an always-on instance.

Feasibility tests in the Learner Lab (2026-11-02, 2026-11-03 and 2026-11-06):

- RDS PostgreSQL 18 on `db.t4g.micro`, Single-AZ, 20 GB gp3, encrypted, not public: works. Only the `default` DB subnet group can be used (own subnet groups fail), so the database lives in the default VPC.
- A Lambda with `LabRole` runs in the default VPC and connects (TCP 20 ms; login plus first query 216 ms on a cold start, about 40 ms warm). `max_connections` is 79.
- Blocked: Aurora Serverless v2 (with or without Data API), Aurora DSQL (`dsql:CreateCluster` missing for `voclabs` and `LabRole`), RDS IAM database authentication (`LabRole` has no `rds-db:connect`; login fails with "PAM authentication failed").
- From inside the VPC without NAT, Textract, Secrets Manager and SNS are unreachable (calls hang until the connect timeout). S3 works through a free gateway endpoint.
- A split worker works without NAT or paid endpoints: S3 → SQS → Textract Lambda outside the VPC → SQS → database Lambda inside the VPC → PostgreSQL (see 0007).
- Driver: pg8000 (pure Python, no native build for Lambda).
- A publicly accessible RDS would avoid the VPC, but Lambdas have no fixed IPs, so port 5432 would be open to the internet. Rejected.

## Decision

- Amazon RDS for PostgreSQL 18, `db.t4g.micro`, Single-AZ, 20 GB gp3, encrypted, not publicly accessible, `default` DB subnet group. One instance per stack (`bonbon-<stage>`).
- PostgreSQL rather than MySQL: `date_trunc` and `FILTER` for reports, native `uuid`, `CHECK` constraints and partial unique indexes, transactional schema migrations. Rather than Aurora: the smallest Aurora instance costs several times more and its extras are blocked or not needed.
- Lambdas that use the database run in the VPC with their own security group; the database security group allows port 5432 only from it. VPC and subnet ids are stack parameters looked up by `.mise/tasks/stack-params.py`, never hard-coded.
- TLS with certificate and hostname verification against the RDS CA bundle shipped in `bonbon/certs/global-bundle.pem`.
- Normalized tables instead of a single table (see [architecture.md](../architecture.md#data-model)). Monthly totals are computed with SQL `GROUP BY` at query time; the DynamoDB Streams aggregation is dropped. Invite codes expire via `expires_at` instead of DynamoDB TTL.
- No RDS Proxy. Each Lambda container reuses one connection; the sum of reserved concurrency of all database Lambdas stays well below 79 (today 41).
- Schema changes are numbered SQL files in `packages/api/src/bonbon/migrations/`, each applied in one transaction and recorded in `schema_migrations`. A migration Lambda inside the VPC runs them; `mise run db:migrate` invokes it, and `mise run stack:up` calls that automatically. CI can't reach the private database and doesn't deploy anyway (0004).
- Dev stacks: `BackupRetentionPeriod: 0`, `DeletionProtection: false`, `DeletionPolicy`/`UpdateReplacePolicy: Delete`.

## Consequences

- The instance costs money while idle: about 11.70 USD/month compute plus 2.30 USD storage, plus 0.80 USD for two secrets. Stopped, only storage and secrets remain (about 3.10 USD). Dev databases are stopped (`mise run db:stop`) or deleted (`mise run stack:down`) when not in use; AWS restarts a stopped instance after 7 days.
- Every developer who runs `stack:up` gets their own database and its cost.
- Lambdas in the VPC have no internet access; anything that calls Textract, SNS or Secrets Manager stays outside (0007).
- Deleting a stack takes up to about 20 minutes because AWS releases the Lambda network interfaces slowly; the security groups wait for that.
- The database is a single instance that doesn't scale automatically. Multi-AZ, read replicas and RDS Proxy are the production upgrade path and are documented as a known limitation.

## Open

- **Prod:** switch `DeletionPolicy` and `UpdateReplacePolicy` to `Snapshot` and set a backup retention before the first prod deploy with the database.
- **Tests:** moto can't fake PostgreSQL and Docker is ruled out (0004). For now, route tests replace the repo layer with in-memory fakes (`tests/fakes.py`), so the SQL itself is only exercised on a dev stack. Candidate for later: a pip-installable PostgreSQL such as `pgserver` as a dev dependency.
- **DynamoDB table:** stays in the template until all domains are on PostgreSQL, then removed together with `TABLE_NAME` and `moto[dynamodb]`.
