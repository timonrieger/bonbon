# 0008 Frontend on Amplify Hosting instead of S3 + CloudFront

**Status:** accepted · Deviates from the proposal (chapter 2, «Frontend-Hosting: Amazon S3 + CloudFront»)

## Context

The proposal serves the React app from a private S3 bucket through CloudFront. In the Learner Lab every CloudFront call is denied ("no identity-based policy allows"), for our own session (`voclabs`) and for `LabRole`, so a CloudFormation service role or a Lambda custom resource doesn't help either. Tested on 2026-11-17: `CreateOriginAccessControl`, `CreateCloudFrontOriginAccessIdentity`, `CreateDistribution` and even `ListDistributions`.

Without CloudFront, plain S3 is the only other place for static files, and it falls short. The S3 website endpoint is HTTP only and needs a public bucket. The S3 REST endpoint has HTTPS but also needs a public bucket, and it has no fallback to `index.html` for client-side routes.

Amplify Hosting works in the Learner Lab, including through CloudFormation (`AWS::Amplify::App`, `AWS::Amplify::Branch`).

## Decision

- The prod stack has an Amplify app (`WebApp`) with one branch `main`. Dev stacks have none; there the app runs on `localhost:5173`.
- `mise run deploy:web` builds `packages/web` against the prod stack and uploads `dist/` as a zip (manual deploy). Amplify never connects to GitHub, so it needs no service role and no token.
- A rewrite rule serves `index.html` with status 200 for every path without a file extension, so `BrowserRouter` deep links survive a reload.
- CORS allows only `https://main.<app>.amplifyapp.com` on prod.

## Consequences

- HTTPS, no public bucket, and deep links work. This meets the goal of the proposal's «S3 + CloudFront», with a different service.
- Amplify runs on CloudFront internally, but AWS manages that part. We don't configure caching or security headers ourselves.
- Free tier and Learner Lab budget: hosting a few MB costs cents.
- The final report must name the deviation and the reason (Learner Lab restriction).
