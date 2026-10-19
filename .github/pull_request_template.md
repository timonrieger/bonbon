## What and why

<!-- One or two sentences. What does this change, and why? -->

Closes #

## How I tested it

<!-- What did you click or run on your own dev stack? Screenshot for UI changes. -->

## Checklist

- [ ] `mise run check` passes
- [ ] Tested on my own dev stack (`mise run dev`), not only with unit tests
- [ ] New or changed endpoint: route has an `operation_id`, matching event in `template.yaml`, test in `packages/api/tests/`, client regenerated
- [ ] Every new route that touches household data calls `require_membership`
- [ ] No secrets, account IDs or IAM roles/policies added
- [ ] Docs updated if behavior or architecture changed (`docs/features/`, `docs/architecture.md`, new ADR in `docs/decisions/`)
- [ ] I read the whole diff myself, including what the AI agent wrote
