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

**Planned** (all items open):
- `DELETE /users/me`: disable Cognito account immediately, insert job into deletion SQS queue
- Deletion worker: remove sole-member households (receipts + S3 images), remove user
  from shared households (transfer owner role). For each household, call
  `households.repo.remove_member(household_id, user_id, hand_over=True)`: it does both in
  one transaction and returns `True` if the household was deleted. Then delete its files with
  `receipts.storage.delete_household_files(household_id)` (needs S3, see [04](04-households.md)).
  Then delete the `users` row (receipts keep
  `uploaded_by = NULL`, migration 0003), then delete Cognito account
- Dedicated SQS queue + DLQ for deletion jobs
- CloudWatch alarm on DLQ depth
