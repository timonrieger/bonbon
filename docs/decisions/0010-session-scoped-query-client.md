# 0010 Session-scoped frontend QueryClient

**Status:** proposed · Implemented in PR #55

## Context

The frontend caches private household data, including reports and presigned receipt image URLs. A new Cognito identity in the same browser must start with an empty cache. Queued requests or late callbacks from the previous identity must stay tied to their original session.

## Decision

- `AuthenticatedSession` creates one in-memory TanStack QueryClient per signed-in session, keyed by Cognito user ID. Session teardown aborts work and clears the cache. A cross-tab change to Amplify's active identity record invalidates the session and prompts a reload.
- The API transport checks the token subject against the bound session and attaches its abort signal. `useSessionMutation` guards queued mutations and their callbacks. Backend membership checks remain responsible for authorizing each household request.

## Consequences

- Sessions start with a cold cache and reuse it across routes until sign-out or identity change. The session boundary adds lifecycle and cancellation logic, including explicit signals for image preparation and presigned S3 uploads.
- A shared QueryClient with user IDs in every private key would require every caller to scope reads, invalidations and writes consistently. Clearing a shared cache at sign-out would also require guards against late callbacks. A session-owned client puts that boundary in one place.
