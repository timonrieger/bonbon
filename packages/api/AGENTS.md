# Backend (packages/api)

Python 3.14 Lambda functions using [Powertools for AWS Lambda](https://docs.powertools.aws.dev/lambda/python/latest/). Dependencies are managed with uv; tests use pytest + moto (in-memory fake AWS).

## Layout

```text
src/bonbon/
  auth.py              current_user_id(), require_membership()
  db.py                DynamoDB table + key helpers (single table, see docs/architecture.md)
  http.py              make_resolver(): shared API setup (validation, CORS)
  openapi.py           ROUTERS list, prints the OpenAPI spec
  households/          one folder per domain
    models.py          Pydantic request/response models
    repo.py            all DynamoDB reads/writes for this domain
    routes.py          Powertools Router with the endpoints
  handlers/
    households.py      Lambda entry point: make_resolver(router) + handler()
tests/                 one test file per domain, api_request() helper in conftest.py
```

Workers that are not HTTP (SQS, S3 events, DynamoDB Streams) go in `handlers/` too, with their logic in the domain folder.

## Adding an endpoint

1. Models in `<domain>/models.py`, DynamoDB access in `<domain>/repo.py`.
2. Route in `<domain>/routes.py`. Always set `operation_id="camelCaseName"` (it becomes the frontend function name; a test enforces it). Call `require_membership` before touching household data.
3. New domain: add a handler in `handlers/`, add the router to `ROUTERS` in `openapi.py`, add an `AWS::Serverless::Function` in `template.yaml`.
4. Add an `Events:` entry in `template.yaml` with the same method and path. Path params use `{name}` there and `<name>` in Python.
5. Test in `tests/test_<domain>.py` using `api_request()`. Cover the non-member case.
6. `mise run generate`, then `mise run check`.

## Rules

- Keys are built only through helpers in `db.py`. Never write `"HH#" + …` inline.
- Writes that must happen together use `transact_write_items` (see `households/repo.py`).
- Workers must be idempotent: SQS and S3 can deliver the same event twice. Use conditional writes.
- Raise Powertools exceptions (`NotFoundError`, `BadRequestError`, …) for errors; don't build error responses by hand.
- `boto3` is provided by the Lambda runtime and is only a dev dependency. Runtime dependencies go in `[project.dependencies]`.
