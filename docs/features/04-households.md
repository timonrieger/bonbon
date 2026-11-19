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
- [x] Members can leave, the owner can remove members; access ends immediately
- [x] The household detail page lets members leave after confirmation and warns about last-member deletion
- [x] The household detail page lets the owner hand over the role to another member after confirmation
- [x] The household detail page lets the owner remove another member after confirmation
- [x] Owner hands over the role before leaving; when the last member leaves, the household, its receipts and images are deleted

## Rules

- Every member can create invite codes, not only the owner.
- A household can have several active invite codes at the same time; each one works once.
- At most 5 failed join attempts per user and hour (`join_attempts`); further attempts are rejected until the hour has passed.
- The owner can't leave without handing over the role first: the API answers `409`. The role passes automatically only on account deletion ([05](05-account-deletion.md)).
- An owner who is the only member can leave: that deletes the household.
- Only the owner can remove other members and hand over the role. Everyone can leave.
- Leaving, removing and handing over lock the household row, so parallel requests can't leave a household without members or without an owner. Joining and creating an invite also lock the household (`FOR KEY SHARE`) before any invite code, the same order as leaving, so a join can't deadlock with the last member leaving.

## API

- `createInvite` `POST /households/{household_id}/invites` → 201 `{code, expires_at}`. Code as `XXXX-XXXX` (8 characters without 0/O/1/I/L, about 40 bits); only its SHA-256 is stored. Creating one also deletes the household's used and expired codes.
- `joinHousehold` `POST /households/join` `{code}` → 200 the household with `my_role: "member"`. Case, dashes and spaces in the code don't matter.
  - 404: code unknown, expired or used; counts as a failed attempt.
  - 409: already a member; the code stays valid and nothing is counted.
  - 429: 5 failed attempts within the last hour, checked before the code.
- `leaveHousehold` `DELETE /households/{household_id}/members/me` → 204.
  - 404: not a member. 409: the owner, while other members remain.
  - The last member leaving deletes the household. Memberships, invite codes, receipts and items go with it (`ON DELETE CASCADE`); then the Lambda deletes `households/<id>/` and `textract-results/<id>/` from S3 through the gateway endpoint. That part is best effort: if S3 fails, the request still succeeds and the error is logged. Objects that `delete_objects` refuses individually (HTTP 200 with `Errors`) are logged by key and not counted as deleted.
- `removeMember` `DELETE /households/{household_id}/members/{user_id}` → 204.
  - 403: the caller isn't the owner. 404: the user isn't a member. The caller's own id works like `leaveHousehold` (incl. 409).
- `transferOwnership` `PUT /households/{household_id}/owner` `{user_id}` → 200 the members with their new roles (like `listMembers`).
  - 403: the caller isn't the owner. 404: the user isn't a member. Handing over to oneself changes nothing.
- Account deletion uses `repo.remove_member(household_id, user_id, hand_over=True)`: as on leaving, but the owner role passes to the member who joined first. No route uses it.
- API Gateway throttles the whole stage at 25 requests/s (burst 50), for all users together.

## Notes

`households/` in the backend is the reference implementation for all other domains. Keep it clean.
