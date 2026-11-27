"""HTTP client, synthetic receipt, and load-control primitives for E2E tests."""

import argparse
import getpass
import hashlib
import http.client
import json
import math
import re
import socket
import struct
import sys
import threading
import time
import unicodedata
import urllib.request
import zlib
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from statistics import median
from types import MappingProxyType
from typing import Literal, Protocol, TypeGuard
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request
from uuid import UUID, uuid4

from bonbon.receipts.models import (
    MAX_UPLOAD_BYTES,
    CreateReceiptRequest,
    ReceiptList,
    ReceiptStatus,
    ReceiptSummary,
    UploadContentType,
)
from bonbon.receipts.models import (
    ReceiptUpload as ReceiptUploadResponse,
)
from pydantic import ValidationError

RequestKind = Literal["api", "s3"]
TestProfile = Literal["smoke_test", "normal_load", "peak_load"]
AssessmentStatus = Literal["PASS", "FAIL", "NOT_EVALUATED", "INCONCLUSIVE"]
_HEADER_NAME_PATTERN = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")


class E2ELoadTestError(Exception):
    """Base error with no request URL, credentials, or response body."""


class ClientInputError(E2ELoadTestError):
    """The client was given invalid input or configuration."""


class InvalidResponseError(E2ELoadTestError):
    """The server returned a response that does not match the backend schema."""


class RequestTimeoutError(E2ELoadTestError):
    def __init__(self) -> None:
        super().__init__("HTTP request timed out.")


class NetworkRequestError(E2ELoadTestError):
    def __init__(self) -> None:
        super().__init__("HTTP request failed due to a network error.")


class HttpStatusError(E2ELoadTestError):
    def __init__(self, kind: RequestKind, method: str, status_code: int) -> None:
        self.kind = kind
        self.method = method
        self.status_code = status_code
        super().__init__(f"{kind.upper()} {method} returned HTTP {status_code}.")


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: bytes = field(repr=False)


class HttpTransport(Protocol):
    def send(self, request: Request, timeout: float) -> HttpResponse: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


class UrllibTransport:
    """Standard-library transport that treats redirects as responses, never follows them."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(_NoRedirectHandler())

    def send(self, request: Request, timeout: float) -> HttpResponse:
        try:
            with self._opener.open(request, timeout=timeout) as response:
                return HttpResponse(response.status, response.read())
        except TimeoutError:
            raise RequestTimeoutError() from None
        except HTTPError as error:
            status_code = error.code
            try:
                error.close()
            except TimeoutError:
                raise RequestTimeoutError() from None
            except http.client.HTTPException, OSError:
                raise NetworkRequestError() from None
            return HttpResponse(status_code, b"")
        except URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                raise RequestTimeoutError() from None
            raise NetworkRequestError() from None
        except http.client.HTTPException, OSError:
            raise NetworkRequestError() from None


@dataclass(frozen=True)
class RequestTiming:
    kind: RequestKind
    method: str
    elapsed_seconds: float
    status_code: int | None
    started_at: float | None = None
    completed_at: float | None = None
    error_category: str | None = None


@dataclass(frozen=True)
class ReceiptUploadGrant:
    receipt_id: str
    size_bytes: int
    expires_in: int
    upload_url: str = field(repr=False)
    upload_headers: Mapping[str, str] = field(repr=False)


@dataclass(frozen=True)
class GeneratedTestReceipt:
    index: int
    file_bytes: bytes = field(repr=False)
    content_type: str
    size_bytes: int
    sha256: str


def _encode_test_run_id(run_id: str) -> bytes:
    if not isinstance(run_id, str) or not run_id.strip():
        raise ClientInputError("A non-empty test run ID is required.")
    try:
        run_id_bytes = run_id.encode("utf-8")
    except UnicodeEncodeError:
        raise ClientInputError("Test run ID must be valid UTF-8.") from None
    if len(run_id_bytes) > 256:
        raise ClientInputError("Test run ID must be at most 256 UTF-8 bytes.")
    return run_id_bytes


def _is_finite_number(value: object) -> TypeGuard[int | float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _is_upload_content_type(value: str) -> TypeGuard[UploadContentType]:
    return value in ("image/jpeg", "image/png", "application/pdf")


@dataclass(frozen=True)
class E2ELoadTestConfig:
    receipt_count: int
    max_concurrency: int
    starts_per_second: float
    acceptance_window_seconds: float
    run_id: str
    profile: TestProfile = "normal_load"

    def __post_init__(self) -> None:
        _encode_test_run_id(self.run_id)
        if self.profile not in ("smoke_test", "normal_load", "peak_load"):
            raise ClientInputError("Test profile is invalid.")
        if type(self.receipt_count) is not int or self.receipt_count <= 0:
            raise ClientInputError("Receipt count must be a positive integer.")
        if type(self.max_concurrency) is not int or self.max_concurrency <= 0:
            raise ClientInputError("Maximum concurrency must be a positive integer.")
        for value, name in (
            (self.starts_per_second, "Upload start rate"),
            (self.acceptance_window_seconds, "Acceptance window"),
        ):
            if not _is_finite_number(value) or value <= 0:
                raise ClientInputError(f"{name} must be finite and positive.")
        try:
            interval = 1.0 / self.starts_per_second
            schedule_span = (self.receipt_count - 1) * interval
        except OverflowError, ZeroDivisionError:
            raise ClientInputError("Upload schedule duration must be finite.") from None
        if not _is_finite_number(interval) or not _is_finite_number(schedule_span):
            raise ClientInputError("Upload schedule duration must be finite.")

    @classmethod
    def smoke_test(cls, run_id: str) -> E2ELoadTestConfig:
        return cls(3, 1, 1.0, 60.0, run_id, "smoke_test")

    @classmethod
    def normal_load(
        cls,
        run_id: str,
        *,
        receipt_count: int,
        max_concurrency: int,
        starts_per_second: float,
        acceptance_window_seconds: float,
    ) -> E2ELoadTestConfig:
        return cls(
            receipt_count,
            max_concurrency,
            starts_per_second,
            acceptance_window_seconds,
            run_id,
            "normal_load",
        )

    @classmethod
    def peak_load(cls, run_id: str) -> E2ELoadTestConfig:
        return cls(200, 10, 4.0, 60.0, run_id, "peak_load")


@dataclass(frozen=True)
class UploadAttemptResult:
    index: int
    sha256: str
    size_bytes: int
    receipt_id: str | None
    planned_start_at: float
    actual_start_at: float | None
    s3_completed_at: float | None
    finished_at: float | None
    upload_succeeded: bool
    failure_category: str | None
    error_message: str | None = field(default=None, repr=False)
    outcome_uncertain: bool = False
    completed_after_deadline: bool = False
    http_status_code: int | None = None


class ReceiptUploadClient(Protocol):
    def create_receipt(
        self, household_id: str, content_type: str, file_bytes: bytes
    ) -> ReceiptUploadGrant: ...

    def upload_file(self, grant: ReceiptUploadGrant, file_bytes: bytes) -> None: ...


class ReceiptMonitoringClient(ReceiptUploadClient, Protocol):
    def list_receipts(self, household_id: str) -> dict[str, ReceiptSummary]: ...


class E2ELoadTestClient(ReceiptMonitoringClient, Protocol):
    @property
    def timings(self) -> tuple[RequestTiming, ...]: ...


@dataclass(frozen=True)
class ReceiptStatusObservation:
    status: ReceiptStatus
    observed_at: float
    observed_after_deadline: bool


@dataclass(frozen=True)
class ReceiptStatusConflict:
    first_terminal_status: ReceiptStatus
    later_status: ReceiptStatus
    observed_at: float


@dataclass(frozen=True)
class PollingErrorObservation:
    category: str
    occurred_at: float
    http_status: int | None
    fatal: bool
    message: str = field(repr=False)


@dataclass(frozen=True)
class UploadLinkageError:
    index: int
    registered_receipt_id: str
    result_receipt_id: str | None


@dataclass(frozen=True)
class ReceiptMonitoringRecord:
    index: int
    receipt_id: str
    registered_at: float
    registered_after_deadline: bool
    last_nonterminal_status: ReceiptStatus | None
    last_nonterminal_observed_at: float | None
    first_terminal_status: ReceiptStatus | None
    first_terminal_observed_at: float | None
    status_observations: tuple[ReceiptStatusObservation, ...]
    status_conflicts: tuple[ReceiptStatusConflict, ...]
    missing_response_count: int
    last_missing_response_at: float | None
    upload_result: UploadAttemptResult | None
    monitoring_outcome: str
    terminal_observed_before_s3_confirmation: bool
    terminal_observed_after_deadline: bool


@dataclass
class _MutableReceiptMonitoringRecord:
    index: int
    receipt_id: str
    registered_at: float
    registered_after_deadline: bool
    last_nonterminal_status: ReceiptStatus | None = None
    last_nonterminal_observed_at: float | None = None
    first_terminal_status: ReceiptStatus | None = None
    first_terminal_observed_at: float | None = None
    status_observations: list[ReceiptStatusObservation] = field(default_factory=list)
    status_conflicts: list[ReceiptStatusConflict] = field(default_factory=list)
    missing_response_count: int = 0
    last_missing_response_at: float | None = None
    upload_result: UploadAttemptResult | None = None


class ReceiptStatusMonitor:
    """Poll the shared receipt list while a load run is uploading and processing."""

    def __init__(
        self,
        http_client: ReceiptMonitoringClient,
        household_id: str,
        *,
        poll_interval_seconds: float = 1.0,
        processing_timeout_seconds: float = 180.0,
        clock: Callable[[], float] = time.perf_counter,
        wait: Callable[[threading.Event, float], bool] | None = None,
    ) -> None:
        if not household_id:
            raise ClientInputError("A household ID is required.")
        if not _is_finite_number(poll_interval_seconds) or poll_interval_seconds <= 0:
            raise ClientInputError("Polling interval must be finite and positive.")
        if not _is_finite_number(processing_timeout_seconds) or processing_timeout_seconds <= 0:
            raise ClientInputError("Processing timeout must be finite and positive.")

        self._http_client = http_client
        self.household_id = household_id
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.processing_timeout_seconds = float(processing_timeout_seconds)
        self._clock = clock
        self._wait = wait or (lambda event, timeout: event.wait(timeout))
        self._lock = threading.Lock()
        self._wake_event = threading.Event()
        self._records: dict[str, _MutableReceiptMonitoringRecord] = {}
        self._records_by_index: dict[int, _MutableReceiptMonitoringRecord] = {}
        self._upload_results: dict[int, UploadAttemptResult] = {}
        self._polling_errors: list[PollingErrorObservation] = []
        self._linkage_errors: list[UploadLinkageError] = []
        self._run_started_at: float | None = None
        self._processing_deadline_at: float | None = None
        self._finished_at: float | None = None
        self._upload_phase_complete = False
        self._stop_requested = False
        self._polling_error_category: str | None = None
        self._stop_reason: str | None = None
        self._unexpected_error: Exception | None = None
        self._thread: threading.Thread | None = None

    @property
    def processing_deadline_at(self) -> float | None:
        with self._lock:
            return self._processing_deadline_at

    @property
    def run_started_at(self) -> float | None:
        with self._lock:
            return self._run_started_at

    @property
    def finished_at(self) -> float | None:
        with self._lock:
            return self._finished_at

    @property
    def polling_errors(self) -> tuple[PollingErrorObservation, ...]:
        with self._lock:
            return tuple(self._polling_errors)

    @property
    def linkage_errors(self) -> tuple[UploadLinkageError, ...]:
        with self._lock:
            return tuple(self._linkage_errors)

    @property
    def polling_error_category(self) -> str | None:
        with self._lock:
            return self._polling_error_category

    @property
    def stop_reason(self) -> str | None:
        with self._lock:
            return self._stop_reason

    @property
    def thread_is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        run_started_at: float,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not _is_finite_number(run_started_at):
            raise ClientInputError("Load-test start time must be finite.")
        deadline = run_started_at + self.processing_timeout_seconds
        if not _is_finite_number(deadline):
            raise ClientInputError("Processing deadline must be finite.")
        with self._lock:
            if self._thread is not None:
                raise RuntimeError("Receipt status monitor can only be started once.")
            if clock is not None:
                self._clock = clock
            self._run_started_at = run_started_at
            self._processing_deadline_at = deadline
            for record in self._records.values():
                record.registered_after_deadline = record.registered_at >= deadline
            self._thread = threading.Thread(
                target=self._thread_entry,
                name="e2e-receipt-status-monitor",
            )
            thread = self._thread
        thread.start()

    def register_receipt(self, index: int, receipt_id: str) -> None:
        if type(index) is not int or index < 0 or not receipt_id:
            raise ClientInputError("Receipt registration is invalid.")
        now = self._clock()
        with self._lock:
            existing = self._records.get(receipt_id)
            if existing is not None:
                if existing.index != index:
                    raise ClientInputError("Receipt ID was registered for multiple uploads.")
                return
            indexed = self._records_by_index.get(index)
            if indexed is not None and indexed.receipt_id != receipt_id:
                raise ClientInputError("Upload index was registered with multiple receipt IDs.")
            deadline = self._processing_deadline_at
            record = _MutableReceiptMonitoringRecord(
                index=index,
                receipt_id=receipt_id,
                registered_at=now,
                registered_after_deadline=deadline is not None and now >= deadline,
            )
            self._records[receipt_id] = record
            self._records_by_index[index] = record
            upload_result = self._upload_results.get(index)
            if upload_result is not None:
                self._link_upload_result_locked(record, upload_result)
        self._wake_event.set()

    def attach_upload_result(self, result: UploadAttemptResult) -> None:
        with self._lock:
            existing = self._upload_results.get(result.index)
            if existing is not None and existing != result:
                record = self._records_by_index.get(result.index)
                self._linkage_errors.append(
                    UploadLinkageError(
                        result.index,
                        record.receipt_id if record is not None else "",
                        result.receipt_id,
                    )
                )
                return
            self._upload_results[result.index] = result
            record = self._records_by_index.get(result.index)
            if record is not None:
                self._link_upload_result_locked(record, result)
        self._wake_event.set()

    def finish_upload_phase(self, results: Sequence[UploadAttemptResult]) -> None:
        for result in results:
            self.attach_upload_result(result)
        with self._lock:
            if self._upload_phase_complete:
                raise RuntimeError("Upload phase was already marked complete.")
            self._upload_phase_complete = True
        self._wake_event.set()

    def stop(self) -> None:
        with self._lock:
            self._stop_requested = True
            if self._stop_reason is None:
                self._stop_reason = "stopped"
        self._wake_event.set()

    def join(self) -> None:
        thread = self._thread
        if thread is None:
            raise RuntimeError("Receipt status monitor has not been started.")
        thread.join()
        if self._unexpected_error is not None:
            raise self._unexpected_error

    def snapshot(self) -> tuple[ReceiptMonitoringRecord, ...]:
        with self._lock:
            return tuple(
                self._snapshot_record(record)
                for record in sorted(self._records.values(), key=lambda item: item.index)
            )

    def _snapshot_record(self, record: _MutableReceiptMonitoringRecord) -> ReceiptMonitoringRecord:
        result = record.upload_result
        terminal_status = record.first_terminal_status
        if terminal_status is not None:
            outcome = terminal_status
        elif self._polling_error_category is not None:
            outcome = "polling_error"
        elif result is None:
            outcome = "upload_pending"
        elif result.failure_category == "deadline" and result.s3_completed_at is None:
            outcome = "s3_not_started"
        elif result.outcome_uncertain:
            outcome = "s3_outcome_uncertain"
        elif not result.upload_succeeded:
            outcome = "s3_upload_failed"
        elif record.last_nonterminal_status == "uploaded":
            outcome = (
                "uploaded_timeout" if self._stop_reason == "processing_deadline" else "uploaded"
            )
        else:
            outcome = "not_observed"

        terminal_at = record.first_terminal_observed_at
        done_before_s3 = (
            terminal_status == "done"
            and terminal_at is not None
            and result is not None
            and result.s3_completed_at is not None
            and terminal_at < result.s3_completed_at
        )
        terminal_after_deadline = (
            terminal_at is not None
            and self._processing_deadline_at is not None
            and terminal_at > self._processing_deadline_at
        )
        return ReceiptMonitoringRecord(
            index=record.index,
            receipt_id=record.receipt_id,
            registered_at=record.registered_at,
            registered_after_deadline=record.registered_after_deadline,
            last_nonterminal_status=record.last_nonterminal_status,
            last_nonterminal_observed_at=record.last_nonterminal_observed_at,
            first_terminal_status=terminal_status,
            first_terminal_observed_at=terminal_at,
            status_observations=tuple(record.status_observations),
            status_conflicts=tuple(record.status_conflicts),
            missing_response_count=record.missing_response_count,
            last_missing_response_at=record.last_missing_response_at,
            upload_result=result,
            monitoring_outcome=outcome,
            terminal_observed_before_s3_confirmation=done_before_s3,
            terminal_observed_after_deadline=terminal_after_deadline,
        )

    def _link_upload_result_locked(
        self,
        record: _MutableReceiptMonitoringRecord,
        result: UploadAttemptResult,
    ) -> None:
        if result.receipt_id != record.receipt_id:
            self._linkage_errors.append(
                UploadLinkageError(
                    record.index,
                    record.receipt_id,
                    result.receipt_id,
                )
            )
            return
        record.upload_result = result

    def _thread_entry(self) -> None:
        try:
            self._poll_loop()
        except Exception as error:
            with self._lock:
                self._unexpected_error = error
                self._stop_reason = "unexpected_error"
        finally:
            finished_at = self._clock()
            with self._lock:
                self._finished_at = finished_at

    def _poll_loop(self) -> None:
        next_poll_at: float | None = None
        while True:
            self._wake_event.clear()
            with self._lock:
                if self._stop_requested or self._polling_error_category is not None:
                    return
                deadline = self._processing_deadline_at
                if deadline is None:
                    raise RuntimeError("Receipt status monitor has no deadline.")
                records = tuple(self._records.values())
                upload_done = self._upload_phase_complete
                all_terminal = all(record.first_terminal_status is not None for record in records)

            now = self._clock()
            if now >= deadline:
                self._set_stop_reason("processing_deadline")
                return
            if upload_done and all_terminal:
                self._set_stop_reason("all_terminal" if records else "no_receipts")
                return
            if not records:
                self._wait(self._wake_event, deadline - now)
                continue
            if next_poll_at is None:
                next_poll_at = now
            if now < next_poll_at:
                self._wait(self._wake_event, min(next_poll_at - now, deadline - now))
                continue
            if self._clock() >= deadline:
                self._set_stop_reason("processing_deadline")
                return

            try:
                receipts = self._http_client.list_receipts(self.household_id)
            except E2ELoadTestError as error:
                observed_at = self._clock()
                fatal = self._record_poll_error(error, observed_at)
                if fatal:
                    return
                next_poll_at = observed_at + self.poll_interval_seconds
                continue

            observed_at = self._clock()
            self._apply_status_response(receipts, observed_at, deadline)
            next_poll_at = observed_at + self.poll_interval_seconds

    def _apply_status_response(
        self,
        receipts: Mapping[str, ReceiptSummary],
        observed_at: float,
        deadline_at: float,
    ) -> None:
        with self._lock:
            for receipt_id, record in self._records.items():
                receipt = receipts.get(receipt_id)
                if receipt is None:
                    record.missing_response_count += 1
                    record.last_missing_response_at = observed_at
                    continue
                status = receipt.status
                observation = ReceiptStatusObservation(
                    status=status,
                    observed_at=observed_at,
                    observed_after_deadline=observed_at > deadline_at,
                )
                record.status_observations.append(observation)
                if status == "uploaded":
                    record.last_nonterminal_status = status
                    record.last_nonterminal_observed_at = observed_at
                    if record.first_terminal_status is not None:
                        record.status_conflicts.append(
                            ReceiptStatusConflict(record.first_terminal_status, status, observed_at)
                        )
                elif record.first_terminal_status is None:
                    record.first_terminal_status = status
                    record.first_terminal_observed_at = observed_at
                elif status != record.first_terminal_status:
                    record.status_conflicts.append(
                        ReceiptStatusConflict(record.first_terminal_status, status, observed_at)
                    )

    def _record_poll_error(self, error: E2ELoadTestError, occurred_at: float) -> bool:
        status_code = error.status_code if isinstance(error, HttpStatusError) else None
        fatal = False
        if isinstance(error, RequestTimeoutError):
            category, message = "timeout", "Receipt status request timed out."
        elif isinstance(error, NetworkRequestError):
            category, message = "network_error", "Receipt status network request failed."
        elif isinstance(error, InvalidResponseError):
            category, message = "invalid_response", "Receipt status response was invalid."
        elif isinstance(error, HttpStatusError):
            if status_code == 401:
                category, message, fatal = (
                    "authentication",
                    "Receipt status request was not authenticated.",
                    True,
                )
            elif status_code == 403:
                category, message, fatal = (
                    "authorization",
                    "Receipt status request was not authorized.",
                    True,
                )
            elif status_code == 429:
                category, message = "rate_limited", "Receipt status request was rate limited."
            elif status_code is not None and 500 <= status_code <= 599:
                category, message = "server_error", "Receipt status service returned an error."
            elif status_code is not None and 400 <= status_code <= 499:
                category, message, fatal = (
                    "http_client_error",
                    "Receipt status request was rejected.",
                    True,
                )
            else:
                category, message = "http_error", "Receipt status request failed."
        elif isinstance(error, ClientInputError):
            category, message, fatal = (
                "client_error",
                "Receipt status request configuration was rejected.",
                True,
            )
        else:
            category, message = "polling_error", "Receipt status request failed."

        with self._lock:
            self._polling_errors.append(
                PollingErrorObservation(
                    category=category,
                    occurred_at=occurred_at,
                    http_status=status_code,
                    fatal=fatal,
                    message=message,
                )
            )
            if fatal:
                self._polling_error_category = category
                self._stop_reason = category
        return fatal

    def _set_stop_reason(self, reason: str) -> None:
        with self._lock:
            if self._stop_reason is None:
                self._stop_reason = reason


def generate_test_receipt(
    run_id: str,
    index: int,
    *,
    width: int = 400,
    height: int = 400,
) -> GeneratedTestReceipt:
    """Generate a deterministic RGB PNG.

    At 400x400, RGB pixels and one filter byte per row make 480,400 raw scanline
    bytes; zlib stored-block framing and PNG chunks bring the file to about 480.5 KB.
    """
    run_id_bytes = _encode_test_run_id(run_id)
    if type(index) is not int or not 0 <= index < 2**64:
        raise ClientInputError("Test receipt index must be a non-negative integer.")
    if (
        type(width) is not int
        or type(height) is not int
        or not 1 <= width <= 0x7FFFFFFF
        or not 1 <= height <= 0x7FFFFFFF
    ):
        raise ClientInputError("PNG dimensions must be positive 32-bit integers.")

    scanline_bytes = width * 3 + 1
    raw_size = scanline_bytes * height
    if raw_size > MAX_UPLOAD_BYTES:
        raise ClientInputError("Generated image dimensions exceed the API upload limit.")

    seed = (
        b"bonbon-e2e-png-v1\0"
        + len(run_id_bytes).to_bytes(4, "big")
        + run_id_bytes
        + index.to_bytes(8, "big")
    )
    pixel_bytes = hashlib.shake_256(seed).digest(width * height * 3)
    scanlines = b"".join(
        b"\0" + pixel_bytes[row * width * 3 : (row + 1) * width * 3] for row in range(height)
    )

    def png_chunk(chunk_type: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(data, zlib.crc32(chunk_type)) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)

    image = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0),
        )
        + png_chunk(b"IDAT", zlib.compress(scanlines, level=0))
        + png_chunk(b"IEND", b"")
    )
    if len(image) > MAX_UPLOAD_BYTES:
        raise ClientInputError("Generated PNG exceeds the API upload limit.")

    return GeneratedTestReceipt(
        index=index,
        file_bytes=image,
        content_type="image/png",
        size_bytes=len(image),
        sha256=hashlib.sha256(image).hexdigest(),
    )


class E2EHttpClient:
    """Small authenticated API and presigned-S3 client; it performs no retries or polling."""

    def __init__(
        self,
        api_base_url: str,
        id_token: str,
        *,
        timeout_seconds: float = 10.0,
        transport: HttpTransport | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._api_base_url = self._validate_api_base_url(api_base_url)
        if not id_token or "\r" in id_token or "\n" in id_token:
            raise ClientInputError("A valid Cognito ID token is required.")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ClientInputError("Request timeout must be a finite positive number.")

        self._id_token = id_token
        self._timeout_seconds = timeout_seconds
        self._transport = transport or UrllibTransport()
        self._clock = clock
        self._timings: list[RequestTiming] = []
        self._timings_lock = threading.Lock()

    @property
    def timings(self) -> tuple[RequestTiming, ...]:
        with self._timings_lock:
            return tuple(self._timings)

    def create_receipt(
        self, household_id: str, content_type: str, file_bytes: bytes
    ) -> ReceiptUploadGrant:
        if not isinstance(file_bytes, bytes):
            raise ClientInputError("Receipt file must be bytes.")
        if not _is_upload_content_type(content_type):
            raise ClientInputError("Receipt content type or size is invalid.")
        try:
            body = (
                CreateReceiptRequest(content_type=content_type, size_bytes=len(file_bytes))
                .model_dump_json()
                .encode("utf-8")
            )
        except ValidationError:
            raise ClientInputError("Receipt content type or size is invalid.") from None

        path = self._receipt_collection_path(household_id)
        request = Request(
            self._api_url(path),
            data=body,
            headers={
                "Authorization": self._id_token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        response, timing = self._send("api", "POST", request)
        if response.status_code != 201:
            raise HttpStatusError("api", "POST", response.status_code)

        try:
            parsed = ReceiptUploadResponse.model_validate(self._decode_json(response.body))
            self._validate_https_url(parsed.upload_url, response=True)
            if not parsed.receipt_id.strip() or parsed.expires_in <= 0:
                raise InvalidResponseError("Receipt creation response is incomplete.")

            headers = dict(parsed.upload_headers)
            expected_length = str(len(file_bytes))
            normalized_headers = self._validate_upload_headers(headers, expected_length)
            if (
                normalized_headers.get("content-type") != content_type
                or normalized_headers.get("x-amz-tagging") != "status=pending"
            ):
                raise InvalidResponseError("Receipt creation response has incomplete S3 headers.")
        except ValidationError:
            self._mark_response_invalid(timing)
            raise InvalidResponseError("Receipt creation response is invalid.") from None
        except InvalidResponseError:
            self._mark_response_invalid(timing)
            raise

        return ReceiptUploadGrant(
            receipt_id=parsed.receipt_id,
            size_bytes=len(file_bytes),
            expires_in=parsed.expires_in,
            upload_url=parsed.upload_url,
            upload_headers=MappingProxyType(headers),
        )

    def upload_file(self, grant: ReceiptUploadGrant, file_bytes: bytes) -> None:
        if not isinstance(file_bytes, bytes) or len(file_bytes) != grant.size_bytes:
            raise ClientInputError("S3 upload bytes do not match the signed file size.")
        headers = dict(grant.upload_headers)
        expected_length = str(len(file_bytes))
        normalized_headers = self._validate_upload_headers(headers, expected_length)
        if (
            "content-type" not in normalized_headers
            or normalized_headers.get("x-amz-tagging") != "status=pending"
        ):
            raise InvalidResponseError("S3 upload headers are incomplete.")
        if "content-length" not in normalized_headers:
            headers["Content-Length"] = expected_length

        self._validate_https_url(grant.upload_url, response=True)
        try:
            request = Request(
                grant.upload_url,
                data=file_bytes,
                headers=headers,
                method="PUT",
            )
        except TypeError, ValueError:
            raise InvalidResponseError("S3 upload request is invalid.") from None

        response, _ = self._send("s3", "PUT", request)
        if not 200 <= response.status_code < 300:
            raise HttpStatusError("s3", "PUT", response.status_code)

    def list_receipts(self, household_id: str) -> dict[str, ReceiptSummary]:
        path = self._receipt_collection_path(household_id)
        request = Request(
            self._api_url(path),
            headers={
                "Authorization": self._id_token,
                "Accept": "application/json",
            },
            method="GET",
        )
        response, timing = self._send("api", "GET", request)
        if response.status_code != 200:
            raise HttpStatusError("api", "GET", response.status_code)

        try:
            receipt_list = ReceiptList.model_validate(self._decode_json(response.body))
            receipts: dict[str, ReceiptSummary] = {}
            for receipt in receipt_list.receipts:
                if receipt.id in receipts:
                    raise InvalidResponseError("Receipt list contains duplicate receipt IDs.")
                receipts[receipt.id] = receipt
        except ValidationError:
            self._mark_response_invalid(timing)
            raise InvalidResponseError("Receipt list response is invalid.") from None
        except InvalidResponseError:
            self._mark_response_invalid(timing)
            raise
        return receipts

    def _send(
        self, kind: RequestKind, method: str, request: Request
    ) -> tuple[HttpResponse, RequestTiming]:
        started = self._clock()
        status_code: int | None = None
        error_category: str | None = None
        try:
            response = self._transport.send(request, self._timeout_seconds)
            status_code = response.status_code
        except RequestTimeoutError:
            error_category = "timeout"
            raise
        except NetworkRequestError:
            error_category = "network_error"
            raise
        except TimeoutError:
            error_category = "timeout"
            raise RequestTimeoutError() from None
        except URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                error_category = "timeout"
                raise RequestTimeoutError() from None
            error_category = "network_error"
            raise NetworkRequestError() from None
        except http.client.HTTPException, OSError:
            error_category = "network_error"
            raise NetworkRequestError() from None
        finally:
            completed = self._clock()
            elapsed = completed - started
            timing = RequestTiming(
                kind,
                method,
                elapsed,
                status_code,
                started_at=started,
                completed_at=completed,
                error_category=error_category,
            )
            with self._timings_lock:
                self._timings.append(timing)
        return response, timing

    def _mark_response_invalid(self, timing: RequestTiming) -> None:
        with self._timings_lock:
            for index, recorded_timing in enumerate(self._timings):
                if recorded_timing is timing:
                    self._timings[index] = replace(timing, error_category="invalid_response")
                    return
        raise RuntimeError("Validated API response has no recorded request timing.")

    def _api_url(self, path: str) -> str:
        return f"{self._api_base_url}/{path.lstrip('/')}"

    @staticmethod
    def _receipt_collection_path(household_id: str) -> str:
        if not household_id:
            raise ClientInputError("A household ID is required.")
        return f"households/{quote(household_id, safe='')}/receipts"

    @classmethod
    def _validate_api_base_url(cls, value: str) -> str:
        cls._validate_https_url(value, response=False)
        parsed = urlsplit(value)
        if parsed.query or parsed.fragment:
            raise ClientInputError("API base URL must not contain a query or fragment.")
        return value.rstrip("/")

    @staticmethod
    def _validate_https_url(value: str, *, response: bool) -> None:
        error = (
            InvalidResponseError("Presigned upload URL is invalid.")
            if response
            else ClientInputError("API base URL must be a valid HTTPS URL.")
        )
        try:
            if not isinstance(value, str) or any(
                char.isspace() or unicodedata.category(char) == "Cc" for char in value
            ):
                raise ValueError
            parsed = urlsplit(value)
            hostname = parsed.hostname
            port = parsed.port
            authority = parsed.netloc.rsplit("@", maxsplit=1)[-1]
            valid = (
                parsed.scheme == "https"
                and bool(hostname)
                and not any(char.isspace() for char in hostname or "")
                and parsed.username is None
                and parsed.password is None
                and not parsed.fragment
                and (port is None or 1 <= port <= 65535)
                and not authority.endswith(":")
            )
        except ValueError:
            valid = False
        if not valid:
            raise error

    @staticmethod
    def _validate_upload_headers(
        headers: Mapping[str, str], expected_length: str
    ) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for name, value in headers.items():
            if not isinstance(name, str) or not _HEADER_NAME_PATTERN.fullmatch(name):
                raise InvalidResponseError("S3 upload header name is invalid.")
            if not isinstance(value, str) or any(
                (unicodedata.category(char) == "Cc" and char != "\t") for char in value
            ):
                raise InvalidResponseError("S3 upload header value is invalid.")

            key = name.lower()
            if key in normalized:
                raise InvalidResponseError("S3 upload headers contain duplicate names.")
            if key in {"authorization", "proxy-authorization"}:
                raise InvalidResponseError("S3 upload headers must not contain authorization.")
            if key == "content-length" and value != expected_length:
                raise InvalidResponseError("S3 upload Content-Length does not match the file.")
            normalized[key] = value
        return normalized

    @staticmethod
    def _decode_json(body: bytes) -> object:
        def object_without_duplicate_keys(
            pairs: list[tuple[str, object]],
        ) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError
                result[key] = value
            return result

        try:
            return json.loads(body, object_pairs_hook=object_without_duplicate_keys)
        except UnicodeDecodeError, ValueError:
            raise InvalidResponseError("Server returned invalid JSON.") from None


def _not_started_result(
    receipt: GeneratedTestReceipt, planned_start_at: float
) -> UploadAttemptResult:
    return UploadAttemptResult(
        index=receipt.index,
        sha256=receipt.sha256,
        size_bytes=receipt.size_bytes,
        receipt_id=None,
        planned_start_at=planned_start_at,
        actual_start_at=None,
        s3_completed_at=None,
        finished_at=None,
        upload_succeeded=False,
        failure_category="deadline",
        error_message="Upload was not started before the acceptance deadline.",
    )


def _failed_upload_result(
    receipt: GeneratedTestReceipt,
    *,
    receipt_id: str | None,
    planned_start_at: float,
    actual_start_at: float,
    deadline_at: float,
    stage: Literal["api", "s3"],
    error: E2ELoadTestError,
    clock: Callable[[], float],
) -> UploadAttemptResult:
    finished_at = clock()
    http_status_code = error.status_code if isinstance(error, HttpStatusError) else None
    uncertain = isinstance(error, (RequestTimeoutError, NetworkRequestError)) or (
        http_status_code is not None and 500 <= http_status_code <= 599
    )
    if isinstance(error, RequestTimeoutError):
        category = f"{stage}_timeout"
        message = "HTTP request timed out; the server-side result may be unknown."
    elif isinstance(error, NetworkRequestError):
        category = f"{stage}_network_error"
        message = "HTTP network failure; the server-side result may be unknown."
    elif isinstance(error, HttpStatusError):
        category = f"{stage}_http_error"
        message = f"{stage.upper()} request returned HTTP {error.status_code}."
    elif isinstance(error, InvalidResponseError):
        category = f"{stage}_invalid_response"
        message = "Server response was invalid."
    elif isinstance(error, ClientInputError):
        category = f"{stage}_client_error"
        message = "Request input was rejected."
    else:
        category = f"{stage}_error"
        message = "Upload request failed."
    return UploadAttemptResult(
        index=receipt.index,
        sha256=receipt.sha256,
        size_bytes=receipt.size_bytes,
        receipt_id=receipt_id,
        planned_start_at=planned_start_at,
        actual_start_at=actual_start_at,
        s3_completed_at=None,
        finished_at=finished_at,
        upload_succeeded=False,
        failure_category=category,
        error_message=message,
        outcome_uncertain=uncertain,
        completed_after_deadline=finished_at > deadline_at,
        http_status_code=http_status_code,
    )


def upload_test_receipt(
    http_client: ReceiptUploadClient,
    household_id: str,
    receipt: GeneratedTestReceipt,
    *,
    planned_start_at: float,
    deadline_at: float,
    clock: Callable[[], float] = time.perf_counter,
    start_gate: Callable[[], bool] | None = None,
    on_receipt_created: Callable[[int, str], None] | None = None,
) -> UploadAttemptResult:
    """Run one API-create and S3-PUT flow.

    The receipt-created callback runs before the S3 PUT so a later status observer can
    begin tracking receipts while the rest of the upload batch is still in progress.
    """
    if not _is_finite_number(planned_start_at) or not _is_finite_number(deadline_at):
        raise ClientInputError("Upload timing values must be finite.")

    if start_gate is not None and not start_gate():
        return _not_started_result(receipt, planned_start_at)

    stage: Literal["api", "s3"] = "api"
    receipt_id: str | None = None
    actual_start_at = clock()
    if not _is_finite_number(actual_start_at):
        raise ClientInputError("Actual upload start time must be finite.")
    if actual_start_at >= deadline_at:
        return _not_started_result(receipt, planned_start_at)
    try:
        grant = http_client.create_receipt(household_id, receipt.content_type, receipt.file_bytes)
        receipt_id = grant.receipt_id
    except E2ELoadTestError as error:
        return _failed_upload_result(
            receipt,
            receipt_id=receipt_id,
            planned_start_at=planned_start_at,
            actual_start_at=actual_start_at,
            deadline_at=deadline_at,
            stage=stage,
            error=error,
            clock=clock,
        )

    if on_receipt_created is not None:
        on_receipt_created(receipt.index, receipt_id)

    if clock() >= deadline_at:
        finished_at = clock()
        return UploadAttemptResult(
            index=receipt.index,
            sha256=receipt.sha256,
            size_bytes=receipt.size_bytes,
            receipt_id=receipt_id,
            planned_start_at=planned_start_at,
            actual_start_at=actual_start_at,
            s3_completed_at=None,
            finished_at=finished_at,
            upload_succeeded=False,
            failure_category="deadline",
            error_message="S3 upload was not started before the acceptance deadline.",
            completed_after_deadline=finished_at > deadline_at,
        )

    stage = "s3"
    try:
        http_client.upload_file(grant, receipt.file_bytes)
    except E2ELoadTestError as error:
        return _failed_upload_result(
            receipt,
            receipt_id=receipt_id,
            planned_start_at=planned_start_at,
            actual_start_at=actual_start_at,
            deadline_at=deadline_at,
            stage=stage,
            error=error,
            clock=clock,
        )

    s3_completed_at = clock()
    return UploadAttemptResult(
        index=receipt.index,
        sha256=receipt.sha256,
        size_bytes=receipt.size_bytes,
        receipt_id=receipt_id,
        planned_start_at=planned_start_at,
        actual_start_at=actual_start_at,
        s3_completed_at=s3_completed_at,
        finished_at=s3_completed_at,
        upload_succeeded=True,
        failure_category=None,
        completed_after_deadline=s3_completed_at > deadline_at,
    )


def run_upload_load(
    http_client: ReceiptUploadClient,
    household_id: str,
    receipts: Sequence[GeneratedTestReceipt],
    config: E2ELoadTestConfig,
    *,
    clock: Callable[[], float] = time.perf_counter,
    sleep: Callable[[float], None] = time.sleep,
    on_receipt_created: Callable[[int, str], None] | None = None,
    status_monitor: ReceiptStatusMonitor | None = None,
) -> tuple[UploadAttemptResult, ...]:
    """Schedule pre-generated receipts at the configured rate and concurrency limit."""
    if not household_id:
        raise ClientInputError("A household ID is required.")
    if len(receipts) != config.receipt_count:
        raise ClientInputError("Receipt count does not match the load-test configuration.")
    ordered_receipts = sorted(receipts, key=lambda receipt: receipt.index)
    if [receipt.index for receipt in ordered_receipts] != list(range(config.receipt_count)):
        raise ClientInputError("Test receipt indices must cover the configured run.")
    if len({receipt.sha256 for receipt in ordered_receipts}) != config.receipt_count:
        raise ClientInputError("Test receipt hashes must be unique.")
    if status_monitor is not None and status_monitor.household_id != household_id:
        raise ClientInputError("Status monitor household does not match the upload run.")

    run_started_at = clock()
    deadline_at = run_started_at + config.acceptance_window_seconds
    interval = 1.0 / config.starts_per_second
    if not _is_finite_number(run_started_at) or not _is_finite_number(deadline_at):
        raise ClientInputError("Load-test timing values must be finite.")
    planned_start_at = [run_started_at + index * interval for index in range(config.receipt_count)]
    next_actual_start_at = run_started_at
    start_lock = threading.Lock()

    def await_actual_start() -> bool:
        nonlocal next_actual_start_at
        while True:
            with start_lock:
                now = clock()
                if now >= deadline_at:
                    return False
                if now >= next_actual_start_at:
                    next_actual_start_at = now + interval
                    return True
                delay = min(next_actual_start_at - now, deadline_at - now)
            sleep(delay)

    results: list[UploadAttemptResult | None] = [None] * config.receipt_count
    futures: list[tuple[int, Future[UploadAttemptResult]]] = []
    active_futures: set[Future[UploadAttemptResult]] = set()
    monitor_started = False

    if status_monitor is not None:
        status_monitor.start(run_started_at, clock=clock)
        monitor_started = True

    def notify_receipt_created(index: int, receipt_id: str) -> None:
        if status_monitor is not None:
            status_monitor.register_receipt(index, receipt_id)
        if on_receipt_created is not None:
            on_receipt_created(index, receipt_id)

    receipt_created_callback = (
        notify_receipt_created
        if status_monitor is not None or on_receipt_created is not None
        else None
    )

    def mark_not_started(from_index: int) -> None:
        for index in range(from_index, config.receipt_count):
            results[index] = _not_started_result(ordered_receipts[index], planned_start_at[index])

    def collect_finished_futures() -> None:
        for index, future in futures:
            if results[index] is None and future.done():
                result = future.result()
                results[index] = result
                if status_monitor is not None:
                    status_monitor.attach_upload_result(result)
                active_futures.discard(future)

    def wait_until(target_at: float) -> bool:
        while True:
            now = clock()
            if now >= deadline_at:
                return False
            if now >= target_at:
                return True
            sleep(min(target_at - now, deadline_at - now))

    try:
        with ThreadPoolExecutor(
            max_workers=min(config.max_concurrency, config.receipt_count)
        ) as executor:
            for index, receipt in enumerate(ordered_receipts):
                collect_finished_futures()
                target_at = planned_start_at[index]
                if target_at >= deadline_at or not wait_until(target_at):
                    mark_not_started(index)
                    break

                while True:
                    collect_finished_futures()
                    if len(active_futures) < config.max_concurrency:
                        break
                    now = clock()
                    if now >= deadline_at:
                        break
                    sleep(min(0.01, deadline_at - now))
                if clock() >= deadline_at:
                    mark_not_started(index)
                    break

                future = executor.submit(
                    upload_test_receipt,
                    http_client,
                    household_id,
                    receipt,
                    planned_start_at=planned_start_at[index],
                    deadline_at=deadline_at,
                    clock=clock,
                    start_gate=await_actual_start,
                    on_receipt_created=receipt_created_callback,
                )
                futures.append((index, future))
                active_futures.add(future)

        for index, future in futures:
            if results[index] is None:
                result = future.result()
                results[index] = result
                if status_monitor is not None:
                    status_monitor.attach_upload_result(result)

        completed_results: list[UploadAttemptResult] = []
        for result in results:
            if result is None:
                raise RuntimeError("Load test finished without recording every receipt.")
            completed_results.append(result)
        result_tuple = tuple(completed_results)
        if status_monitor is not None:
            status_monitor.finish_upload_phase(result_tuple)
            status_monitor.join()
            monitor_started = False
        return result_tuple
    finally:
        if monitor_started and status_monitor is not None and status_monitor.thread_is_alive:
            status_monitor.stop()
            status_monitor.join()


@dataclass(frozen=True)
class RuntimeStatistics:
    count: int
    minimum_seconds: float | None
    mean_seconds: float | None
    median_seconds: float | None
    p95_seconds: float | None
    maximum_seconds: float | None


@dataclass(frozen=True)
class RequestMetrics:
    request_count: int
    succeeded_count: int
    failed_count: int
    timeout_count: int
    network_error_count: int
    http_error_count: int
    latency: RuntimeStatistics
    successful_latency: RuntimeStatistics
    failed_latency: RuntimeStatistics
    timeout_latency: RuntimeStatistics
    missing_elapsed_count: int
    missing_start_time_count: int


@dataclass(frozen=True)
class QualityAssessment:
    status: AssessmentStatus
    reason: str
    measured_value: float | int | None = None
    threshold: str | None = None


@dataclass(frozen=True)
class UploadReportResult:
    index: int
    sha256: str
    size_bytes: int
    receipt_id: str | None
    planned_start_at: float
    actual_start_at: float | None
    s3_completed_at: float | None
    finished_at: float | None
    upload_succeeded: bool
    failure_category: str | None
    outcome_uncertain: bool
    completed_after_deadline: bool
    http_status_code: int | None


@dataclass(frozen=True)
class ReceiptReportResult:
    index: int
    receipt_id: str
    registered_at: float
    registered_after_deadline: bool
    last_nonterminal_status: ReceiptStatus | None
    last_nonterminal_observed_at: float | None
    first_terminal_status: ReceiptStatus | None
    first_terminal_observed_at: float | None
    status_observations: tuple[ReceiptStatusObservation, ...]
    status_conflicts: tuple[ReceiptStatusConflict, ...]
    missing_response_count: int
    last_missing_response_at: float | None
    monitoring_outcome: str
    terminal_observed_before_s3_confirmation: bool
    terminal_observed_after_deadline: bool


@dataclass(frozen=True)
class PollingErrorReport:
    category: str
    occurred_at: float
    http_status: int | None
    fatal: bool


@dataclass(frozen=True)
class E2ELoadTestReport:
    run_id: str
    profile: TestProfile
    configuration: dict[str, int | float | str | None]
    expected_receipts: int
    timing: dict[str, float | None]
    file_sizes_bytes: tuple[int, ...]
    upload_summary: dict[str, int | dict[str, int] | None]
    processing_summary: dict[str, int | None]
    api_request_metrics: dict[str, RequestMetrics]
    s3_put_metrics: RequestMetrics
    e2e_processing_latency: RuntimeStatistics
    throughput: dict[str, float | int | None]
    quality_assessments: dict[str, QualityAssessment]
    data_quality: dict[str, int | list[int] | None]
    upload_results: tuple[UploadReportResult, ...]
    receipt_results: tuple[ReceiptReportResult, ...]
    polling_errors: tuple[PollingErrorReport, ...]
    measurement_definitions: tuple[str, ...]

    def to_json(self) -> str:
        return json.dumps(_json_safe(asdict(self)), indent=2, sort_keys=True, allow_nan=False)

    def to_dict(self) -> dict[str, object]:
        return json.loads(self.to_json())

    def summary_text(self) -> str:
        done = self.processing_summary["done_observed"]
        confirmed = self.upload_summary["confirmed_s3_uploads"]
        e2e_p95 = self.e2e_processing_latency.p95_seconds
        p95_text = "n/a" if e2e_p95 is None else f"{e2e_p95:.2f}s"
        return (
            f"Bonbon E2E {self.profile} run {self.run_id}: "
            f"{confirmed}/{self.expected_receipts} S3 uploads confirmed, "
            f"{done}/{self.expected_receipts} done observed, E2E p95 {p95_text}."
        )


@dataclass(frozen=True)
class _ProcessingMetrics:
    done_records: tuple[ReceiptMonitoringRecord, ...]
    done_within_deadline: int | None
    done_after_deadline: int | None
    failed_records: int
    duplicate_records: int
    uploaded_records: int
    missing_status_records: int
    missing_or_unobserved: int
    missing_list_observations: int
    conflicts: int
    conflicting_terminal_failures: int
    uncertain_uploads_done: int
    e2e_stats: RuntimeStatistics
    e2e_temporal_overlaps: int
    e2e_missing_observed_at: int
    e2e_invalid_timestamps: int
    e2e_without_confirmed_s3: int
    e2e_linkage_mismatches: int


def _json_safe(value: object) -> object:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    return value


def nearest_rank_percentile(values: Sequence[float], percentile: float = 0.95) -> float | None:
    if not _is_finite_number(percentile) or not 0 < percentile <= 1:
        raise ClientInputError("Percentile must be finite and in (0, 1].")
    if not values:
        return None
    if any(not _is_finite_number(value) or value < 0 for value in values):
        raise ClientInputError("Runtime samples must be finite and non-negative.")
    ordered = sorted(values)
    return ordered[math.ceil(percentile * len(ordered)) - 1]


def runtime_statistics(values: Sequence[float]) -> RuntimeStatistics:
    if not values:
        return RuntimeStatistics(0, None, None, None, None, None)
    if any(not _is_finite_number(value) or value < 0 for value in values):
        raise ClientInputError("Runtime samples must be finite and non-negative.")
    return RuntimeStatistics(
        count=len(values),
        minimum_seconds=min(values),
        mean_seconds=math.fsum(value / len(values) for value in values),
        median_seconds=median(values),
        p95_seconds=nearest_rank_percentile(values),
        maximum_seconds=max(values),
    )


def _request_succeeded(timing: RequestTiming) -> bool:
    if timing.error_category is not None or timing.status_code is None:
        return False
    if timing.kind == "s3":
        return timing.method == "PUT" and 200 <= timing.status_code < 300
    expected_status = {"GET": 200, "POST": 201}.get(timing.method)
    return (
        timing.status_code == expected_status
        if expected_status is not None
        else 200 <= timing.status_code < 300
    )


def _request_metrics(
    timings: Sequence[RequestTiming],
    *,
    missing_start_time_count: int | None = None,
) -> RequestMetrics:
    succeeded = [timing for timing in timings if _request_succeeded(timing)]
    failed = [timing for timing in timings if not _request_succeeded(timing)]
    timed_out = [timing for timing in failed if timing.error_category == "timeout"]
    network_errors = [timing for timing in failed if timing.error_category == "network_error"]

    def valid_durations(items: Sequence[RequestTiming]) -> list[float]:
        return [
            item.elapsed_seconds
            for item in items
            if _is_finite_number(item.elapsed_seconds) and item.elapsed_seconds >= 0
        ]

    durations = valid_durations(timings)
    return RequestMetrics(
        request_count=len(timings),
        succeeded_count=len(succeeded),
        failed_count=len(failed),
        timeout_count=len(timed_out),
        network_error_count=len(network_errors),
        http_error_count=sum(timing.status_code is not None for timing in failed),
        latency=runtime_statistics(durations),
        successful_latency=runtime_statistics(valid_durations(succeeded)),
        failed_latency=runtime_statistics(valid_durations(failed)),
        timeout_latency=runtime_statistics(valid_durations(timed_out)),
        missing_elapsed_count=len(timings) - len(durations),
        missing_start_time_count=(
            sum(not _is_finite_number(item.started_at) for item in timings)
            if missing_start_time_count is None
            else missing_start_time_count
        ),
    )


def _quality_assessment(
    status: AssessmentStatus,
    reason: str,
    *,
    measured_value: float | int | None = None,
    threshold: str | None = None,
) -> QualityAssessment:
    return QualityAssessment(status, reason, measured_value, threshold)


def _validate_report_indices(
    indices: Sequence[int],
    receipt_count: int,
    result_name: str,
) -> None:
    invalid_indices = [
        index for index in indices if type(index) is not int or not 0 <= index < receipt_count
    ]
    seen_indices: set[int] = set()
    duplicate_indices: set[int] = set()
    for index in indices:
        if type(index) is int and 0 <= index < receipt_count:
            if index in seen_indices:
                duplicate_indices.add(index)
            seen_indices.add(index)
    if invalid_indices or duplicate_indices:
        raise ClientInputError(
            f"{result_name} indices must be unique and in range "
            f"0..{receipt_count - 1}; duplicates="
            f"{sorted(duplicate_indices)}, invalid="
            f"{
                [
                    index if type(index) is int else f'<{type(index).__name__}>'
                    for index in invalid_indices
                ]
            }."
        )


def _aggregate_processing_metrics(
    monitoring_records: Sequence[ReceiptMonitoringRecord],
    upload_by_index: Mapping[int, UploadAttemptResult],
    missing_record_count: int,
    processing_deadline_at: float | None,
) -> _ProcessingMetrics:
    done_records = tuple(
        record for record in monitoring_records if record.first_terminal_status == "done"
    )
    done_within_deadline = (
        sum(
            record.first_terminal_observed_at is not None
            and record.first_terminal_observed_at <= processing_deadline_at
            for record in done_records
        )
        if processing_deadline_at is not None
        else None
    )
    done_after_deadline = (
        sum(
            record.first_terminal_observed_at is not None
            and record.first_terminal_observed_at > processing_deadline_at
            for record in done_records
        )
        if processing_deadline_at is not None
        else None
    )
    failed_records = sum(record.first_terminal_status == "failed" for record in monitoring_records)
    duplicate_records = sum(
        record.first_terminal_status == "duplicate" for record in monitoring_records
    )
    uploaded_records = sum(
        record.first_terminal_status is None and record.last_nonterminal_status == "uploaded"
        for record in monitoring_records
    )
    missing_status_records = sum(not record.status_observations for record in monitoring_records)
    missing_or_unobserved = missing_record_count + missing_status_records
    missing_list_observations = sum(record.missing_response_count for record in monitoring_records)
    conflicts = sum(len(record.status_conflicts) for record in monitoring_records)
    conflicting_terminal_failures = sum(
        conflict.later_status in ("failed", "duplicate")
        for record in monitoring_records
        for conflict in record.status_conflicts
    )
    uncertain_uploads_done = 0
    e2e_samples: list[float] = []
    e2e_temporal_overlaps = 0
    e2e_missing_observed_at = 0
    e2e_invalid_timestamps = 0
    e2e_without_confirmed_s3 = 0
    e2e_linkage_mismatches = 0
    for record in done_records:
        result = record.upload_result or upload_by_index.get(record.index)
        if result is not None and result.outcome_uncertain:
            uncertain_uploads_done += 1
        if result is None or result.receipt_id != record.receipt_id:
            e2e_linkage_mismatches += 1
            continue
        if not result.upload_succeeded or not _is_finite_number(result.s3_completed_at):
            e2e_without_confirmed_s3 += 1
            continue
        observed_at = record.first_terminal_observed_at
        if observed_at is None:
            e2e_missing_observed_at += 1
            continue
        if not _is_finite_number(observed_at):
            e2e_invalid_timestamps += 1
            continue
        if observed_at < result.s3_completed_at:
            e2e_temporal_overlaps += 1
            continue
        elapsed = observed_at - result.s3_completed_at
        if math.isfinite(elapsed) and elapsed >= 0:
            e2e_samples.append(elapsed)
        else:
            e2e_invalid_timestamps += 1

    return _ProcessingMetrics(
        done_records=done_records,
        done_within_deadline=done_within_deadline,
        done_after_deadline=done_after_deadline,
        failed_records=failed_records,
        duplicate_records=duplicate_records,
        uploaded_records=uploaded_records,
        missing_status_records=missing_status_records,
        missing_or_unobserved=missing_or_unobserved,
        missing_list_observations=missing_list_observations,
        conflicts=conflicts,
        conflicting_terminal_failures=conflicting_terminal_failures,
        uncertain_uploads_done=uncertain_uploads_done,
        e2e_stats=runtime_statistics(e2e_samples),
        e2e_temporal_overlaps=e2e_temporal_overlaps,
        e2e_missing_observed_at=e2e_missing_observed_at,
        e2e_invalid_timestamps=e2e_invalid_timestamps,
        e2e_without_confirmed_s3=e2e_without_confirmed_s3,
        e2e_linkage_mismatches=e2e_linkage_mismatches,
    )


def _classify_upload_outcomes(
    upload_results: Sequence[UploadAttemptResult],
    run_started_at: float | None,
    acceptance_deadline_at: float | None,
) -> tuple[dict[str, int], int, int, int]:
    outcome_categories = {
        "confirmed_within_window": 0,
        "confirmed_late": 0,
        "confirmed_time_unavailable": 0,
        "api_failed": 0,
        "api_uncertain": 0,
        "s3_failed": 0,
        "s3_uncertain": 0,
        "s3_put_not_started": 0,
        "other_uncertain": 0,
        "other_failure": 0,
        "not_started": 0,
    }
    confirmed_within_window = 0
    confirmed_late = 0
    invalid_s3_timestamps = 0
    for result in upload_results:
        if result.actual_start_at is None:
            category = "not_started"
        elif result.upload_succeeded:
            if (
                acceptance_deadline_at is None
                or not _is_finite_number(result.s3_completed_at)
                or run_started_at is None
                or result.s3_completed_at < run_started_at
            ):
                category = "confirmed_time_unavailable"
                if result.s3_completed_at is not None and (
                    not _is_finite_number(result.s3_completed_at)
                    or (run_started_at is not None and result.s3_completed_at < run_started_at)
                ):
                    invalid_s3_timestamps += 1
            elif (
                acceptance_deadline_at is not None
                and result.s3_completed_at <= acceptance_deadline_at
            ):
                category = "confirmed_within_window"
                confirmed_within_window += 1
            else:
                category = "confirmed_late"
                confirmed_late += 1
        elif result.failure_category == "deadline" and result.receipt_id is not None:
            category = "s3_put_not_started"
        elif result.failure_category is not None and result.failure_category.startswith("api_"):
            category = "api_uncertain" if result.outcome_uncertain else "api_failed"
        elif result.failure_category is not None and result.failure_category.startswith("s3_"):
            category = "s3_uncertain" if result.outcome_uncertain else "s3_failed"
        elif result.outcome_uncertain:
            category = "other_uncertain"
        else:
            category = "other_failure"
        outcome_categories[category] += 1
    return (
        outcome_categories,
        confirmed_within_window,
        confirmed_late,
        invalid_s3_timestamps,
    )


def _aggregate_request_metrics(
    request_timings: Sequence[RequestTiming],
    run_started_at: float | None,
    acceptance_deadline_at: float | None,
) -> tuple[dict[str, RequestMetrics], RequestMetrics]:
    api_timings = [item for item in request_timings if item.kind == "api"]
    post_timings = [item for item in api_timings if item.method == "POST"]
    get_timings = [item for item in api_timings if item.method == "GET"]
    missing_peak_start_times = sum(not _is_finite_number(item.started_at) for item in api_timings)
    peak_timings = (
        [
            item
            for item in api_timings
            if _is_finite_number(item.started_at)
            and run_started_at <= item.started_at < acceptance_deadline_at
        ]
        if acceptance_deadline_at is not None and run_started_at is not None
        else []
    )
    api_metrics = {
        "all": _request_metrics(api_timings),
        "post": _request_metrics(post_timings),
        "get": _request_metrics(get_timings),
        "peak_window": _request_metrics(
            peak_timings,
            missing_start_time_count=missing_peak_start_times,
        ),
    }
    s3_metrics = _request_metrics(
        [item for item in request_timings if item.kind == "s3" and item.method == "PUT"]
    )
    return api_metrics, s3_metrics


def _report_result_records(
    upload_results: Sequence[UploadAttemptResult],
    monitoring_records: Sequence[ReceiptMonitoringRecord],
    polling_errors: Sequence[PollingErrorObservation],
) -> tuple[
    tuple[UploadReportResult, ...],
    tuple[ReceiptReportResult, ...],
    tuple[PollingErrorReport, ...],
]:
    safe_upload_results = tuple(
        UploadReportResult(
            index=result.index,
            sha256=result.sha256,
            size_bytes=result.size_bytes,
            receipt_id=result.receipt_id,
            planned_start_at=result.planned_start_at,
            actual_start_at=result.actual_start_at,
            s3_completed_at=result.s3_completed_at,
            finished_at=result.finished_at,
            upload_succeeded=result.upload_succeeded,
            failure_category=result.failure_category,
            outcome_uncertain=result.outcome_uncertain,
            completed_after_deadline=result.completed_after_deadline,
            http_status_code=result.http_status_code,
        )
        for result in sorted(upload_results, key=lambda item: item.index)
    )
    safe_receipt_results = tuple(
        ReceiptReportResult(
            index=record.index,
            receipt_id=record.receipt_id,
            registered_at=record.registered_at,
            registered_after_deadline=record.registered_after_deadline,
            last_nonterminal_status=record.last_nonterminal_status,
            last_nonterminal_observed_at=record.last_nonterminal_observed_at,
            first_terminal_status=record.first_terminal_status,
            first_terminal_observed_at=record.first_terminal_observed_at,
            status_observations=record.status_observations,
            status_conflicts=record.status_conflicts,
            missing_response_count=record.missing_response_count,
            last_missing_response_at=record.last_missing_response_at,
            monitoring_outcome=record.monitoring_outcome,
            terminal_observed_before_s3_confirmation=record.terminal_observed_before_s3_confirmation,
            terminal_observed_after_deadline=record.terminal_observed_after_deadline,
        )
        for record in sorted(monitoring_records, key=lambda item: item.index)
    )
    safe_polling_errors = tuple(
        PollingErrorReport(
            category=error.category,
            occurred_at=error.occurred_at,
            http_status=error.http_status,
            fatal=error.fatal,
        )
        for error in polling_errors
    )
    return safe_upload_results, safe_receipt_results, safe_polling_errors


def build_e2e_load_test_report(
    config: E2ELoadTestConfig,
    upload_results: Sequence[UploadAttemptResult],
    request_timings: Sequence[RequestTiming],
    *,
    status_monitor: ReceiptStatusMonitor | None = None,
    run_started_at: float | None = None,
    completed_at: float | None = None,
    processing_timeout_seconds: float = 180.0,
    request_timeout_seconds: float = 10.0,
) -> E2ELoadTestReport:
    if not _is_finite_number(processing_timeout_seconds) or processing_timeout_seconds <= 0:
        raise ClientInputError("Processing timeout must be finite and positive.")
    if not _is_finite_number(request_timeout_seconds) or request_timeout_seconds <= 0:
        raise ClientInputError("Request timeout must be finite and positive.")
    expected_indices = set(range(config.receipt_count))
    upload_indices = [result.index for result in upload_results]
    _validate_report_indices(upload_indices, config.receipt_count, "Upload result")
    upload_by_index = {result.index: result for result in upload_results}
    missing_upload_indices = sorted(expected_indices - set(upload_by_index))
    upload_indices_complete = not missing_upload_indices
    if run_started_at is None and status_monitor is not None:
        run_started_at = status_monitor.run_started_at
    if run_started_at is None and 0 in upload_by_index:
        run_started_at = upload_by_index[0].planned_start_at
    if run_started_at is not None and not _is_finite_number(run_started_at):
        raise ClientInputError("Load-test start time must be finite.")

    if status_monitor is not None:
        monitoring_records = status_monitor.snapshot()
        polling_errors = status_monitor.polling_errors
        monitor_stop_reason = status_monitor.stop_reason
        monitor_finished_at = status_monitor.finished_at
        processing_deadline_at = status_monitor.processing_deadline_at
        linkage_error_count = len(status_monitor.linkage_errors)
        processing_timeout_seconds = status_monitor.processing_timeout_seconds
    else:
        monitoring_records = ()
        polling_errors = ()
        monitor_stop_reason = None
        monitor_finished_at = None
        processing_deadline_at = None
        linkage_error_count = 0

    if completed_at is None and len(upload_results) == config.receipt_count:
        event_times = [
            timestamp
            for timestamp in (
                monitor_finished_at,
                *(result.finished_at for result in upload_results),
                *(timing.completed_at for timing in request_timings),
                *(
                    observation.observed_at
                    for record in monitoring_records
                    for observation in record.status_observations
                ),
                *(error.occurred_at for error in polling_errors),
            )
            if _is_finite_number(timestamp)
        ]
        completed_at = max(event_times) if event_times else None
    if completed_at is not None and not _is_finite_number(completed_at):
        raise ClientInputError("Load-test completion time must be finite.")

    acceptance_deadline_at = (
        run_started_at + config.acceptance_window_seconds if run_started_at is not None else None
    )
    if acceptance_deadline_at is not None and not math.isfinite(acceptance_deadline_at):
        raise ClientInputError("Acceptance deadline must be finite.")
    if processing_deadline_at is None and run_started_at is not None:
        processing_deadline_at = run_started_at + processing_timeout_seconds
    if processing_deadline_at is not None and not math.isfinite(processing_deadline_at):
        raise ClientInputError("Processing deadline must be finite.")
    run_duration = (
        completed_at - run_started_at
        if completed_at is not None and run_started_at is not None
        else None
    )
    if run_duration is not None and (not math.isfinite(run_duration) or run_duration < 0):
        run_duration = None

    upload_started = sum(result.actual_start_at is not None for result in upload_results)
    receipt_records_created = sum(result.receipt_id is not None for result in upload_results)
    confirmed_uploads = [result for result in upload_results if result.upload_succeeded]
    (
        outcome_categories,
        confirmed_within_window,
        confirmed_late,
        invalid_s3_timestamps,
    ) = _classify_upload_outcomes(upload_results, run_started_at, acceptance_deadline_at)

    api_metrics, s3_metrics = _aggregate_request_metrics(
        request_timings, run_started_at, acceptance_deadline_at
    )
    peak_expected_post_count = (
        sum(
            _is_finite_number(result.actual_start_at)
            and run_started_at <= result.actual_start_at < acceptance_deadline_at
            for result in upload_results
        )
        if run_started_at is not None and acceptance_deadline_at is not None
        else None
    )
    peak_observed_post_count = (
        sum(
            timing.kind == "api"
            and timing.method == "POST"
            and _is_finite_number(timing.started_at)
            and run_started_at <= timing.started_at < acceptance_deadline_at
            for timing in request_timings
        )
        if run_started_at is not None and acceptance_deadline_at is not None
        else None
    )
    peak_missing_post_count = (
        max(peak_expected_post_count - peak_observed_post_count, 0)
        if peak_expected_post_count is not None and peak_observed_post_count is not None
        else None
    )
    peak_unexpected_post_count = (
        max(peak_observed_post_count - peak_expected_post_count, 0)
        if peak_expected_post_count is not None and peak_observed_post_count is not None
        else None
    )

    status_indices = [record.index for record in monitoring_records]
    _validate_report_indices(status_indices, config.receipt_count, "Status record")
    records_by_index = {record.index: record for record in monitoring_records}
    missing_record_indices = sorted(expected_indices - set(records_by_index))
    status_indices_complete = not missing_record_indices
    status_linkage_mismatches = sorted(
        record.index
        for record in monitoring_records
        if record.index not in upload_by_index
        or upload_by_index[record.index].receipt_id != record.receipt_id
        or (
            record.upload_result is not None
            and record.upload_result != upload_by_index.get(record.index)
        )
    )
    status_linkage_complete = not status_linkage_mismatches and linkage_error_count == 0
    processing_metrics = _aggregate_processing_metrics(
        monitoring_records,
        upload_by_index,
        len(missing_record_indices),
        processing_deadline_at,
    )
    last_confirmed_at = max(
        (
            result.s3_completed_at
            for result in confirmed_uploads
            if _is_finite_number(result.s3_completed_at)
        ),
        default=None,
    )
    last_done_at = max(
        (
            record.first_terminal_observed_at
            for record in processing_metrics.done_records
            if _is_finite_number(record.first_terminal_observed_at)
        ),
        default=None,
    )
    duration_to_last_upload = (
        last_confirmed_at - run_started_at
        if last_confirmed_at is not None and run_started_at is not None
        else None
    )
    duration_to_last_done = (
        last_done_at - run_started_at
        if last_done_at is not None and run_started_at is not None
        else None
    )
    if duration_to_last_upload is not None and (
        not math.isfinite(duration_to_last_upload) or duration_to_last_upload < 0
    ):
        duration_to_last_upload = None
    if duration_to_last_done is not None and (
        not math.isfinite(duration_to_last_done) or duration_to_last_done < 0
    ):
        duration_to_last_done = None
    upload_throughput = (
        len(confirmed_uploads) / duration_to_last_upload
        if duration_to_last_upload is not None and duration_to_last_upload > 0
        else None
    )
    processed_throughput = (
        len(processing_metrics.done_records) / duration_to_last_done
        if duration_to_last_done is not None and duration_to_last_done > 0
        else None
    )
    upload_failures = max(config.receipt_count - len(confirmed_uploads), 0)
    upload_failure_rate = (
        upload_failures / config.receipt_count * 100 if config.receipt_count else None
    )
    not_processed_share = (
        (config.receipt_count - processing_metrics.done_within_deadline)
        / config.receipt_count
        * 100
        if config.receipt_count and processing_metrics.done_within_deadline is not None
        else None
    )

    upload_summary: dict[str, int | dict[str, int] | None] = {
        "planned": config.receipt_count,
        "started": upload_started,
        "receipt_records_created": receipt_records_created,
        "confirmed_s3_uploads": len(confirmed_uploads),
        "confirmed_within_acceptance_window": (
            confirmed_within_window if acceptance_deadline_at is not None else None
        ),
        "confirmed_late": confirmed_late if acceptance_deadline_at is not None else None,
        "invalid_s3_completion_timestamps": invalid_s3_timestamps,
        "api_errors": sum(
            result.failure_category is not None and result.failure_category.startswith("api_")
            for result in upload_results
        ),
        "s3_errors": sum(
            result.failure_category is not None and result.failure_category.startswith("s3_")
            for result in upload_results
        ),
        "uncertain": sum(result.outcome_uncertain for result in upload_results),
        "not_started": sum(result.actual_start_at is None for result in upload_results),
        "s3_put_not_started_after_deadline": sum(
            result.failure_category == "deadline" and result.receipt_id is not None
            for result in upload_results
        ),
        "confirmed_bytes": sum(result.size_bytes for result in confirmed_uploads),
        "outcome_categories": outcome_categories,
    }
    processing_summary: dict[str, int | None] = {
        "expected": config.receipt_count,
        "done_observed": len(processing_metrics.done_records),
        "done_within_processing_deadline": processing_metrics.done_within_deadline,
        "done_after_processing_deadline": processing_metrics.done_after_deadline,
        "failed": processing_metrics.failed_records,
        "duplicate": processing_metrics.duplicate_records,
        "still_uploaded": processing_metrics.uploaded_records,
        "missing_or_unobserved_receipt_ids": processing_metrics.missing_or_unobserved,
        "missing_list_observations": processing_metrics.missing_list_observations,
        "conflicting_status_observations": processing_metrics.conflicts,
        "conflicting_terminal_failures": processing_metrics.conflicting_terminal_failures,
        "polling_errors": len(polling_errors),
        "uncertain_uploads_later_done": processing_metrics.uncertain_uploads_done,
    }

    quality: dict[str, QualityAssessment] = {
        "normal_e2e_p95_10_seconds": _quality_assessment(
            "NOT_EVALUATED", "This objective applies only to Normal Load."
        ),
        "peak_200_uploads_within_60_seconds": _quality_assessment(
            "NOT_EVALUATED", "This objective applies only to Peak Load."
        ),
        "peak_200_done_within_180_seconds": _quality_assessment(
            "NOT_EVALUATED", "This objective applies only to Peak Load."
        ),
        "peak_api_p95_below_1_second": _quality_assessment(
            "NOT_EVALUATED", "This objective applies only to Peak Load."
        ),
        "smoke_functional_check": _quality_assessment(
            "NOT_EVALUATED", "This objective applies only to Smoke Test."
        ),
        "dlq_textract_throttling": _quality_assessment(
            "NOT_EVALUATED",
            "Requires a later CloudWatch DLQ inspection; this report makes no AWS query.",
        ),
    }
    if config.profile == "normal_load":
        if not _profile_configuration_matches(config):
            quality["normal_e2e_p95_10_seconds"] = _quality_assessment(
                "INCONCLUSIVE",
                "The provisional Normal Load profile requires 20 receipts.",
                threshold="20 receipts; E2E p95 <= 10 seconds",
            )
        else:
            complete_e2e = (
                processing_metrics.e2e_stats.count == config.receipt_count
                and upload_indices_complete
                and status_indices_complete
                and status_linkage_complete
                and processing_metrics.missing_or_unobserved == 0
                and processing_metrics.conflicts == 0
                and processing_metrics.e2e_temporal_overlaps == 0
                and processing_metrics.e2e_without_confirmed_s3 == 0
                and processing_metrics.e2e_linkage_mismatches == 0
            )
            p95 = processing_metrics.e2e_stats.p95_seconds
            if (
                processing_metrics.failed_records
                or processing_metrics.duplicate_records
                or processing_metrics.conflicting_terminal_failures
            ):
                assessment = _quality_assessment(
                    "FAIL",
                    "At least one receipt has a confirmed failed or duplicate terminal status.",
                    measured_value=p95,
                    threshold="<= 10 seconds",
                )
            elif not complete_e2e or p95 is None:
                assessment = _quality_assessment(
                    "INCONCLUSIVE",
                    "The E2E sample is incomplete or contains unmeasurable receipts.",
                    measured_value=p95,
                    threshold="<= 10 seconds",
                )
            elif p95 <= 10.0:
                assessment = _quality_assessment(
                    "PASS",
                    "Complete observed E2E p95 is within the target.",
                    measured_value=p95,
                    threshold="<= 10 seconds",
                )
            else:
                assessment = _quality_assessment(
                    "FAIL",
                    "Complete observed E2E p95 exceeds the target.",
                    measured_value=p95,
                    threshold="<= 10 seconds",
                )
            quality["normal_e2e_p95_10_seconds"] = assessment
    elif config.profile == "peak_load":
        peak_profile_matches = _profile_configuration_matches(config)
        if not peak_profile_matches or len(upload_results) != 200 or acceptance_deadline_at is None:
            quality["peak_200_uploads_within_60_seconds"] = _quality_assessment(
                "INCONCLUSIVE",
                "The original Peak profile (200 receipts, 4 starts/s, "
                "concurrency 10, 60s) is required.",
                measured_value=confirmed_within_window,
                threshold="200 within 60 seconds",
            )
        elif (
            confirmed_within_window == 200
            and duration_to_last_upload is not None
            and duration_to_last_upload <= 60
        ):
            quality["peak_200_uploads_within_60_seconds"] = _quality_assessment(
                "PASS",
                "All 200 S3 uploads were confirmed within the acceptance window.",
                measured_value=duration_to_last_upload,
                threshold="<= 60 seconds",
            )
        else:
            quality["peak_200_uploads_within_60_seconds"] = _quality_assessment(
                "FAIL",
                "Fewer than 200 S3 uploads were confirmed within 60 seconds.",
                measured_value=confirmed_within_window,
                threshold="200 within 60 seconds",
            )

        peak_processing_deadline = run_started_at + 180.0 if run_started_at is not None else None
        done_by_peak_deadline = (
            sum(
                record.first_terminal_status == "done"
                and record.first_terminal_observed_at is not None
                and record.first_terminal_observed_at <= peak_processing_deadline
                for record in monitoring_records
            )
            if peak_processing_deadline is not None
            else None
        )
        if not peak_profile_matches or status_monitor is None or peak_processing_deadline is None:
            quality["peak_200_done_within_180_seconds"] = _quality_assessment(
                "INCONCLUSIVE",
                "A monitored Peak Load run with 200 receipts is required.",
                measured_value=done_by_peak_deadline,
                threshold="200 done within 180 seconds",
            )
        elif status_monitor.polling_error_category is not None:
            quality["peak_200_done_within_180_seconds"] = _quality_assessment(
                "INCONCLUSIVE",
                "Status monitoring ended before processing could be evaluated.",
                measured_value=processing_metrics.done_within_deadline,
                threshold="200 done within 180 seconds",
            )
        elif (
            processing_metrics.conflicting_terminal_failures
            or processing_metrics.failed_records
            or processing_metrics.duplicate_records
        ):
            quality["peak_200_done_within_180_seconds"] = _quality_assessment(
                "FAIL",
                "At least one receipt has a confirmed failed or duplicate terminal status.",
                measured_value=done_by_peak_deadline,
                threshold="200 done within 180 seconds",
            )
        elif processing_metrics.conflicts:
            quality["peak_200_done_within_180_seconds"] = _quality_assessment(
                "INCONCLUSIVE",
                "Conflicting status observations prevent an unambiguous result.",
                measured_value=done_by_peak_deadline,
                threshold="200 done within 180 seconds",
            )
        elif (
            not upload_indices_complete
            or not status_indices_complete
            or not status_linkage_complete
        ):
            quality["peak_200_done_within_180_seconds"] = _quality_assessment(
                "INCONCLUSIVE",
                "Upload indices, status indices, or their receipt-ID linkage are incomplete.",
                measured_value=done_by_peak_deadline,
                threshold="200 done within 180 seconds",
            )
        elif done_by_peak_deadline == 200 and len(monitoring_records) == 200:
            quality["peak_200_done_within_180_seconds"] = _quality_assessment(
                "PASS",
                "All 200 receipts were observed as done by the processing deadline.",
                measured_value=done_by_peak_deadline,
                threshold="200 within 180 seconds",
            )
        elif (
            processing_metrics.failed_records
            or processing_metrics.duplicate_records
            or (len(monitoring_records) == 200 and monitor_stop_reason == "all_terminal")
            or (
                monitor_stop_reason == "processing_deadline"
                and status_monitor.processing_timeout_seconds >= 180.0
            )
        ):
            quality["peak_200_done_within_180_seconds"] = _quality_assessment(
                "FAIL",
                "The complete processing target was not observed by the deadline.",
                measured_value=done_by_peak_deadline,
                threshold="200 done within 180 seconds",
            )
        elif (
            monitor_stop_reason == "processing_deadline"
            and status_monitor.processing_timeout_seconds < 180.0
        ):
            quality["peak_200_done_within_180_seconds"] = _quality_assessment(
                "INCONCLUSIVE",
                "Monitoring ended before the 180-second target deadline.",
                measured_value=done_by_peak_deadline,
                threshold="200 done within 180 seconds",
            )
        else:
            quality["peak_200_done_within_180_seconds"] = _quality_assessment(
                "INCONCLUSIVE",
                "Status observations are incomplete.",
                measured_value=processing_metrics.done_within_deadline,
                threshold="200 done within 180 seconds",
            )

        peak_api = api_metrics["peak_window"]
        if not peak_profile_matches:
            quality["peak_api_p95_below_1_second"] = _quality_assessment(
                "INCONCLUSIVE",
                "The original Peak profile (200 receipts, 4 starts/s, "
                "concurrency 10, 60s) is required.",
                measured_value=peak_api.latency.p95_seconds,
                threshold="< 1 second",
            )
        elif peak_api.failed_count:
            quality["peak_api_p95_below_1_second"] = _quality_assessment(
                "FAIL",
                "Peak-window API requests failed; latency alone is insufficient.",
                measured_value=peak_api.latency.p95_seconds,
                threshold="< 1 second and no failed API requests",
            )
        elif (
            peak_expected_post_count is None
            or peak_expected_post_count == 0
            or peak_observed_post_count != peak_expected_post_count
            or peak_api.request_count == 0
            or peak_api.missing_start_time_count
            or peak_api.missing_elapsed_count
        ):
            post_measurement_detail = (
                "unavailable"
                if peak_expected_post_count is None or peak_observed_post_count is None
                else (
                    f"{peak_observed_post_count}/{peak_expected_post_count} expected "
                    f"POST measurements; {peak_missing_post_count} missing, "
                    f"{peak_unexpected_post_count} unexpected"
                )
            )
            quality["peak_api_p95_below_1_second"] = _quality_assessment(
                "INCONCLUSIVE",
                "Peak-window API latency samples are missing or incomplete; "
                f"POST measurements: {post_measurement_detail}.",
                measured_value=peak_api.latency.p95_seconds,
                threshold="< 1 second",
            )
        elif peak_api.latency.p95_seconds is not None and peak_api.latency.p95_seconds < 1:
            quality["peak_api_p95_below_1_second"] = _quality_assessment(
                "PASS",
                "All measured peak-window API calls succeeded and p95 is below one second.",
                measured_value=peak_api.latency.p95_seconds,
                threshold="< 1 second",
            )
        else:
            quality["peak_api_p95_below_1_second"] = _quality_assessment(
                "FAIL",
                "Peak-window API p95 is not strictly below one second.",
                measured_value=peak_api.latency.p95_seconds,
                threshold="< 1 second",
            )
    else:
        if (
            processing_metrics.conflicting_terminal_failures
            or processing_metrics.failed_records
            or processing_metrics.duplicate_records
        ):
            quality["smoke_functional_check"] = _quality_assessment(
                "FAIL",
                "At least one smoke-test receipt has a confirmed failed or "
                "duplicate terminal status.",
            )
        elif processing_metrics.conflicts:
            quality["smoke_functional_check"] = _quality_assessment(
                "INCONCLUSIVE", "Conflicting status observations prevent an unambiguous result."
            )
        elif (
            not upload_indices_complete
            or not status_indices_complete
            or not status_linkage_complete
        ):
            quality["smoke_functional_check"] = _quality_assessment(
                "INCONCLUSIVE",
                "Smoke-test upload indices, status indices, or their receipt-ID "
                "linkage are incomplete.",
            )
        elif any(not result.upload_succeeded for result in upload_results) or (
            processing_metrics.failed_records or processing_metrics.duplicate_records
        ):
            quality["smoke_functional_check"] = _quality_assessment(
                "FAIL", "At least one smoke-test upload or receipt processing failed."
            )
        elif len(processing_metrics.done_records) == config.receipt_count:
            quality["smoke_functional_check"] = _quality_assessment(
                "PASS", "All smoke-test receipts were uploaded and observed as done."
            )
        else:
            quality["smoke_functional_check"] = _quality_assessment(
                "INCONCLUSIVE", "Not all smoke-test receipts were observed as done."
            )

    (
        safe_upload_results,
        safe_receipt_results,
        safe_polling_errors,
    ) = _report_result_records(upload_results, monitoring_records, polling_errors)
    data_quality: dict[str, int | list[int] | None] = {
        "missing_upload_results": max(config.receipt_count - len(upload_results), 0),
        "unexpected_upload_results": max(len(upload_results) - config.receipt_count, 0),
        "missing_upload_indices": missing_upload_indices,
        "peak_expected_api_post_measurements": peak_expected_post_count,
        "peak_observed_api_post_measurements": peak_observed_post_count,
        "peak_missing_api_post_measurements": peak_missing_post_count,
        "peak_unexpected_api_post_measurements": peak_unexpected_post_count,
        "missing_status_records": len(missing_record_indices),
        "missing_status_indices": missing_record_indices,
        "status_linkage_mismatches": status_linkage_mismatches,
        "missing_or_unobserved_receipt_ids": processing_metrics.missing_or_unobserved,
        "missing_list_observations": processing_metrics.missing_list_observations,
        "e2e_values_not_measurable": max(
            config.receipt_count - processing_metrics.e2e_stats.count, 0
        ),
        "e2e_temporal_overlaps": processing_metrics.e2e_temporal_overlaps,
        "e2e_missing_observed_at": processing_metrics.e2e_missing_observed_at,
        "e2e_invalid_timestamps": processing_metrics.e2e_invalid_timestamps,
        "e2e_without_confirmed_s3": processing_metrics.e2e_without_confirmed_s3,
        "e2e_linkage_mismatches": processing_metrics.e2e_linkage_mismatches,
        "status_linkage_errors": linkage_error_count,
        "conflicting_terminal_failures": processing_metrics.conflicting_terminal_failures,
        "missing_request_durations": (
            api_metrics["all"].missing_elapsed_count + s3_metrics.missing_elapsed_count
        ),
        "missing_run_start_time": int(run_started_at is None),
        "missing_run_completion_time": int(completed_at is None),
        "invalid_run_duration": int(
            run_duration is None and completed_at is not None and run_started_at is not None
        ),
    }
    configuration: dict[str, int | float | str | None] = {
        "receipt_count": config.receipt_count,
        "max_concurrency": config.max_concurrency,
        "starts_per_second": config.starts_per_second,
        "acceptance_window_seconds": config.acceptance_window_seconds,
        "processing_timeout_seconds": processing_timeout_seconds,
        "request_timeout_seconds": request_timeout_seconds,
        "poll_interval_seconds": (
            status_monitor.poll_interval_seconds if status_monitor is not None else None
        ),
    }
    throughput: dict[str, float | int | None] = {
        "duration_to_last_confirmed_upload_seconds": duration_to_last_upload,
        "duration_to_last_done_observation_seconds": duration_to_last_done,
        "total_run_duration_seconds": run_duration,
        "confirmed_uploads_per_second": upload_throughput,
        "done_receipts_per_second": processed_throughput,
        "upload_failure_rate_percent": upload_failure_rate,
        "planned_receipts_not_done_by_deadline_percent": not_processed_share,
    }
    return E2ELoadTestReport(
        run_id=config.run_id,
        profile=config.profile,
        configuration=configuration,
        expected_receipts=config.receipt_count,
        timing={
            "run_started_at": run_started_at,
            "completed_at": completed_at,
            "acceptance_deadline_at": acceptance_deadline_at,
            "processing_deadline_at": processing_deadline_at,
            "load_spike_window_start_at": run_started_at,
            "load_spike_window_end_at": acceptance_deadline_at,
        },
        file_sizes_bytes=tuple(
            result.size_bytes for result in sorted(upload_results, key=lambda item: item.index)
        ),
        upload_summary=upload_summary,
        processing_summary=processing_summary,
        api_request_metrics=api_metrics,
        s3_put_metrics=s3_metrics,
        e2e_processing_latency=processing_metrics.e2e_stats,
        throughput=throughput,
        quality_assessments=quality,
        data_quality=data_quality,
        upload_results=safe_upload_results,
        receipt_results=safe_receipt_results,
        polling_errors=safe_polling_errors,
        measurement_definitions=(
            "E2E latency is first observed done minus confirmed S3 PUT completion; "
            "it includes polling and API response delay.",
            "Nearest-rank p95 is sorted_samples[ceil(0.95 * n) - 1].",
            "API peak window is [run start, acceptance deadline); failed API attempts "
            "with valid durations remain in latency statistics.",
            "Confirmed-upload throughput uses run start through the last confirmed "
            "S3 PUT; done throughput uses run start through the last first-done observation.",
            "Without an explicit completion timestamp, total duration ends at the "
            "latest captured upload, request, status, or monitor-finish event.",
            "Status conflicts are detectable only when both conflicting values are "
            "observed during the actual polling period.",
            "DLQ/Textract-throttling status is not evaluated; it requires CloudWatch evidence.",
        ),
    )


EXIT_OK = 0
EXIT_TARGETS_NOT_MET = 1
EXIT_CONFIGURATION_ERROR = 2
EXIT_SAFETY_BLOCKED = 3
EXIT_EXECUTION_ERROR = 4


class LiveModeBlockedError(Exception):
    pass


def run_e2e_load_test(
    config: E2ELoadTestConfig,
    household_id: str,
    http_client: E2ELoadTestClient,
    *,
    processing_timeout_seconds: float = 180.0,
    poll_interval_seconds: float = 1.0,
    request_timeout_seconds: float = 10.0,
    clock: Callable[[], float] = time.perf_counter,
    sleep: Callable[[float], None] = time.sleep,
) -> E2ELoadTestReport:
    receipts = tuple(
        generate_test_receipt(config.run_id, index) for index in range(config.receipt_count)
    )
    monitor = ReceiptStatusMonitor(
        http_client,
        household_id,
        poll_interval_seconds=poll_interval_seconds,
        processing_timeout_seconds=processing_timeout_seconds,
        clock=clock,
    )
    uploads = run_upload_load(
        http_client,
        household_id,
        receipts,
        config,
        clock=clock,
        sleep=sleep,
        status_monitor=monitor,
    )
    return build_e2e_load_test_report(
        config,
        uploads,
        http_client.timings,
        status_monitor=monitor,
        request_timeout_seconds=request_timeout_seconds,
    )


def _build_cli_config(args: argparse.Namespace, profile: str, run_id: str) -> E2ELoadTestConfig:
    if profile == "normal":
        return E2ELoadTestConfig.normal_load(
            run_id,
            receipt_count=args.count if args.count is not None else 20,
            max_concurrency=args.concurrency if args.concurrency is not None else 5,
            starts_per_second=args.rate if args.rate is not None else 1.0,
            acceptance_window_seconds=(
                args.acceptance_timeout if args.acceptance_timeout is not None else 60.0
            ),
        )

    config = (
        E2ELoadTestConfig.smoke_test(run_id)
        if profile == "smoke"
        else E2ELoadTestConfig.peak_load(run_id)
    )
    for argument, field_name in (
        (args.count, "receipt_count"),
        (args.rate, "starts_per_second"),
        (args.concurrency, "max_concurrency"),
        (args.acceptance_timeout, "acceptance_window_seconds"),
    ):
        if argument is not None and argument != getattr(config, field_name):
            raise ClientInputError(
                f"The {profile} profile has fixed {field_name.replace('_', ' ')}."
            )
    return config


def _validate_cli_settings(args: argparse.Namespace) -> None:
    for value, label in (
        (args.processing_timeout, "Processing timeout"),
        (args.poll_interval, "Polling interval"),
        (args.request_timeout, "Request timeout"),
    ):
        if not _is_finite_number(value) or value <= 0:
            raise ClientInputError(f"{label} must be finite and positive.")
    if args.household_id is not None:
        try:
            if str(UUID(args.household_id)) != args.household_id.lower():
                raise ValueError
        except AttributeError, ValueError:
            raise ClientInputError("Household ID must be a canonical UUID.") from None
    if args.api_url is not None:
        E2EHttpClient._validate_api_base_url(args.api_url)


def _profile_configuration_matches(config: E2ELoadTestConfig) -> bool:
    if config.profile == "smoke_test":
        return config.receipt_count == 3
    if config.profile == "normal_load":
        return config.receipt_count == 20
    return (
        config.receipt_count == 200
        and config.starts_per_second == 4.0
        and config.max_concurrency == 10
        and config.acceptance_window_seconds == 60.0
    )


def _profile_matches_target(config: E2ELoadTestConfig, processing_timeout_seconds: float) -> bool:
    return _profile_configuration_matches(config) and (
        config.profile != "peak_load" or processing_timeout_seconds == 180.0
    )


def _dry_run_plan(
    config: E2ELoadTestConfig,
    args: argparse.Namespace,
) -> dict[str, object]:
    sample_size = generate_test_receipt(config.run_id, 0).size_bytes
    return {
        "dry_run": True,
        "run_id": config.run_id,
        "profile": {
            "smoke_test": "smoke",
            "normal_load": "normal",
            "peak_load": "peak",
        }[config.profile],
        "profile_matches_target": _profile_matches_target(config, args.processing_timeout),
        "receipt_count": config.receipt_count,
        "starts_per_second": config.starts_per_second,
        "max_concurrency": config.max_concurrency,
        "acceptance_timeout_seconds": config.acceptance_window_seconds,
        "processing_timeout_seconds": args.processing_timeout,
        "poll_interval_seconds": args.poll_interval,
        "request_timeout_seconds": args.request_timeout,
        "test_data_estimate": {
            "sample_png_bytes": sample_size,
            "estimated_total_bytes": sample_size * config.receipt_count,
            "basis": "one locally generated PNG sample multiplied by receipt count",
        },
        "target_configured": {
            "api_url": args.api_url is not None,
            "household_id": args.household_id is not None,
        },
        "quality_assessment": "NOT_EVALUATED",
        "safety": [
            "A dedicated dev household is required.",
            "The deployed stack must be technically verified as bonbon-dev.",
            "The deployed worker must be technically verified to use Damian's Textract mock.",
        ],
        "note": (
            "No token was requested; no uploads, network requests, or AWS "
            "measurements were performed."
        ),
    }


def _write_new_json_file(path: Path, payload: str) -> None:
    with path.open("x", encoding="utf-8") as output:
        output.write(payload)
        output.write("\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safely prepare or run Bonbon's AWS end-to-end receipt load test."
    )
    parser.add_argument("--profile", choices=("smoke", "normal", "peak"))
    parser.add_argument("--count", type=int)
    parser.add_argument("--rate", type=float)
    parser.add_argument("--concurrency", type=int)
    parser.add_argument("--acceptance-timeout", type=float)
    parser.add_argument("--processing-timeout", type=float, default=180.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--request-timeout", type=float, default=10.0)
    parser.add_argument("--run-id")
    parser.add_argument("--household-id")
    parser.add_argument("--api-url")
    parser.add_argument("--output", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument(
        "--confirm-start",
        action="store_true",
        help="Explicit consent; this alone cannot enable live mode.",
    )
    return parser


def _require_verified_live_target() -> None:
    raise LiveModeBlockedError(
        "Live network mode is disabled: this code cannot technically verify the "
        "bonbon-dev stack or the deployed Textract mock. HTTPS, a URL, and manual "
        "confirmation are not sufficient evidence."
    )


def _report_exit_code(report: E2ELoadTestReport) -> int:
    applicable = {
        "smoke_test": ("smoke_functional_check",),
        "normal_load": ("normal_e2e_p95_10_seconds",),
        "peak_load": (
            "peak_200_uploads_within_60_seconds",
            "peak_200_done_within_180_seconds",
            "peak_api_p95_below_1_second",
            "dlq_textract_throttling",
        ),
    }[report.profile]
    return (
        EXIT_OK
        if all(report.quality_assessments[name].status == "PASS" for name in applicable)
        else EXIT_TARGETS_NOT_MET
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    clock: Callable[[], float] = time.perf_counter,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        if args.profile is None and not args.dry_run:
            raise LiveModeBlockedError(
                "Choose a profile explicitly; without it, live testing is disabled."
            )
        _validate_cli_settings(args)
        profile = args.profile or "normal"
        run_id = args.run_id if args.run_id is not None else uuid4().hex
        config = _build_cli_config(args, profile, run_id)

        if args.dry_run:
            plan = _dry_run_plan(config, args)
            payload = json.dumps(plan, indent=2, sort_keys=True, allow_nan=False)
            print(payload)
            if args.output is not None:
                _write_new_json_file(args.output, payload)
            return EXIT_OK

        if not args.confirm_start:
            raise LiveModeBlockedError(
                "Live testing requires --confirm-start, and technical target verification."
            )
        if args.household_id is None or args.api_url is None:
            raise ClientInputError("Live mode requires --household-id and --api-url.")
        _require_verified_live_target()

        token = getpass.getpass("Cognito ID token: ")
        http_client = E2EHttpClient(
            args.api_url,
            token,
            timeout_seconds=args.request_timeout,
            clock=clock,
        )
        del token
        report = run_e2e_load_test(
            config,
            args.household_id,
            http_client,
            processing_timeout_seconds=args.processing_timeout,
            poll_interval_seconds=args.poll_interval,
            request_timeout_seconds=args.request_timeout,
            clock=clock,
            sleep=sleep,
        )
        print(report.summary_text())
        print("DLQ/Textract-throttling: NOT_EVALUATED; a later CloudWatch check is required.")
        if args.output is not None:
            _write_new_json_file(args.output, report.to_json())
        return _report_exit_code(report)
    except LiveModeBlockedError as error:
        print(f"Safety block: {error}", file=sys.stderr)
        return EXIT_SAFETY_BLOCKED
    except ClientInputError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return EXIT_CONFIGURATION_ERROR
    except OSError:
        print(
            "Could not write JSON output (the file may exist or the path may be inaccessible).",
            file=sys.stderr,
        )
        return EXIT_EXECUTION_ERROR
    except E2ELoadTestError, EOFError:
        print("The E2E load-test execution failed.", file=sys.stderr)
        return EXIT_EXECUTION_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
