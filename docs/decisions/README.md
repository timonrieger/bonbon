# Decisions

Short records of decisions that someone (or an agent) might otherwise undo. One file per decision, numbered, never deleted; if a decision changes, add a new one that supersedes it.

Template: copy an existing file. Sections: **Context**, **Decision**, **Consequences**. Ten to twenty lines is plenty.

| # | Decision |
|---|---|
| [0001](0001-learner-lab-constraints.md) | Work within Learner Lab constraints: LabRole only, us-east-1 |
| [0002](0002-dynamodb-single-table.md) | DynamoDB single table instead of a relational database |
| [0003](0003-textract-primary.md) | Textract AnalyzeExpense as primary extraction |
| [0004](0004-per-person-cloud-dev-stacks.md) | Develop against personal cloud stacks, no local AWS emulation, no Docker |
| [0005](0005-openapi-generated-client.md) | Type-safe API via OpenAPI + generated client instead of tRPC |
