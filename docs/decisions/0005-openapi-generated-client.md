# 0005 OpenAPI + generated client instead of tRPC

**Status:** accepted

## Context

We want end-to-end type safety between backend and frontend so that a backend change can't silently break the frontend. tRPC requires a TypeScript backend and a single router function; our backend is Python with one Lambda per domain.

## Decision

- Routes are written with Powertools `APIGatewayRestResolver` and Pydantic models, which produce an OpenAPI spec (`packages/api/openapi.json`).
- [oazapfts](https://github.com/oazapfts/oazapfts) generates a single TypeScript file with one function per endpoint (`packages/web/src/api/client.gen.ts`), the same setup Immich uses.
- Both files are committed. A pre-commit hook regenerates them when Python routes change, and CI fails if they're stale.

## Consequences

- A breaking backend change makes the frontend type-check fail.
- Every route needs an explicit `operation_id`, which becomes the function name (enforced by a test).
