# 05 Account deletion

**Owners:** @Dam-Mil (deletion worker), @RR02-rr (dialog) · **Milestone:** M3

## Done when

- [ ] The app shows per household what will happen, and requires re-authentication
- [ ] The API disables the Cognito account immediately and queues a deletion job (own SQS queue)
- [ ] The worker deletes all households where the user is the only member, including receipts and S3 images
- [ ] In shared households the user is removed like on leaving: receipts stay, the link to the user is removed, the owner role goes to the longest-standing member
- [ ] Finally the Cognito account is deleted
- [ ] All steps can be repeated safely; failures go to a DLQ and trigger a CloudWatch alarm
- [ ] Done within a few minutes

## Implementation status

### Frontend (`packages/web`) — @RR02-rr

**Implemented** (#16):

- `src/components/DeleteAccountDialog.tsx`: single-step confirmation dialog
  - Explains all three consequences (sole-member households deleted, shared
    households: user removed and owner role transferred, action irreversible)
  - Checkbox acknowledgement "Ich habe die Konsequenzen gelesen …"; once the
    endpoint exists, the confirm button should only become clickable after it is ticked
  - Visible in-dialog notice: *„Die Kontolöschung ist noch nicht verfügbar"*
  - No `onConfirmed` callback yet: it is added together with the endpoint, so no
    accidental trigger path exists
  - Confirm button is hardcoded `disabled` until the backend endpoint exists;
    no fake deletion, no simulated success message
  - Escape key closes the dialog unless `isSaving` is true
  - `isSaving` prop disables all controls during an in-flight deletion request
  - Initial focus: `useEffect` focuses the dialog container (`tabIndex={-1}`)
    on mount so keyboard navigation starts inside the dialog immediately
  - Focus return: `triggerRef` prop (optional) receives focus when the dialog
    closes, returning keyboard users to the "Konto löschen" button
  - All interactive elements labelled via `useId()`-based IDs;
    `aria-modal`, `role="dialog"`, `aria-labelledby`, `aria-describedby`
- `src/App.tsx`: "Konto löschen" link in the header opens the dialog; the email
  shown comes from `useAuthenticator()` (the login id, since users sign in with
  their email); `deleteButtonRef` passed as `triggerRef` to restore focus

**Why no password re-authentication in the dialog:**
Amplify v6 throws `UserAlreadyAuthenticatedException` when `signIn()` is called
while a session is already active. The backend `DELETE /users/me` endpoint receives
the existing Cognito ID token from the shared fetch wrapper — no separate
credential check is needed from the frontend. The checkbox acknowledgement is
the user-intent gate.

**Why `deleteUser()` from Amplify is NOT used:**
`deleteUser()` removes the Cognito account immediately but leaves all household
data and S3 receipts behind. The backend worker handles data cleanup first;
only then does it delete the Cognito account. Calling `deleteUser()` from the
frontend bypasses the entire cleanup pipeline.

**To wire up once `DELETE /users/me` is implemented:**

1. Run `mise run generate` — a `deleteAccount` function will appear in `client.gen.ts`
2. Add `onConfirmed: () => void` back to `DeleteAccountDialogProps`
3. In `App.tsx`, pass `onConfirmed` from a `useMutation` call:
   ```ts
   const del = useMutation({ mutationFn: () => deleteAccount() });
   // onConfirmed:
   del.mutate(undefined, { onSuccess: () => signOut() });
   ```
4. Add `onClick={onConfirmed}` to the confirm button and replace the hardcoded
   `disabled` with `disabled={!acknowledged || isSaving}`
5. Pass `isSaving={del.isPending}` to `<DeleteAccountDialog>`

### Backend / worker — @Dam-Mil

**Planned** (all items open). Agreed design: queue + worker as in the proposal, not a
synchronous request. "Instant" means no grace period; the worker is done within seconds.

**Lambdas.** VPC Lambdas reach only the database and S3 (gateway endpoint), not Cognito
or SQS ([0007](../decisions/0007-worker-split-and-db-credentials.md)). So:

- `DELETE /users/me`: new users Lambda **outside** the VPC (the first API Lambda there).
  Disables the Cognito account (`AdminDisableUser`), then sends `{user_id}` to the deletion
  queue, then answers `202`. Order matters: disable first, so the user can't sign in or
  refresh tokens any more. Reads `sub` straight from the authorizer claims, never from the
  request, and not through `bonbon.auth.current_user_id`: that syncs the user to the
  database, which this Lambda can't reach.
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

**Cleanup Lambda, in this order.** SQS retries the whole job on any failure, so every step
must survive running twice, and every failure must raise (otherwise nothing reaches the DLQ).

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
