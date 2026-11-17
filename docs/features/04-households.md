# 04 Shared households

**Owners:** @nosernoel (API, data model), @schmid277 (household UI) · **Milestone:** M3

## Done when

- [x] Create a household; creator becomes owner (`POST /households`)
- [x] Members can read their household; non-members get 404 (`GET /households/{household_id}`)
- [x] List the households I'm a member of (`GET /households`)
- [x] List the members of a household with their display names, owner first (`GET /households/{household_id}/members`)
- [x] Invite via random code, valid 48 h, single use; only a hash is stored; expired via `expires_at` (optional: join without code)
- [x] Joining is one transaction: create member and invalidate the code
- [x] Failed join attempts are limited per user; API Gateway throttles
- [x] Every receipt belongs to exactly one household; all reports use that household's data
- [ ] Members can leave, the owner can remove members; access ends immediately
- [ ] Owner hands over the role before leaving; when the last member leaves, the household, its receipts and images are deleted

## Rules

- Every member can create invite codes, not only the owner.
- A household can have several active invite codes at the same time; each one works once.
- At most 5 failed join attempts per user and hour (`join_attempts`); further attempts are rejected until the hour has passed.
- The owner can't leave without handing over the role first: the API answers `409`. The role passes automatically only on account deletion ([05](05-account-deletion.md)).

## API

- `createInvite` `POST /households/{household_id}/invites` → 201 `{code, expires_at}`. Code as `XXXX-XXXX` (8 characters without 0/O/1/I/L, about 40 bits); only its SHA-256 is stored. Creating one also deletes the household's used and expired codes.
- `joinHousehold` `POST /households/join` `{code}` → 200 the household with `my_role: "member"`. Case, dashes and spaces in the code don't matter.
  - 404: code unknown, expired or used; counts as a failed attempt.
  - 409: already a member; the code stays valid and nothing is counted.
  - 429: 5 failed attempts within the last hour, checked before the code.
- API Gateway throttles the whole stage at 25 requests/s (burst 50), for all users together.

## Notes

`households/` in the backend is the reference implementation for all other domains. Keep it clean.
