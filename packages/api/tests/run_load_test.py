"""Local receipt-pipeline load test; no AWS clients or resources are used."""

import argparse
import json
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID

from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
from bonbon.handlers import process_receipt, process_result
from bonbon.receipts import categories, storage
from fakes import FakeDatabase

DATA = Path(__file__).parent / "data"
RECEIPTS = 200
MAX_CONCURRENCY = 10
HOUSEHOLD_ID = UUID(int=1)


def non_negative_float(value: str) -> float:
    delay = float(value)
    if not math.isfinite(delay) or delay < 0:
        raise argparse.ArgumentTypeError("delay must be a finite number zero or greater")
    return delay


class MockTextract:
    def __init__(self, result: dict[str, Any], delay: float) -> None:
        self.result = result
        self.delay = delay
        self._lock = threading.Lock()
        self._active = 0
        self.max_active = 0

    def analyze_expense(self, **_: Any) -> dict[str, Any]:
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        try:
            time.sleep(self.delay)
            return self.result
        finally:
            with self._lock:
                self._active -= 1


def percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def sqs_record(body: str) -> SQSRecord:
    return SQSRecord(
        {
            "messageId": "local-load-test",
            "receiptHandle": "local-load-test",
            "body": body,
            "attributes": {"ApproximateReceiveCount": "1"},
            "messageAttributes": {},
            "md5OfBody": "",
            "eventSource": "aws:sqs",
            "eventSourceARN": "arn:aws:sqs:us-east-1:000000000000:local-load-test",
            "awsRegion": "us-east-1",
        }
    )


def run_load_test(delay: float) -> int:
    result = json.loads((DATA / "textract_migros.json").read_text())
    database = FakeDatabase()
    textract = MockTextract(result, delay)
    lock = threading.Lock()
    images: dict[str, bytes] = {}
    textract_results: dict[str, bytes] = {}
    result_messages: dict[str, str] = {}

    for index in range(RECEIPTS):
        receipt_id = database.add_receipt(HOUSEHOLD_ID, None)
        key = storage.receipt_key(str(HOUSEHOLD_ID), str(receipt_id))
        images[key] = f"synthetic-receipt-{index}".encode()

    def read_object(key: str) -> bytes:
        with lock:
            return images[key]

    def put_json(key: str, data: bytes) -> None:
        with lock:
            textract_results[key] = data

    def read_json(key: str) -> dict[str, Any]:
        with lock:
            return json.loads(textract_results[key])

    def send_result(message: Any) -> None:
        with lock:
            result_messages[str(message.receipt_id)] = message.model_dump_json()

    def process(receipt_id: UUID, arrival: float) -> tuple[float, str, str | None]:
        key = storage.receipt_key(str(HOUSEHOLD_ID), str(receipt_id))
        image_size = len(images[key])
        s3_event = {
            "Records": [
                {
                    "eventName": "ObjectCreated:Put",
                    "s3": {
                        "bucket": {"name": "local-test"},
                        "object": {"key": key, "size": image_size},
                    },
                }
            ]
        }
        try:
            process_receipt.process_record(sqs_record(json.dumps(s3_event)))
            message = result_messages[str(receipt_id)]
            process_result.process_record(sqs_record(message))
            status = database.receipts[receipt_id].status
            return time.perf_counter() - arrival, status, None
        except Exception as exc:
            return time.perf_counter() - arrival, "error", str(exc)

    started = time.perf_counter()
    completion_times: list[float] = []
    outcomes: list[tuple[str, str | None]] = []
    with (
        patch.object(process_receipt, "_textract", return_value=textract),
        patch.object(process_receipt, "_send", side_effect=send_result),
        patch.object(storage, "read_object", side_effect=read_object),
        patch.object(storage, "put_json", side_effect=put_json),
        patch.object(storage, "read_json", side_effect=read_json),
        patch.object(storage, "remove_pending_tag"),
        patch.object(
            process_result.repo, "finish_extracted", side_effect=database.finish_extracted
        ),
        patch.object(process_result.repo, "finish_failed", side_effect=database.finish_failed),
        patch.object(categories, "_rules", return_value=[]),
        patch.object(process_receipt.logger, "info"),
        patch.object(process_result.logger, "info"),
        ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as executor,
    ):
        futures = []
        for receipt_id in database.receipts:
            futures.append(executor.submit(process, receipt_id, time.perf_counter()))
        for future in futures:
            elapsed, status, error = future.result()
            completion_times.append(elapsed)
            outcomes.append((status, error))
    duration = time.perf_counter() - started

    succeeded = sum(status == "done" for status, _ in outcomes)
    failed = RECEIPTS - succeeded
    failure_rate = failed / RECEIPTS * 100
    throughput = succeeded / duration if duration else 0
    p95 = percentile_95(completion_times) if completion_times else 0

    print("Bonbon - lokaler Lasttest (Textract gemockt)")
    print(f"Belege:                 {RECEIPTS}")
    print(f"Textract-Verzögerung:   {delay:.2f} s")
    print(f"Max. Nebenläufigkeit:   {textract.max_active}/{MAX_CONCURRENCY}")
    print(f"Erfolgreich:            {succeeded}/{RECEIPTS}")
    print(f"Fehlerrate:             {failure_rate:.2f} %")
    print(f"Gesamtdauer:            {duration:.2f} s")
    print(f"Durchsatz:              {throughput:.2f} Belege/s")
    print(f"p95-Verarbeitungszeit:  {p95:.2f} s (inkl. lokaler Wartezeit)")

    errors = [error for _, error in outcomes if error]
    for error in errors[:3]:
        print(f"Fehler: {error}")
    if len(errors) > 3:
        print(f"... und {len(errors) - 3} weitere Fehler")

    return 0 if failed == 0 and textract.max_active <= MAX_CONCURRENCY else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--delay",
        type=non_negative_float,
        default=os.environ.get("BONBON_TEXTRACT_DELAY_SECONDS", "3.3"),
        help="simulated AnalyzeExpense duration in seconds (default: 3.3)",
    )
    args = parser.parse_args()
    return run_load_test(args.delay)


if __name__ == "__main__":
    raise SystemExit(main())
