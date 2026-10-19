# Workflow

## The loop

1. **Pick an issue** on the project board. If there isn't one, create it with the "Task" template and copy the acceptance criteria from `docs/features/`.
2. **Branch:** `git switch -c feat/short-name` (or `fix/…`, `docs/…`).
3. **Work with your agent** (see below).
4. **Check:** `mise run check` (or `Terminal → Run Task… → Check`). Fix until it passes.
5. **Try it for real** on your dev stack with `mise run dev`. Unit tests alone don't count.
6. **Commit** with a [Conventional Commit](https://www.conventionalcommits.org/) message, e.g. `feat: upload receipts via presigned URL`. The pre-commit hooks run automatically. If they modify files, `git add` and commit again.
7. **Pull request** into `main`. Fill in the checklist honestly and request a review from your stand-in (see proposal chapter 6).
8. **Merge** after one approval and green CI. Delete the branch.

## Working with AI agents

The agent reads `AGENTS.md` automatically. Help it further:

- **Start with context:** "Implement the 'list my households' criterion from docs/features/04-households.md. Follow the existing households pattern."
- **One thing per prompt.** Small tasks give reviewable diffs.
- **Ask for a plan first** on anything bigger than one file: "Plan this first, don't write code yet."
- **Make it verify:** "Run `mise run check` and fix all errors."
- **Read the diff yourself** before committing. You're responsible for it, not the agent. If you don't understand a part, ask the agent to explain it, or ask the area's owner.
- **Never** let an agent: add AWS services not in the proposal, create IAM roles, paste credentials into files, skip or disable hooks (`--no-verify`), or edit generated files.
- If the agent goes in circles after two or three tries, stop, run `git restore .` and start over with a clearer prompt, or ask a teammate.

## Docs are part of the work

If your change alters behavior or architecture, update the matching doc in the same PR:

- Feature progress → tick the checkbox in `docs/features/`
- New AWS resource or data item → `docs/architecture.md`
- A choice between alternatives → new file in `docs/decisions/`

These docs feed directly into the final report.
