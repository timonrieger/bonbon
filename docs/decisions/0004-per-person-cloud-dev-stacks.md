# 0004 Personal cloud dev stacks, no local AWS emulation, no Docker

**Status:** accepted

## Context

The app consists only of managed services: Lambda, API Gateway, Cognito, DynamoDB Streams, SQS, S3 events, Textract. Local emulators either don't exist (Cognito, Textract), behave differently (Streams, S3 → SQS), or need Docker, which is a common setup hurdle for less technical team members. Each member has their own AWS account anyway.

## Decision

- Every developer deploys their own stack `bonbon-dev` into their own Learner Lab account. `mise run dev` runs the frontend locally and syncs backend changes to that stack within seconds (`sam sync --watch`).
- Business logic is tested locally with pytest + moto (in-process fake AWS, no Docker).
- Production is the `bonbon-prod` stack in @timonrieger's account, deployed manually with `mise run deploy:prod` from `main`.
- CI runs checks only and never deploys, because Learner Lab credentials expire every few hours.

## Consequences

- No Docker anywhere. Idle serverless stacks cost close to nothing.
- You need a running lab session (and fresh credentials via `mise run creds`) to develop against the cloud.
- `sam sync` is for dev only; prod always uses `sam deploy`.
