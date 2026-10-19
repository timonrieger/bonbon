# AGENTS.md

Bonbon turns photos of Swiss supermarket receipts into a shared household spending overview. It's a university cloud project (CLDE) on AWS Learner Lab: serverless and event-driven, built by a team of five.

**Scope is fixed by [docs/project/kassenzettel.md](docs/project/kassenzettel.md)** (the approved proposal, German). Don't add features, endpoints or AWS services that aren't in it. If a task seems to need one, stop and ask.

## Commands

Everything runs through mise. Never call `pip`, `npm`, `sam deploy` etc. directly.

| Command | What it does |
|---|---|
| `mise run check` | Lint, type-check and test everything. **Run before every commit.** |
| `mise run test` | Backend tests only (AWS is faked with moto) |
| `mise run generate` | Regenerate `openapi.json` and the frontend client after changing Python routes |
| `mise run dev` | Frontend locally + live sync of the backend to the developer's own AWS stack |
| `mise run stack:up` | Full deploy of the developer's own dev stack |
| `mise tasks --all` | List all tasks |

## Repo map

- `packages/api/`: Python Lambda functions ([AGENTS.md](packages/api/AGENTS.md))
- `packages/web/`: React frontend ([AGENTS.md](packages/web/AGENTS.md))
- `template.yaml`: all AWS resources (SAM). `samconfig.toml`: deploy settings
- `docs/`: architecture, feature specs, decisions, guides ([index](docs/README.md))
- `.mise/`: tool versions and tasks (`config.toml`), plus script tasks in `tasks/` written as standalone uv scripts

## Hard rules

1. **No IAM.** The Learner Lab forbids creating IAM roles or policies. Never add `AWS::IAM::*` resources or `Policies:` to functions. Every function sets `Role: !Sub arn:aws:iam::${AWS::AccountId}:role/LabRole`. A pre-commit hook enforces this.
2. **Every route that touches household data calls `require_membership`** from `bonbon.auth`. Data isolation between households is a graded requirement.
3. **No secrets, account IDs or credentials in code.** Config comes from stack outputs and environment variables.
4. **Never edit generated files**: `packages/api/openapi.json`, `packages/web/src/api/client.gen.ts`. Run `mise run generate`.
5. **Copy the existing pattern.** Households (`packages/api/src/bonbon/households/`, `packages/web/src/pages/`) is the reference implementation. New code should look like it.
6. Don't add dependencies without a reason you can state in the PR.

## Conventions

- Code, comments, commits and docs in English; UI text in German.
- JSON fields are `snake_case` (the Pydantic default), on the wire and in the frontend.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat: …`, `fix: …`, `docs: …`).
- Terms: see [docs/glossary.md](docs/glossary.md) (Beleg = receipt, Haushalt = household, …).

## Definition of done

- `mise run check` passes.
- New endpoint: route + test + matching event in `template.yaml` + regenerated client.
- Works on the developer's own dev stack, not just in tests.
- If behavior or architecture changed, the matching file in `docs/` is updated in the same PR.
