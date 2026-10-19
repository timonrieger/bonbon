# 05 Account deletion

**Owners:** P3 (deletion worker), P4 (dialog) · **Milestone:** M3

## Done when

- [ ] The app shows per household what will happen, and requires re-authentication
- [ ] The API disables the Cognito account immediately and queues a deletion job (own SQS queue)
- [ ] The worker deletes all households where the user is the only member, including receipts, monthly totals and S3 images
- [ ] In shared households the user is removed like on leaving: receipts stay, the link to the user is removed, the owner role goes to the longest-standing member
- [ ] Finally the Cognito account is deleted
- [ ] All steps can be repeated safely; failures go to a DLQ and trigger a CloudWatch alarm
- [ ] Done within a few minutes
