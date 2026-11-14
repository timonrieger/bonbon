# 04 Shared households

**Owners:** @nosernoel (API, data model), @schmid277 (household UI) · **Milestone:** M3

## Done when

- [x] Create a household; creator becomes owner (`POST /households`)
- [x] Members can read their household; non-members get 404 (`GET /households/{household_id}`)
- [x] List the households I'm a member of (`GET /households`)
- [x] List the members of a household with their display names, owner first (`GET /households/{household_id}/members`)
- [ ] Invite via random code, valid 48 h, single use; only a hash is stored; expired via `expires_at` (optional: join without code)
- [ ] Joining is one transaction: create member and invalidate the code
- [ ] Failed join attempts are limited per user; API Gateway throttles
- [ ] Every receipt belongs to exactly one household; all reports use that household's data
- [ ] Members can leave, the owner can remove members; access ends immediately
- [ ] Owner hands over the role before leaving; when the last member leaves, the household, its receipts and images are deleted

## Rules

- Every member can create invite codes, not only the owner.
- A household can have several active invite codes at the same time; each one works once.
- At most 5 failed join attempts per user and hour (`join_attempts`); further attempts are rejected until the hour has passed.
- The owner can't leave without handing over the role first: the API answers `409`. The role passes automatically only on account deletion ([05](05-account-deletion.md)).

## Notes

`households/` in the backend is the reference implementation for all other domains. Keep it clean.
