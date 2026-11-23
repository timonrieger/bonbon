# Decisions

Short records of decisions that someone (or an agent) might otherwise undo. One file per decision, numbered, never deleted; if a decision changes, add a new one that supersedes it.

Template: copy an existing file. Sections: **Context**, **Decision**, **Consequences**. Ten to twenty lines is plenty.

| #                                               | Decision                                                                      |
| ----------------------------------------------- | ----------------------------------------------------------------------------- |
| [0001](0001-learner-lab-constraints.md)         | Work within Learner Lab constraints: LabRole only, us-east-1                  |
| [0002](0002-dynamodb-single-table.md)           | DynamoDB single table (superseded by 0006)                                    |
| [0003](0003-textract-primary.md)                | Textract AnalyzeExpense as primary extraction                                 |
| [0004](0004-per-person-cloud-dev-stacks.md)     | Develop against personal cloud stacks, no local AWS emulation, no Docker      |
| [0005](0005-openapi-generated-client.md)        | Type-safe API via OpenAPI + generated client instead of tRPC                  |
| [0006](0006-postgresql-on-rds.md)               | PostgreSQL on RDS instead of DynamoDB                                         |
| [0007](0007-worker-split-and-db-credentials.md) | Worker split and database credentials without NAT                             |
| [0008](0008-frontend-on-amplify-hosting.md)     | Frontend on Amplify Hosting, because CloudFront is blocked in the Learner Lab |
| [0009](0009-manual-deploys.md)                  | Deploys stay manual, no deployment from GitHub Actions                        |
| [0010](0010-session-scoped-query-client.md)     | One frontend QueryClient per authenticated session                            |
