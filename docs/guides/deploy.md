# Deploying to prod

Only the infra owner deploys prod, by hand, from `main`. GitHub Actions doesn't deploy ([decisions/0009](../decisions/0009-manual-deploys.md)).

## Every deploy

1. Start the Learner Lab and save fresh credentials, as in [setup.md, step 3](setup.md#3-connect-your-learner-lab-account). The keys stop working when the lab session ends (about 4 hours), so do this each session.
2. Check out the current `main`:

   ```sh
   git switch main && git pull
   ```

3. Deploy the backend, then migrate the database:

   ```sh
   mise run deploy:prod                         # shows the changeset and asks before applying
   BONBON_STACK=bonbon-prod mise run db:migrate
   ```

4. Publish the frontend:

   ```sh
   mise run deploy:web
   ```

   It prints the app's address at the end.

## If something fails

- `explicit deny … voc-cancel-cred` or `ExpiredToken`: the lab session has ended. Start the lab, save new credentials (step 1), run the command again.
- The worker queue triggers are off after a new lab session: `deploy:prod` turns them back on. Without a deploy, run `mise run stack:workers bonbon-prod`.
