# 04 Shared households

**Owners:** P2 (API, data model), P5 (household UI) · **Milestone:** M3

## Done when

- [x] Create a household; creator becomes owner (`POST /households`)
- [x] Members can read their household; non-members get 404 (`GET /households/{household_id}`)
- [ ] List the households I'm a member of
- [ ] Invite via random code, valid 48 h, single use; only a hash is stored; expired codes removed by DynamoDB TTL (optional: join without code)
- [ ] Joining is one transaction: create member and invalidate the code
- [ ] Failed join attempts are limited per user; API Gateway throttles
- [ ] Every receipt belongs to exactly one household; all reports use that household's data
- [ ] Members can leave, the owner can remove members; access ends immediately
- [ ] Owner hands over the role before leaving; when the last member leaves, the household, its receipts and images are deleted

## Notes

`households/` in the backend is the reference implementation for all other domains. Keep it clean.
