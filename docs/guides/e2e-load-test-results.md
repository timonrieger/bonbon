# AWS E2E load-test results

Results for issue #35, collected on 27 November 2026 against `bonbon-dev` in `us-east-1`.
The Textract mock was enabled with a 3300 ms delay. The Receipt Worker and Result Worker each
had reserved concurrency 10.

## Run summary

The runner-generated JSON reports are the source for receipt counts, elapsed times, and API/E2E
percentiles below. API p95 is calculated from requests with measurable latency in the report's
acceptance window; the sample count is shown in parentheses. E2E p95 uses the confirmed-upload to
first-observed-`done` measurements. Times are elapsed from run start.

| Metric | Smoke | Normal | Peak 01 | Peak 02 | Peak 03 |
|---|---:|---:|---:|---:|---:|
| Receipts planned | 3 | 20 | 200 | 200 | 200 |
| Runner concurrency | 1 | 5 | 10 | 15 | 15 |
| `ReceiptsFunction` reserved concurrency* | 10 | 10 | 10 | 10 | 20 |
| Confirmed S3 uploads | 3 | 20 | 199 | 196 | 200 |
| Confirmed within 60 seconds | 3 | 20 | 190 | 196 | 200 |
| Successfully processed (`done` observed) | 3 | 20 | 199 | 196 | 200 |
| Last confirmed upload (s) | 8.70 | 22.79 | 63.45 | 59.73 | 52.07 |
| Last `done` observed (s) | 15.82 | 28.40 | 90.57 | 89.99 | 88.24 |
| API p95 (s; sample count) | 0.897 (16) | 0.364 (44) | 0.387 (248) | 2.236 (240) | 0.519 (241) |
| E2E p95 (s; sample count) | 9.66 (3) | 6.96 (20) | 38.18 (199) | 36.84 (196) | 43.50 (200) |

*The runner JSON records its own concurrency setting, not the deployed API Lambda's reserved
concurrency. Those API values are from the deployment/test records: the dev `ReceiptsFunction`
was raised from 10 to 20 before Peak 03; production remained unchanged.

## Acceptance criteria

- **Smoke:** all 3 receipts were uploaded and observed as processed.
- **Normal:** E2E p95 was 6.96 s, meeting the 10 s target.
- **Peak 01:** API p95 passed at 0.387 s, but upload throughput failed (190/200 within 60 s)
  and only 199/200 were processed.
- **Peak 02:** all 196 confirmed uploads were within 60 s, but the 200-upload target failed;
  API p95 failed at 2.236 s. The processing assessment was `INCONCLUSIVE` with 196/200
  processed.
- **Peak 03:** all three automatic Peak performance criteria passed: 200/200 confirmed uploads
  within 60 s, 200/200 processed within 180 s, and API p95 below 1 s. The runner still exited
  non-zero because its separate DLQ/Textract-throttling criterion is `NOT_EVALUATED`.

## Peak investigation and changes

**Peak 01** recorded one S3 network error with an uncertain outcome and nine confirmed uploads
after the 60-second window. After this run, runner concurrency was raised from 10 to 15 for Peak.

**Peak 02** had no S3 errors or late confirmed uploads, but recorded four API HTTP 500 responses.
CloudWatch showed four API Gateway 5XX errors and four `ReceiptsFunction` throttles; the function
reached its reserved concurrency of 10. RDS CPU peaked at 8.65%, with at most 13 measured
connections. API Lambda throttling is the most likely cause of the 500s, but there is no
request-level correlation proving that attribution. Before Peak 03, only the dev
`ReceiptsFunction` reserved concurrency was raised from 10 to 20; production and both processing
workers remained at 10.

**Peak 03** had no API or S3 errors. No API Lambda errors or throttles appeared in the available
CloudWatch measurement points, but the maximum measured API concurrency was only 2. The result
therefore does not establish that the higher reserved concurrency caused the improvement. The
Receipt queue reached approximately 59 visible messages, with the oldest around 25 seconds, and
was subsequently drained. RDS CPU peaked at 8.46%, with at most 10 measured connections; minimum
FreeableMemory was approximately 131.5 MiB and 288 CPU credits were reported.

## DLQ and Textract observations

Both DLQs were checked separately using AWS CLI/CloudWatch data for approximately 08:50–09:36 UTC.
Each had 46 historical CloudWatch data points and a maximum of zero visible messages. At the
check, visible, not-visible, and delayed message counts were all zero.

This is a DLQ check under the Textract mock, not evidence about real Textract quotas or throttling.
The mock models processing delay but does not call Textract or simulate its service quota. The
runner's DLQ criterion remains `NOT_EVALUATED`; the separate empty-DLQ observation is limited to
the inspected test window.

## Limitations

- The tests used mocked Textract; real Textract calls and throttling were not exercised.
- E2E latency includes polling and API response delay; it is an observation interval, not exact
  server-side processing time.
- The dedicated test household accumulated data between runs, so later runs did not use an
  identical household state.
- Peak 03 had 36 missing receipt-list observations, while all 200 terminal statuses and all 200
  E2E measurements were present in its report.
- CloudWatch metrics are time-aggregated. Missing data points are not equivalent to zero.
- Normal was run before the final API concurrency configuration change.
- Peak 03 is one successful run, not statistical evidence of sustained reliability.
- A passing set of Peak performance criteria does not change the runner's non-zero exit while its
  DLQ/Textract-throttling assessment is `NOT_EVALUATED`.

The original JSON reports remain outside the repository and have not been copied here.
