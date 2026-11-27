# AWS E2E receipt load test

The E2E runner was added for [issue #35](https://github.com/timonrieger/bonbon/issues/35).
It exercises the client-to-AWS path: create a receipt with an API `POST`, upload its PNG using
the returned presigned S3 `PUT`, then poll receipt status until processing is observed or the
configured deadline is reached. Processing depends on the deployed Textract mock; without a
verified mock, this runner cannot validate the deployed processing path.

This is separate from [`mise run load-test`](../features/01-upload-processing.md),
which runs local worker code with in-memory S3/SQS and a fake database. The E2E runner does not
assess OCR accuracy: its synthetic PNGs are test inputs, not an OCR-quality dataset.

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
| `--concurrency N` | Maximum concurrent upload attempts. |
| `--acceptance-timeout N` | Acceptance window in seconds. |
| `--processing-timeout N` | Status-monitor deadline in seconds (default: 180). |
| `--poll-interval N` | Status polling interval in seconds (default: 1). |
| `--request-timeout N` | Per-request timeout in seconds (default: 10). |
| `--run-id ID` | Optional run identifier; otherwise generated locally. |
| `--household-id UUID` | Target household; live use only. |
| `--api-url URL` | API base URL; live use only. |
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
| Peak | 200 | 4/s | 10 | 60 s | 180 s |

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

The technical gate for a real AWS run is currently **closed**. The runner cannot establish that
the selected stack is `bonbon-dev` or that its deployed Textract mock is active, so `--dry-run`
is the only supported run mode for now. `--confirm-start` does not bypass this gate. No live AWS
measurements have been collected.

Before a future coordinated AWS smoke test, the team must:

1. Technically verify the `bonbon-dev` stack and the actually deployed Textract mock.
2. Use a dedicated test household.
3. Decide on a secure process to obtain and provide a Cognito ID token.
4. Confirm the receipt-list endpoint returns every relevant test receipt.
5. Check available AWS permissions and the Learner Lab budget.
6. Coordinate and review an AWS smoke test before any larger run.

The dev/mock verification mechanism is not implemented yet. Do not treat a configured URL,
manual confirmation, or a passing dry run as evidence that the live target is safe.

## Known limitations

- No real AWS E2E measurements or dev/mock verification yet.
- Configurable workload limits have not been added; technical upper bounds must be reviewed
  before the live safety gate can be opened.
- Verification of the dedicated test household remains outstanding.
- The monitor does not end early when every planned receipt is definitively known not to have
  uploaded; consider this only if actual use shows a need.
- The API does not expose `processed_at`; E2E duration ends at the first observed `done`.
- CloudWatch dashboard and DLQ evaluation are outstanding.
- Dry Run flags a Smoke profile with a non-standard receipt count as unsuitable; a programmatically
  constructed report can still evaluate its functional check for that count. This existing
  difference is retained rather than changing report behavior in this phase.
