# 05 Account deletion

**Owners:** @Dam-Mil (deletion worker), @RR02-rr (dialog) · **Milestone:** M3

## Done when

- [ ] The app previews the consequences for each household and requires explicit checkbox confirmation
- [ ] After HTTP 202 the app confirms acceptance and signs out. HTTP 5xx, network errors and timeouts allow manual retry.
- [x] The API queues a deletion job (own SQS queue), then disables the Cognito account
- [x] The worker deletes all households where the user is the only member, including receipts and S3 images
- [x] In shared households the user is removed like on leaving: receipts stay, the link to the user is removed, the owner role goes to the longest-standing member
- [x] Finally the Cognito account is deleted
- [x] Failed jobs are retried and can reach a DLQ monitored by a CloudWatch alarm
- [ ] All cleanup paths recover safely after a partial failure
- [ ] Verify that a real account deletion completes within the target of a few minutes

## Implementation status

### Frontend (`packages/web`) — @RR02-rr

**Implemented**:

- The header opens a modal that loads the signed-in user's households and their
  membership lists through the existing API and a session-scoped preview query.
  A confirmed access denial evicts cached private household data, and the dialog
  refreshes the household list before enabling confirmation. It shows the
  consequences for sole members, shared members and shared owners. For an owner,
  it explains that the longest-standing remaining member takes over. Memberships
  can change between the preview and the worker run.
- The destructive action requires a complete preview and explicit checkbox
  confirmation. The dialog supports keyboard navigation and restores focus on
  cancellation. During submission it prevents duplicate requests and dismissal.
- The existing Cognito session authorizes the generated `deleteAccount` call
  through `useSessionMutation`. The request has a 20-second deadline and no
  automatic retry.
- HTTP 202 means the request was accepted. The app displays an acceptance
  message outside the authenticated session and calls the Authenticator's
  sign-out action. Session teardown aborts outstanding work and clears its
  query cache. A new authenticated session clears the acceptance message.
- HTTP errors, network errors and timeouts keep the dialog open for manual
  retry. A lost response or timeout can leave the outcome unknown. Session
  cancellation does not show a request error from the old session.

**Validation:** The browser regression fixture runs against mocked responses.
Start `mise run //packages/web:dev` and open `/tests/account-deletion.html`.
The AWS dev deployment succeeded, the deletion worker is enabled, and migrations
0007 and 0008 were applied. Actual end-to-end account deletion and its duration
remain unverified on AWS.

### Backend / worker — @Dam-Mil

**Implemented**: the `DELETE /users/me` endpoint, the deletion queue + DLQ + alarm, and
the tombstone table (migration 0008) in #65; the cleanup + orchestrator worker Lambdas
in #66. The queue starts asynchronous processing without a grace period. The
completion target is a few minutes.

**Lambdas.** VPC Lambdas reach only the database and S3 (gateway endpoint), not Cognito
or SQS ([0007](../decisions/0007-worker-split-and-db-credentials.md)). So:

- `DELETE /users/me`: new users Lambda **outside** the VPC (the first API Lambda there).
  Queues the deletion job first (`SendMessage`), then disables the Cognito account
  (`AdminDisableUser`), then answers `202`. Order (team decision, #58): queue before disable.
  An SQS error propagates as a 5xx before the endpoint attempts to disable the account.
  If the SQS response is lost, a job may already have been queued. A failure to disable
  the account after queueing is logged and the endpoint still returns `202`. The worker
  tombstones the id and deletes the Cognito account. A retry can enqueue a duplicate job.
  The worker tolerates
  already-removed memberships and accounts, subject to the cleanup limitations below. An
  already-issued ID token stays valid until it expires, so the tombstone (not the disable) is
  what blocks requests during deletion. Reads `sub` straight from the authorizer claims, never
  from the request, and not through
  `bonbon.auth.current_user_id`: that syncs the user to the database, which this Lambda can't
  reach.

- Deletion worker **outside** the VPC, triggered by the deletion queue. Invokes a cleanup
  Lambda **inside** the VPC (`lambda:Invoke`, synchronous) for all database and S3 work,
  then deletes the Cognito account (`AdminDeleteUser`; `UserNotFoundException` counts as
  success, so a retry doesn't fail on it).
  A synchronous invoke answers `200` even when the cleanup Lambda raises; the error is only
  in `FunctionError`. The worker must check it and raise itself, otherwise nothing reaches
  the DLQ. Timeouts must nest: cleanup Lambda < the worker's boto3 `read_timeout` < worker
  Lambda < the queue's visibility timeout.
- Dedicated SQS queue + DLQ (copy `ReceiptsQueue`/`ReceiptsDeadLetterQueue`), CloudWatch
  alarm on DLQ depth.
- LabRole permissions checked with `iam simulate-principal-policy` (2026-11-19):
  `AdminDisableUser`, `AdminDeleteUser`, `lambda:InvokeFunction`, `sqs:SendMessage` and
  `cloudwatch:PutMetricAlarm` are allowed. Confirm on the dev stack.

**Cleanup Lambda, in this order.** SQS retries the whole job when a step raises.
The cleanup is designed to tolerate repeats, with the limitations below.

1. **Block the user.** Insert the user id into a new tombstone table (migration; only the
   `sub`, no personal data, `ON CONFLICT DO NOTHING`). `bonbon.auth.current_user_id` answers
   `401` for tombstoned ids instead of calling `users.sync`.
   *Why:* disabling the Cognito account does not revoke ID tokens already issued. API Gateway
   checks only signature and expiry, so a token stays valid for up to 60 minutes (tested on a
   dev stack: `200` after `AdminDisableUser` and after `AdminUserGlobalSignOut`; only token
   refresh fails). Without the
   tombstone, a request with that token would recreate the `users` row (name, e-mail) after
   the worker deleted it, or join a household with an invite code.
2. **Sole-member households: close them, then delete their files.** In one transaction with
   the household locked (`FOR UPDATE`, as in `remove_member`): if the user is the only
   member, delete the household's invite codes so nobody can join any more. Then call
   `receipts.storage.delete_household_files(household_id)`. It doesn't raise on single
   objects S3 refuses but returns their keys: treat a non-empty list as a failure.
   *Why before the database:* once `remove_member` has deleted the household, it no longer
   shows up in the user's memberships, so a retry after an S3 failure would never find its
   files again. Leaving a household (04) deletes files best effort; here they must be gone.
3. **Every household:** `households.repo.remove_member(household_id, user_id, hand_over=True)`.
   Deletes sole-member households (cascading to receipts and items) and, in shared ones,
   removes the user and hands the owner role to the member who joined first. Households
   already left in an earlier attempt are no longer in the list, so a retry skips them.
4. **Delete the `users` row** (receipts keep `uploaded_by = NULL`, migration 0003). Keep the
   tombstone.

**Known limitations.**

- The tombstone check is one database query per request, past the `_synced` cache in
  `bonbon.auth`.
- An upload link issued before the deletion stays valid for 300 s (`UPLOAD_URL_EXPIRES_IN`).
  A file uploaded after step 2 is left in S3, together with its Textract result.
- If the last other member leaves between preparation and membership removal,
  the worker deletes the household row before attempting S3 cleanup. If that
  cleanup fails, the next attempt can no longer discover the household through
  the user's memberships. Its files can remain in S3.
