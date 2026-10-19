# Frontend (packages/web)

Vite + React 19 + TypeScript single-page app, styled with Tailwind CSS v4. Built to static files and served from S3 + CloudFront.

## Layout

```text
src/
  main.tsx             providers: Amplify Authenticator, TanStack Query, Router
  App.tsx              layout + routes
  api/index.ts         configures the client (base URL, auth token); import API functions from '@/api'
  api/client.gen.ts    GENERATED from packages/api/openapi.json, never edit
  pages/               one component per route
  components/          reusable UI pieces
```

## Rules

- **Calling the API:** import functions from `@/api` (`getHousehold`, `createHousehold`, …). Never use `fetch` directly; the client adds the login token.
- **Server data always goes through TanStack Query:** `useQuery` for reads, `useMutation` for writes, as in `src/pages/`. No `useEffect` + `fetch`. For status polling (receipt processing) use `refetchInterval`.
- If an endpoint you need doesn't exist in `client.gen.ts`, it doesn't exist in the backend yet. Add it there first (see `packages/api/AGENTS.md`); don't fake it.
- Login is handled by Amplify's `<Authenticator>`; use `useAuthenticator()` for the current user and sign-out.
- Charts: Recharts. Styling: Tailwind classes, no separate CSS files.
- UI text in German, code in English. Imports use the `@/` alias.
- Config comes from `.env.local` (written by `mise run env`); never hard-code URLs or pool IDs.
