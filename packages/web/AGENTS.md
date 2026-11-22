# Frontend (packages/web)

Vite + React 19 + TypeScript single-page app, styled with Tailwind CSS v4. The production build in `dist/` is uploaded manually to Amplify Hosting with `mise run deploy:web`. Amplify serves `index.html` for client-side routes. Dev runs locally on Vite against the developer's AWS stack. See [hosting](../../docs/decisions/0008-frontend-on-amplify-hosting.md), [manual deployment](../../docs/decisions/0009-manual-deploys.md), and the [deploy guide](../../docs/guides/deploy.md).

## Layout

```text
src/
  main.tsx             Cognito configuration, Amplify Authenticator, session boundary, BrowserRouter
  App.tsx              layout + routes
  components/AuthenticatedSession.tsx
                       session QueryClient, API binding, session hooks
  api/index.ts         generated API exports, base URL, authenticated transport
  api/client.gen.ts    GENERATED from packages/api/openapi.json, never edit
  api/privateQuery.ts  Authenticated request helpers and private response handling
  features/households/ Household query keys, cache eviction and access hook
  features/receipts/   Browser image preparation and receipt upload workflow
  pages/               one component per route
  components/          reusable UI pieces
```

## Authentication and API

- Amplify's `Authenticator` handles Cognito sign-in. Use `useAuthenticator()` for the current user and sign-out. `AuthenticatedSession` mounts the app and an in-memory QueryClient for the active Cognito user. Ending or replacing that session aborts work and clears its cache. Cross-tab identity changes invalidate the session and prompt a reload. See [ADR 0010](../../docs/decisions/0010-session-scoped-query-client.md).
- Import API functions and generated models from `@/api`. The transport checks the Cognito ID token's subject against the active session and combines the session abort signal with any request signal. Direct S3 PUTs use `uploadToS3` from `@/api/receipts`, with the presigned URL and its signed headers.
- Use `useQuery` for reads and `useSessionMutation` for authenticated writes. Keep server reads in TanStack Query, including polling via `refetchInterval`, and pass the query signal to requests. The mutation hook checks queued work and callbacks against their originating session. Use `useSessionSignal` for browser work outside the transport and for callbacks that need to recheck the session after an `await`.
- `requestPrivateResource` applies `no-store` and preserves HTTP access errors. `readPrivateResource` maps unavailable responses to `null` for private reads.

## Household cache

- Read a household through `useHouseholdAccess(householdId)` from `@/features/households/useHouseholdAccess`. Use `householdAccessKey(householdId)` from `@/features/households/householdAccess` to update or invalidate the canonical `['householdAccess', householdId]` entry. Enable dependent reads only when access is available.
- Put the household ID second in private data keys. The receipt list uses `['receipts', householdId, selectedMonth]`, with an empty month for the unfiltered list. Invalidate the prefix `['receipts', householdId]` after uploads and corrections to cover every filter.
- Use `readHouseholdResource` and `handleHouseholdAccessError` from the same module when a denial establishes lost household access. Pass the request's abort signal to both. Confirmed denial records `null`, removes the household from cached household lists, and evicts its private queries. Aborted requests leave the cache alone. Recheck membership for a receipt 404 or an owner action that fails with insufficient permissions or a missing target member.

## Conventions

- **API types come from `@/api` too:** use the generated models and enums (`ReceiptDetail`, `ReceiptItem`, `ContentType`, `Status`, …), never hand-written copies or string literals. Form state that differs from the wire format derives from them (`Pick`, `Omit`, indexed access like `ReceiptUpload['upload_headers']`). Don't give components the same name as a generated type.
- If an endpoint you need doesn't exist in `client.gen.ts`, it doesn't exist in the backend yet. Add it there first (see `packages/api/AGENTS.md`); don't fake it.
- Charts: Recharts. Styling: Tailwind classes, no separate CSS files.
- UI text in German, code in English. Imports use the `@/` alias.
- `mise run env` writes dev configuration to `.env.local`. The production deploy uses `.env.production.local`. Keep URLs and pool IDs in the generated environment files.
