# AWS E2E receipt load test

The E2E runner was added for [issue #35](https://github.com/timonrieger/bonbon/issues/35).
It exercises the client-to-AWS path: create a receipt with an API `POST`, upload its PNG using
the returned presigned S3 `PUT`, then poll receipt status until processing is observed or the
configured deadline is reached. Processing depends on the deployed Textract mock; without a
verified mock, this runner cannot validate the deployed processing path.

This is separate from [`mise run load-test`](../features/01-upload-processing.md),
which runs local worker code with in-memory S3/SQS and a fake database. The E2E runner does not
assess OCR accuracy: its synthetic PNGs are test inputs, not an OCR-quality dataset.
Results from the completed AWS runs, including their acceptance criteria and limitations, are
summarized in [E2E load-test results](./e2e-load-test-results.md).

## Safe local use

Run these commands from the repository root. Help and dry runs do not request a token or make
network or AWS calls:

```sh
mise run load-test:e2e --help
mise run load-test:e2e --dry-run --profile smoke
mise run load-test:e2e --dry-run --profile normal
mise run load-test:e2e --dry-run --profile peak
```

`--output PATH` optionally writes the JSON plan or report to a new file; the path must not
already exist. The runner's available options are:

| Option | Meaning |
|---|---|
| `--profile smoke`, `normal`, or `peak` | Select a test configuration. Required for live mode; dry run defaults to Normal. |
| `--count N` | Receipt count. Normal may be adjusted; Smoke and Peak profiles are fixed. |
| `--rate N` | Planned API-POST start rate in starts per second. |
| `--concurrency N` | Maximum concurrent upload attempts; Peak accepts 10-15 (default 10), other profiles are fixed. |
| `--acceptance-timeout N` | Acceptance window in seconds. |
| `--processing-timeout N` | Status-monitor deadline in seconds (default: 180). |
| `--poll-interval N` | Status polling interval in seconds (default: 1). |
| `--request-timeout N` | Per-request timeout in seconds (default: 10). |
| `--run-id ID` | Optional run identifier; otherwise generated locally. |
| `--household-id UUID` | Target household; live use only. |
| `--api-url URL` | API base URL; live use only. |
| `--token-stdin` | Read one Cognito ID-token JWT from stdin instead of prompting; live use only. |
| `--output PATH` | Write JSON to a new file. |
| `--dry-run` | Print a local plan without requesting credentials or performing measurements. |
| `--confirm-start` | Explicit consent flag; does not override the technical safety gate. |

Exit codes: `0` success (or a completed dry run), `1` quality targets not met, `2` invalid
configuration, `3` safety gate blocked the run, and `4` execution or output-file error. Help exits
with `0`; argparse usage errors use its standard non-zero exit.

## Test configurations

These are configured workloads, not demonstrated AWS performance:

| Profile | Receipts | Planned starts | Max concurrency | Acceptance window | Processing target |
|---|---:|---:|---:|---:|---:|
| Smoke | 3 | 1/s | 1 | 60 s | Configured monitor timeout |
| Normal | 20 (provisional) | 1/s | 5 | 60 s | Configured monitor timeout |
| Peak | 200 | 4/s | 10 (default; up to 15) | 60 s | 180 s |

Live mode only accepts these workload settings; Peak concurrency may be explicitly raised from 10
to at most 15. All other counts, rates, time limits and profile settings remain fixed. Polling must
remain at one request per second, request timeout is capped at 10 seconds, and monitoring is capped
at 180 seconds (Peak requires exactly 180 seconds). Dry runs may still explore other values, but
those plans are not eligible for live execution.

The local start rate controls client-side API `POST` starts, not server-side Textract calls.
Uploads are asynchronous and pass through the queue and workers, so the two rates are not
equivalent.

## Measurements and quality goals

- An upload is confirmed only after a successful S3 `PUT` response. A receipt created by the API
  or an unconfirmed/uncertain `PUT` is not counted as a confirmed upload.
- API request latency and S3 `PUT` latency are reported separately. Missing or invalid timing
  data stays unavailable; the runner does not invent a measurement or turn an uncertain upload
  into a confirmed one.
- Percentiles use nearest rank: sort the samples and select
  `sorted_samples[ceil(0.95 * n) - 1]` for p95.
- Observed E2E latency is the first observed `done` status minus confirmed S3 `PUT` completion.
  It includes status-polling and API response delay; therefore it is an observation interval,
  not the exact server-side processing duration. `processed_at` is not exposed by the API.
- A status can only be observed when polling sees it. Poll intervals, request latency, and
  missing responses can delay or prevent observations.

The report evaluates these targets:

- Normal E2E p95 at most 10 seconds.
- All 200 S3 uploads confirmed within 60 seconds.
- All 200 receipts observed as successfully processed within 180 seconds.
- API p95 strictly below one second during the peak window.
- No DLQ entries caused by Textract throttling. This requires a separate CloudWatch inspection;
  the runner reports this target as `NOT_EVALUATED`.

These are target thresholds, not claims about measured or achieved AWS performance.

## Safety gate and prerequisites

Every live run requires `--confirm-start` and performs read-only AWS CLI checks before asking for
the Cognito ID token. It verifies the `bonbon-dev` stack in `us-east-1`, `Stage=dev`,
`UPDATE_COMPLETE`, and an exact match between `--api-url` and the stack's `ApiUrl` output. It
resolves the receipt worker's physical function name from the CloudFormation logical resource and
checks that the deployed function is `Active`, its last update is `Successful`, and its
`STAGE=dev`, `TEXTRACT_MOCK=1`, and `TEXTRACT_MOCK_DELAY_MS=3300` settings match. Any AWS CLI
error, missing field, timeout, or mismatch blocks the run without printing AWS output or
environment variables. The local verification uses only read operations; no deployment or
configuration changes are made.

The operator needs an installed, authenticated AWS CLI with permission to call
`cloudformation:DescribeStacks`, `cloudformation:DescribeStackResources`, and
`lambda:GetFunctionConfiguration`. These permissions are not established by local tests.

Create a dedicated household named exactly `BONBON-E2E-LOAD-TEST` and pass its generated UUID as
`--household-id`. After the AWS checks and token prompt, the runner uses authenticated
`GET /households` to require an exact ID/name match and `my_role=owner`, then calls
`GET /households/{household_id}/members` and requires exactly one member. Any API error, malformed
response, or mismatch blocks live mode before uploads. Keep the household for test data only.
These preflight requests use a separate client and are excluded from load-test measurements.

For WSL, set `API_URL` to the verified dev stack output and `HOUSEHOLD_ID` to the dedicated
household UUID, then paste the ID token into the Windows clipboard:

```sh
powershell.exe -NoProfile -Command 'Get-Clipboard -Raw' |
  mise run load-test:e2e --profile smoke --confirm-start \
    --api-url "$API_URL" --household-id "$HOUSEHOLD_ID" --token-stdin
```

The runner trims surrounding whitespace and rejects empty or malformed JWT input. It never echoes
the token; default mode still prompts with `getpass`.

The explicit confirmation flag is still mandatory and cannot bypass either technical check.
Dry-run and help modes remain offline and do not invoke the AWS CLI or request a token. No live
load test is run by automated tests; AWS CLI responses are mocked.

## Known limitations

- The recorded results are historical; the deployed stack configuration must be checked again by
  the gate for every live run.
- The monitor does not end early when every planned receipt is definitively known not to have
  uploaded; consider this only if actual use shows a need.
- The API does not expose `processed_at`; E2E duration ends at the first observed `done`.
- DLQ/Textract-throttling evaluation remains manual; Lambda throttles and an empty DLQ do not prove
  that Textract was not throttled.
- Dry Run flags a Smoke profile with a non-standard receipt count as unsuitable; a programmatically
  constructed report can still evaluate its functional check for that count. This existing
  difference is retained rather than changing report behavior in this phase.
