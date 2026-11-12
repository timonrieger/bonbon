# 05 Account deletion

**Owners:** @Dam-Mil (deletion worker), @RR02-rr (dialog) · **Milestone:** M3

## Done when

- [ ] The app shows per household what will happen, and requires re-authentication
- [ ] The API disables the Cognito account immediately and queues a deletion job (own SQS queue)
- [ ] The worker deletes all households where the user is the only member, including receipts, monthly totals and S3 images
- [ ] In shared households the user is removed like on leaving: receipts stay, the link to the user is removed, the owner role goes to the longest-standing member
- [ ] Finally the Cognito account is deleted
- [ ] All steps can be repeated safely; failures go to a DLQ and trigger a CloudWatch alarm
- [ ] Done within a few minutes

## Implementation status

### Frontend (`packages/web`) — @RR02-rr

**Implemented** (`feat/frontend-rabit`):

- `src/components/DeleteAccountDialog.tsx`: single-step confirmation dialog
  - Explains all three consequences (sole-member households deleted, shared
    households: user removed and owner role transferred, action irreversible)
  - Checkbox acknowledgement: the confirm button only becomes clickable after
    the user ticks "Ich habe die Konsequenzen gelesen …"
  - Visible in-dialog notice: *„Die Kontolöschung ist noch nicht verfügbar"*
  - `onConfirmed()` callback (no parameters) — parent is responsible for the
    API call and subsequent `signOut()`; `onConfirmed` is not attached to the
    button while it is `disabled`, so no accidental trigger path exists
  - Confirm button has two guards: checkbox state + hardcoded `disabled` until
    the backend endpoint exists; no fake deletion, no simulated success message
  - Escape key closes the dialog unless `isSaving` is true
  - `isSaving` prop disables all controls during an in-flight deletion request
  - Initial focus: `useEffect` focuses the dialog container (`tabIndex={-1}`)
    on mount so keyboard navigation starts inside the dialog immediately
  - Focus return: `triggerRef` prop (optional) receives focus when the dialog
    closes, returning keyboard users to the "Konto löschen" button
  - All interactive elements labelled via `useId()`-based IDs;
    `aria-modal`, `role="dialog"`, `aria-labelledby`, `aria-describedby`
- `src/App.tsx`: "Konto löschen" link in the header opens the dialog;
  `fetchUserAttributes()` loads the email once on mount (cached by Amplify)
  for display only; `deleteButtonRef` passed as `triggerRef` to restore focus

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
4. Add `onClick={onConfirmed}` to the confirm button and remove the hardcoded `disabled`
5. Pass `isSaving={del.isPending}` to `<DeleteAccountDialog>`

### Backend / worker — @Dam-Mil

**Planned** (all items open):
- `DELETE /users/me`: disable Cognito account immediately, insert job into deletion SQS queue
- Deletion worker: remove sole-member households (receipts + S3 images), remove user
  from shared households (transfer owner role), then delete Cognito account
- Dedicated SQS queue + DLQ for deletion jobs
- CloudWatch alarm on DLQ depth
