# Backend (packages/api)

Python 3.14 Lambda functions using [Powertools for AWS Lambda](https://docs.powertools.aws.dev/lambda/python/latest/). Data lives in PostgreSQL on RDS (driver: pg8000). Dependencies are managed with uv; tests use pytest, moto for AWS and in-memory fakes for the database (`tests/fakes.py`).

## Layout

```text
src/bonbon/
  auth.py              current_user_id(), require_membership()
  db.py                PostgreSQL connection (one per container), query(), transaction()
  http.py              make_resolver(): shared API setup (validation, CORS)
  openapi.py           ROUTERS list, prints the OpenAPI spec
  households/          one folder per domain
    models.py          Pydantic request/response models
    repo.py            all SQL for this domain
    routes.py          Powertools Router with the endpoints
  handlers/
    households.py      Lambda entry point: make_resolver(router) + handler()
    migrate.py         applies migrations/ (invoked by `mise run db:migrate`)
  migrations/          numbered SQL files, 0001_init.sql, …
  certs/               RDS CA bundle for TLS verification
tests/                 one test file per domain, api_request() helper in conftest.py,
                       in-memory fakes for the repo functions in fakes.py
```

Workers that are not HTTP (SQS, S3 events) go in `handlers/` too, with their logic in the domain folder.

## Adding an endpoint

1. Models in `<domain>/models.py`, SQL in `<domain>/repo.py`. New tables or columns: a new migration file (next number); never edit one that was applied anywhere.
2. Route in `<domain>/routes.py`. Always set `operation_id="camelCaseName"` (it becomes the frontend function name; a test enforces it). Call `require_membership` before touching household data.
3. New domain: add a handler in `handlers/`, add the router to `ROUTERS` in `openapi.py`, add an `AWS::Serverless::Function` in `template.yaml` with the same `VpcConfig`, `DB_*` variables and a `ReservedConcurrentExecutions` as `HouseholdsFunction` (keep the total below 79 connections).
4. Add an `Events:` entry in `template.yaml` with the same method and path. Path params use `{name}` there and `<name>` in Python.
5. Test in `tests/test_<domain>.py` using `api_request()`. Cover the non-member case. Add the new repo functions to `tests/fakes.py` and patch them in `conftest.py`.
6. `mise run generate`, then `mise run check`.

## Rules

- SQL only in `repo.py` files (and the membership lookup in `auth.py`), always with `:named` parameters. Never build SQL with f-strings or `+` from input.
- Reads use `db.query()`. Writes that must happen together go in one `with db.transaction() as conn:` block (see `households/repo.py`).
- Workers must be idempotent: SQS and S3 can deliver the same event twice. Use conditional updates (`UPDATE … WHERE status = 'uploaded'`).
- Lambdas inside the VPC can't reach Textract, SNS or Secrets Manager (no NAT). Code that calls those runs in a Lambda outside the VPC (see docs/decisions/0007).
- Raise Powertools exceptions (`NotFoundError`, `BadRequestError`, …) for errors; don't build error responses by hand.
- `boto3` is provided by the Lambda runtime and is only a dev dependency. Runtime dependencies go in `[project.dependencies]`.
