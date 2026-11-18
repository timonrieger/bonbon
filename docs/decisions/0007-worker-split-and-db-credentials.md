# 0007 Worker split and database credentials without NAT

**Status:** accepted · implemented (credentials; worker split stage 2 with both Lambdas and the S3 gateway endpoint) · Builds on [0006](0006-postgresql-on-rds.md)

## Context

The database is private in the default VPC (0006). Inside the VPC, without a NAT gateway, Lambdas can't reach Textract, SNS or Secrets Manager. A NAT gateway (about 33 USD/month) or interface endpoints (about 7.30 USD/month each, per AZ) would eat most of the 50 USD budget. RDS IAM authentication is blocked in the Learner Lab, so the Lambdas need a password.

## Decision

**Credentials**

- Two secrets in the stack (`AWS::SecretsManager::Secret` with `GenerateSecretString`, no rotation): `DbMasterSecret` for the master user `bonbon_admin` and `DbAppSecret` for `bonbon_app`.
- Not the RDS-managed master secret (`ManageMasterUserPassword`): it rotates every 7 days, and the copy in the Lambda configuration would then be wrong.
- CloudFormation resolves the secrets at deploy time (`{{resolve:secretsmanager:…}}`) and passes them to the VPC Lambdas as environment variables, because Secrets Manager isn't reachable at runtime.
- Only `MigrateFunction` gets the master user. The first migration creates `bonbon_app` with data rights only (SELECT, INSERT, UPDATE, DELETE on the app tables, no DDL); the migration Lambda sets its password from `DbAppSecret` on every run. API and worker Lambdas connect as `bonbon_app`.

**Worker split (stage 2)**

- `ReceiptsQueue` → Textract Lambda **outside** the VPC: calls Textract, stores the raw JSON in S3 under a prefix outside `households/` (otherwise the bucket notification fires again), and sends only the S3 key to a new `ResultsQueue` with its own DLQ.
- `ResultsQueue` → database Lambda **inside** the VPC: reads the JSON through an S3 gateway endpoint (free) and writes to PostgreSQL. It takes the receipt from `uploaded` straight to `done`, `failed` or `duplicate` in **one transaction**, guarded by `WHERE id = $1 AND status = 'uploaded'`: a duplicate delivery changes nothing, and a crash rolls everything back, so the retry starts clean and no receipt gets stuck half-processed. There is no `processing` status; nothing can write to the database while Textract runs, so the app shows `uploaded` as «in Bearbeitung».
- Failures are reported, not only dead-lettered: on its last attempt (`ApproximateReceiveCount` = 3) the Textract Lambda sends the error to the `ResultsQueue` instead of a result key before it fails, so the database Lambda sets `failed` and the message still lands in the DLQ for analysis.
- The gateway endpoint is created by the stack only if the default VPC doesn't have one for S3 yet (a condition fed by the deploy task); an existing endpoint is never touched. `stack-params.py` sets `CreateS3Endpoint` and recognizes the stack's own endpoint by its `bonbon:stack` tag, so a redeploy keeps it instead of counting it as existing.
- SNS notifications are sent from outside the VPC as well.

## Consequences

- No NAT gateway, no interface endpoints, no extra monthly cost beyond the database and two secrets (0.80 USD/month).
- **Known limitation:** the database passwords are visible in plain text in the Lambda configuration to anyone with `lambda:GetFunctionConfiguration`. In the Learner Lab every principal is `LabRole`/`voclabs` anyway, so this doesn't widen access; in a real deployment we would use RDS IAM auth or a Secrets Manager endpoint.
- Changing a secret takes effect only after the next deploy (new environment variables) and `db:migrate` (new role password).
- With dev and prod in the same account, the second stack uses the first one's endpoint. Deleting the stack that created it removes S3 access for the other until its next deploy, which then creates its own.
- One more queue and Lambda in the receipt pipeline; a receipt is processed in two hops.
- With all retries the pipeline takes at most 18 minutes (2 queues × 3 attempts × 180 s visibility timeout). The receipt list treats a receipt still `uploaded` after 30 minutes as an upload whose file never arrived and leaves it out. If the database Lambda itself fails three times, its receipt stays `uploaded` and drops out of the list too; the results DLQ shows it.
