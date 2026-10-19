# Bonbon

Turns photos of Swiss supermarket receipts (Migros, Coop, Aldi, Lidl) into a shared household spending overview. University project for CLDE (Cloud Development), built serverless and event-driven on AWS.

**New here?** Start with [docs/guides/setup.md](docs/guides/setup.md), then [docs/guides/workflow.md](docs/guides/workflow.md).

## Stack

- **Backend:** Python 3.14 on AWS Lambda ([Powertools](https://docs.powertools.aws.dev/lambda/python/latest/)), API Gateway, Cognito, DynamoDB, S3, SQS, SNS, Textract
- **Frontend:** Vite + React + TypeScript, TanStack Query, Tailwind CSS, Amplify Auth
- **API contract:** OpenAPI from Pydantic models → generated TypeScript client ([oazapfts](https://github.com/oazapfts/oazapfts))
- **Infrastructure:** AWS SAM (`template.yaml`)
- **Tooling:** [mise](https://mise.jdx.dev) for tools and tasks, [prek](https://prek.j178.dev) for git hooks

## Common commands

```sh
mise run dev        # app on localhost:5173 + live backend sync to your dev stack
mise run check      # everything CI checks, run before committing
mise run generate   # after changing API routes
mise tasks --all    # everything else
```

## Docs

[docs/README.md](docs/README.md) lists everything: architecture, feature specs, decisions, glossary. AI agents start at [AGENTS.md](AGENTS.md).
