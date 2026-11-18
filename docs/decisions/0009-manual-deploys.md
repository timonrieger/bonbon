# 0009 Deploys stay manual, no deployment from GitHub Actions

**Status:** accepted · Deviates from the proposal (chapter 2, «GitHub Actions: automatisches Deployment») · Replaces the CI reasoning in [0001](0001-learner-lab-constraints.md) and [0004](0004-per-person-cloud-dev-stacks.md)

## Context

The proposal plans automatic deployment with GitHub Actions. In a normal AWS account this is done with GitHub OIDC: an IAM OIDC provider plus a role that the workflow assumes, with no stored keys and nothing that expires. Both are IAM resources, which the Learner Lab forbids (0001).

The only credentials we have are the Learner Lab session keys. They can be stored as GitHub secrets, but they stop working when the lab session ends (about 4 hours). After that, every call fails with an explicit deny (`voc-cancel-cred`) until someone starts the lab and copies new keys from the lab page. There is no API to get new keys.

We looked at a semi-automatic variant (2026-11-17): a push to `main` starts a job that waits for approval in a GitHub environment, and the infra owner approves it after storing fresh keys as secrets. It works in principle, but it saves nothing. Starting the lab and copying keys is the actual work, and after that, `mise run deploy:prod` on the laptop takes the same effort. Per-author dev deploys on pull requests were dropped as well: in a personal repository only the owner can set environment secrets, and every author would have to refresh keys every 4 hours.

## Decision

- Prod is deployed manually by the infra owner from `main`, see [guides/deploy.md](../guides/deploy.md).
- GitHub Actions runs checks only (lint, tests, generated client up to date). `main` only changes through reviewed pull requests with green checks.
- Dev stacks stay as in 0004: `mise run dev` / `mise run stack:up` per person.

## Consequences

- Deploys depend on one person and a running lab session. Everything they need is pinned by mise, so another team member could deploy from their own account with the same commands.
- What runs on prod is whatever was on `main` at the last deploy. There is no automatic link between a merge and a deploy.
- With a real AWS account we would add an OIDC role for GitHub Actions and deploy every push to `main` automatically. The report names this as a Learner Lab limitation.
