import hashlib
import http.client
import io
import json
import runpy
import socket
import struct
import sys
import threading
import time
import urllib.request
import zlib
from collections import deque
from collections.abc import Callable
from dataclasses import replace
from email.message import Message
from itertools import pairwise
from pathlib import Path
from types import TracebackType
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request
from uuid import UUID

import pytest
import run_e2e_load_test as e2e_runner
from bonbon.receipts.models import MAX_UPLOAD_BYTES, ReceiptSummary
from run_e2e_load_test import (
    EXIT_CONFIGURATION_ERROR,
    EXIT_EXECUTION_ERROR,
    EXIT_OK,
    EXIT_SAFETY_BLOCKED,
    EXIT_TARGETS_NOT_MET,
    ClientInputError,
    E2EHttpClient,
    E2ELoadTestConfig,
    GeneratedTestReceipt,
    HttpResponse,
    HttpStatusError,
    InvalidResponseError,
    NetworkRequestError,
    QualityAssessment,
    ReceiptStatusMonitor,
    ReceiptUploadGrant,
    RequestTimeoutError,
    RequestTiming,
    UploadAttemptResult,
    UrllibTransport,
    _NoRedirectHandler,
    _report_exit_code,
    build_e2e_load_test_report,
    generate_test_receipt,
    main,
    nearest_rank_percentile,
    run_upload_load,
    runtime_statistics,
    upload_test_receipt,
)

API_BASE_URL = "https://api.example.test/api"
HOUSEHOLD_ID = "00000000-0000-0000-0000-000000000001"
RECEIPT_ID = "00000000-0000-0000-0000-000000000002"
ID_TOKEN = "synthetic-id-token"
UPLOAD_URL = "https://s3.example.test/upload"
FILE_BYTES = b"synthetic receipt bytes"
UPLOAD_HEADERS = {
    "Content-Type": "image/jpeg",
    "x-amz-tagging": "status=pending",
}


class FakeTransport:
    def __init__(self, *responses: HttpResponse | Exception) -> None:
        self.responses = deque(responses)
        self.requests: list[tuple[Request, float]] = []

    def send(self, request: Request, timeout: float) -> HttpResponse:
        self.requests.append((request, timeout))
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response


class SimulatedResponse:
    def __init__(self, status: int, body: bytes = b"", read_error: Exception | None = None) -> None:
        self.status = status
        self._body = body
        self._read_error = read_error

    def __enter__(self) -> SimulatedResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        if self._read_error is not None:
            raise self._read_error
        return self._body


class FakeClock:
    def __init__(self, start_at: float = 100.0) -> None:
        self._now = start_at
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            return self._now

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._now += seconds

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)
        time.sleep(0)


class FakeReceiptClient:
    def __init__(
        self,
        *,
        create_error: Exception | None = None,
        upload_error: Exception | None = None,
        after_create: Callable[[], None] | None = None,
        during_upload: Callable[[ReceiptUploadGrant, bytes], None] | None = None,
    ) -> None:
        self.create_error = create_error
        self.upload_error = upload_error
        self.after_create = after_create
        self.during_upload = during_upload
        self.create_calls: list[tuple[str, str, bytes]] = []
        self.upload_calls: list[str] = []
        self.events: list[tuple[str, str]] = []
        self.timings: tuple[RequestTiming, ...] = ()
        self._lock = threading.Lock()

    def create_receipt(
        self, household_id: str, content_type: str, file_bytes: bytes
    ) -> ReceiptUploadGrant:
        with self._lock:
            self.create_calls.append((household_id, content_type, file_bytes))
            receipt_id = f"synthetic-receipt-{len(self.create_calls)}"
            self.events.append(("create", receipt_id))
        if self.create_error is not None:
            raise self.create_error
        if self.after_create is not None:
            self.after_create()
        return ReceiptUploadGrant(
            receipt_id=receipt_id,
            size_bytes=len(file_bytes),
            expires_in=300,
            upload_url=UPLOAD_URL,
            upload_headers=UPLOAD_HEADERS,
        )

    def upload_file(self, grant: ReceiptUploadGrant, file_bytes: bytes) -> None:
        with self._lock:
            self.upload_calls.append(grant.receipt_id)
            self.events.append(("upload", grant.receipt_id))
        if self.during_upload is not None:
            self.during_upload(grant, file_bytes)
        if self.upload_error is not None:
            raise self.upload_error


class FakeMonitoringClient(FakeReceiptClient):
    def __init__(
        self,
        responses: tuple[dict[str, ReceiptSummary] | Exception, ...] = (),
        *,
        default_response: dict[str, ReceiptSummary] | None = None,
        on_list: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.responses = deque(responses)
        self.default_response = default_response or {}
        self.on_list = on_list
        self.list_calls = 0
        self.active_list_calls = 0
        self.max_active_list_calls = 0

    def list_receipts(self, household_id: str) -> dict[str, ReceiptSummary]:
        with self._lock:
            self.list_calls += 1
            self.active_list_calls += 1
            self.max_active_list_calls = max(self.max_active_list_calls, self.active_list_calls)
        try:
            if self.on_list is not None:
                self.on_list()
            response = self.responses.popleft() if self.responses else self.default_response
            if isinstance(response, Exception):
                raise response
            return response
        finally:
            with self._lock:
                self.active_list_calls -= 1


class AdvancingMonitorWait:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.timeouts: list[float] = []

    def __call__(self, event: threading.Event, timeout: float) -> bool:
        self.timeouts.append(timeout)
        if event.is_set():
            return True
        self.clock.advance(timeout)
        return event.is_set()


@pytest.fixture(autouse=True)
def prevent_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_network(*_: Any, **__: Any) -> None:
        raise AssertionError("Tests must not open network connections.")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", fail_network)
    monkeypatch.setattr(socket.socket, "connect", fail_network)
    monkeypatch.setattr(socket, "create_connection", fail_network)


def json_response(data: object, status_code: int = 200) -> HttpResponse:
    return HttpResponse(status_code, json.dumps(data).encode("utf-8"))


def receipt_upload_response(**overrides: object) -> dict[str, object]:
    return {
        "receipt_id": RECEIPT_ID,
        "upload_url": UPLOAD_URL,
        "upload_headers": UPLOAD_HEADERS,
        "expires_in": 300,
        **overrides,
    }


def receipt_summary(receipt_id: str, status: str) -> dict[str, object]:
    return {
        "id": receipt_id,
        "status": status,
        "store": None,
        "purchase_date": None,
        "total_rappen": None,
        "uploaded_by_name": None,
        "created_at": "2026-11-24T12:00:00Z",
        "possible_duplicate": False,
    }


def client(
    transport: FakeTransport,
    *,
    clock: Callable[[], float] = time.perf_counter,
    timeout_seconds: float = 10.0,
) -> E2EHttpClient:
    return E2EHttpClient(
        API_BASE_URL,
        ID_TOKEN,
        transport=transport,
        clock=clock,
        timeout_seconds=timeout_seconds,
    )


def request_headers(request: Request) -> dict[str, str]:
    return {name.lower(): value for name, value in request.header_items()}


def parse_png_chunks(image: bytes) -> list[tuple[bytes, bytes]]:
    signature = b"\x89PNG\r\n\x1a\n"
    assert image.startswith(signature)
    position = len(signature)
    chunks: list[tuple[bytes, bytes]] = []
    while position < len(image):
        length = struct.unpack_from(">I", image, position)[0]
        position += 4
        chunk_type = image[position : position + 4]
        position += 4
        data = image[position : position + length]
        position += length
        expected_crc = struct.unpack_from(">I", image, position)[0]
        position += 4
        assert expected_crc == zlib.crc32(data, zlib.crc32(chunk_type)) & 0xFFFFFFFF
        chunks.append((chunk_type, data))
        if chunk_type == b"IEND":
            break
    assert position == len(image)
    return chunks


def small_test_receipts(run_id: str, count: int) -> list[GeneratedTestReceipt]:
    return [generate_test_receipt(run_id, index, width=8, height=8) for index in range(count)]


def receipt_status_map(*statuses: tuple[str, str]) -> dict[str, ReceiptSummary]:
    return {
        receipt_id: ReceiptSummary.model_validate(receipt_summary(receipt_id, status))
        for receipt_id, status in statuses
    }


def successful_upload_result(
    index: int,
    receipt_id: str,
    *,
    planned_start_at: float = 100.0,
    actual_start_at: float | None = 100.0,
    s3_completed_at: float = 100.5,
) -> UploadAttemptResult:
    receipt = generate_test_receipt("monitor-result", index, width=8, height=8)
    return UploadAttemptResult(
        index=index,
        sha256=receipt.sha256,
        size_bytes=receipt.size_bytes,
        receipt_id=receipt_id,
        planned_start_at=planned_start_at,
        actual_start_at=actual_start_at,
        s3_completed_at=s3_completed_at,
        finished_at=s3_completed_at,
        upload_succeeded=True,
        failure_category=None,
    )


def finished_monitor(
    http_client: FakeMonitoringClient,
    clock: FakeClock,
    receipts: tuple[tuple[int, str], ...],
    *,
    upload_results: tuple[UploadAttemptResult, ...] = (),
    poll_interval_seconds: float = 1.0,
    processing_timeout_seconds: float = 10.0,
) -> tuple[ReceiptStatusMonitor, AdvancingMonitorWait]:
    wait = AdvancingMonitorWait(clock)
    monitor = ReceiptStatusMonitor(
        http_client,
        HOUSEHOLD_ID,
        poll_interval_seconds=poll_interval_seconds,
        processing_timeout_seconds=processing_timeout_seconds,
        clock=clock,
        wait=wait,
    )
    for index, receipt_id in receipts:
        monitor.register_receipt(index, receipt_id)
    monitor.finish_upload_phase(upload_results)
    monitor.start(clock())
    monitor.join()
    return monitor, wait


def report_upload_results(
    count: int,
    *,
    start_at: float = 100.0,
    late_index: int | None = None,
    failed_index: int | None = None,
    uncertain_index: int | None = None,
) -> tuple[UploadAttemptResult, ...]:
    results = []
    for index in range(count):
        receipt_id = f"synthetic-receipt-{index}"
        receipt = generate_test_receipt("report-run", index, width=8, height=8)
        if index == failed_index:
            results.append(
                UploadAttemptResult(
                    index=index,
                    sha256=receipt.sha256,
                    size_bytes=receipt.size_bytes,
                    receipt_id=receipt_id,
                    planned_start_at=start_at,
                    actual_start_at=start_at,
                    s3_completed_at=None,
                    finished_at=start_at + 0.5,
                    upload_succeeded=False,
                    failure_category="s3_http_error",
                )
            )
        elif index == uncertain_index:
            results.append(
                UploadAttemptResult(
                    index=index,
                    sha256=receipt.sha256,
                    size_bytes=receipt.size_bytes,
                    receipt_id=receipt_id,
                    planned_start_at=start_at,
                    actual_start_at=start_at,
                    s3_completed_at=None,
                    finished_at=start_at + 0.5,
                    upload_succeeded=False,
                    failure_category="s3_timeout",
                    outcome_uncertain=True,
                )
            )
        else:
            completed_at = start_at + (61.0 if index == late_index else 0.25)
            results.append(
                UploadAttemptResult(
                    index=index,
                    sha256=receipt.sha256,
                    size_bytes=receipt.size_bytes,
                    receipt_id=receipt_id,
                    planned_start_at=start_at,
                    actual_start_at=start_at,
                    s3_completed_at=completed_at,
                    finished_at=completed_at,
                    upload_succeeded=True,
                    failure_category=None,
                )
            )
    return tuple(results)


def report_status_monitor(
    results: tuple[UploadAttemptResult, ...],
    clock: FakeClock,
    *,
    statuses: tuple[str, ...] | None = None,
    on_list: Callable[[], None] | None = None,
    processing_timeout_seconds: float = 180.0,
) -> ReceiptStatusMonitor:
    receipt_ids = tuple(
        (result.index, result.receipt_id) for result in results if result.receipt_id is not None
    )
    receipt_statuses = statuses or tuple("done" for _ in receipt_ids)
    response = receipt_status_map(
        *(
            (receipt_id, status)
            for (_, receipt_id), status in zip(receipt_ids, receipt_statuses, strict=True)
        )
    )
    monitor, _ = finished_monitor(
        FakeMonitoringClient((response,), on_list=on_list),
        clock,
        receipt_ids,
        upload_results=results,
        processing_timeout_seconds=processing_timeout_seconds,
    )
    return monitor


def test_create_receipt_sends_expected_body_and_id_token_header() -> None:
    transport = FakeTransport(json_response(receipt_upload_response(), 201))
    result = client(transport).create_receipt(HOUSEHOLD_ID, "image/jpeg", FILE_BYTES)

    request, timeout = transport.requests[0]
    headers = request_headers(request)
    assert request.method == "POST"
    assert urlsplit(request.full_url).path == f"/api/households/{HOUSEHOLD_ID}/receipts"
    assert headers["authorization"] == ID_TOKEN
    assert not headers["authorization"].startswith("Bearer ")
    assert headers["content-type"] == "application/json"
    assert isinstance(request.data, bytes)
    assert json.loads(request.data) == {
        "content_type": "image/jpeg",
        "size_bytes": len(FILE_BYTES),
    }
    assert timeout == 10.0
    assert result.receipt_id == RECEIPT_ID
    assert result.size_bytes == len(FILE_BYTES)
    assert result.expires_in == 300


def test_upload_uses_backend_headers_bytes_and_actual_content_length_without_token() -> None:
    transport = FakeTransport(
        json_response(receipt_upload_response(), 201),
        HttpResponse(204, b""),
    )
    http_client = client(transport)
    grant = http_client.create_receipt(HOUSEHOLD_ID, "image/jpeg", FILE_BYTES)

    http_client.upload_file(grant, FILE_BYTES)

    request, _ = transport.requests[1]
    headers = request_headers(request)
    assert request.method == "PUT"
    assert request.data == FILE_BYTES
    assert headers["content-type"] == UPLOAD_HEADERS["Content-Type"]
    assert headers["x-amz-tagging"] == UPLOAD_HEADERS["x-amz-tagging"]
    assert headers["content-length"] == str(len(FILE_BYTES))
    assert "authorization" not in headers
    assert "proxy-authorization" not in headers
    assert http_client.timings[-1].kind == "s3"
    assert http_client.timings[-1].status_code == 204


def test_upload_accepts_any_2xx_response() -> None:
    transport = FakeTransport(
        json_response(receipt_upload_response(), 201),
        HttpResponse(201, b""),
    )
    http_client = client(transport)
    grant = http_client.create_receipt(HOUSEHOLD_ID, "image/jpeg", FILE_BYTES)

    http_client.upload_file(grant, FILE_BYTES)

    assert len(transport.requests) == 2


def test_status_list_maps_all_backend_statuses_without_month_filter() -> None:
    statuses = ("uploaded", "done", "failed", "duplicate")
    response = {
        "receipts": [
            receipt_summary(f"receipt-{index}", status) for index, status in enumerate(statuses)
        ]
    }
    transport = FakeTransport(json_response(response))

    receipts = client(transport).list_receipts(HOUSEHOLD_ID)

    request, _ = transport.requests[0]
    assert request.method == "GET"
    assert urlsplit(request.full_url).path == f"/api/households/{HOUSEHOLD_ID}/receipts"
    assert urlsplit(request.full_url).query == ""
    assert request_headers(request)["authorization"] == ID_TOKEN
    assert [receipts[f"receipt-{index}"].status for index in range(4)] == list(statuses)


@pytest.mark.parametrize("status_code", [401, 403, 404, 422, 429, 500, 503])
def test_api_http_errors_are_safe_and_not_retried(status_code: int) -> None:
    sensitive_body = f"{ID_TOKEN} {UPLOAD_URL}"
    transport = FakeTransport(HttpResponse(status_code, sensitive_body.encode()))
    http_client = client(transport)

    with pytest.raises(HttpStatusError) as error:
        http_client.create_receipt(HOUSEHOLD_ID, "image/jpeg", FILE_BYTES)

    assert error.value.status_code == status_code
    assert ID_TOKEN not in str(error.value)
    assert UPLOAD_URL not in str(error.value)
    assert len(transport.requests) == 1
    assert http_client.timings[0].status_code == status_code


def test_s3_http_error_is_safe_and_not_retried() -> None:
    transport = FakeTransport(
        json_response(receipt_upload_response(), 201),
        HttpResponse(503, f"{ID_TOKEN} {UPLOAD_URL}".encode()),
    )
    http_client = client(transport)
    grant = http_client.create_receipt(HOUSEHOLD_ID, "image/jpeg", FILE_BYTES)

    with pytest.raises(HttpStatusError) as error:
        http_client.upload_file(grant, FILE_BYTES)

    assert error.value.status_code == 503
    assert ID_TOKEN not in str(error.value)
    assert UPLOAD_URL not in str(error.value)
    assert len(transport.requests) == 2


@pytest.mark.parametrize(
    ("failure", "error_type"),
    [
        (TimeoutError("synthetic timeout"), RequestTimeoutError),
        (URLError("synthetic network failure"), NetworkRequestError),
    ],
)
def test_network_and_timeout_errors_are_sanitized_and_timed(
    failure: Exception, error_type: type[Exception]
) -> None:
    transport = FakeTransport(failure)
    http_client = client(transport)

    with pytest.raises(error_type) as error:
        http_client.list_receipts(HOUSEHOLD_ID)

    assert ID_TOKEN not in str(error.value)
    assert UPLOAD_URL not in str(error.value)
    assert len(http_client.timings) == 1
    assert http_client.timings[0].status_code is None


@pytest.mark.parametrize(
    "failure",
    [
        http.client.IncompleteRead(b"sensitive response fragment", 100),
        http.client.BadStatusLine("sensitive malformed status line"),
    ],
)
def test_client_sanitizes_http_exceptions_from_custom_transport(
    failure: Exception,
) -> None:
    http_client = client(FakeTransport(failure))

    with pytest.raises(NetworkRequestError) as error:
        http_client.list_receipts(HOUSEHOLD_ID)

    assert str(error.value) == "HTTP request failed due to a network error."
    assert "sensitive" not in str(error.value)


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b"\xff",
    ],
)
def test_invalid_api_json_is_rejected_without_echoing_body(body: bytes) -> None:
    transport = FakeTransport(HttpResponse(201, body))
    http_client = client(transport)

    with pytest.raises(InvalidResponseError, match="invalid JSON"):
        http_client.create_receipt(HOUSEHOLD_ID, "image/jpeg", FILE_BYTES)

    assert len(http_client.timings) == 1
    assert http_client.timings[0].error_category == "invalid_response"


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"receipt_id": RECEIPT_ID},
        receipt_upload_response(upload_headers={"Content-Type": "image/jpeg"}),
        receipt_upload_response(upload_url="not-a-url"),
        receipt_upload_response(upload_headers={"Authorization": "synthetic-secret"}),
    ],
)
def test_incomplete_or_unsafe_create_response_is_rejected(response: dict[str, object]) -> None:
    transport = FakeTransport(json_response(response, 201))

    with pytest.raises(InvalidResponseError):
        client(transport).create_receipt(HOUSEHOLD_ID, "image/jpeg", FILE_BYTES)


def test_create_receipt_rejects_exact_duplicate_json_header_names() -> None:
    response_body = (
        b'{"receipt_id":"00000000-0000-0000-0000-000000000002",'
        b'"upload_url":"https://s3.example.test/upload",'
        b'"upload_headers":{"Content-Type":"image/jpeg",'
        b'"Content-Type":"image/png","x-amz-tagging":"status=pending"},'
        b'"expires_in":300}'
    )
    transport = FakeTransport(HttpResponse(201, response_body))

    with pytest.raises(InvalidResponseError, match="invalid JSON"):
        client(transport).create_receipt(HOUSEHOLD_ID, "image/jpeg", FILE_BYTES)


def test_invalid_status_list_response_is_rejected() -> None:
    transport = FakeTransport(
        json_response({"receipts": [receipt_summary(RECEIPT_ID, "processing")]})
    )
    http_client = client(transport)

    with pytest.raises(InvalidResponseError):
        http_client.list_receipts(HOUSEHOLD_ID)

    assert len(http_client.timings) == 1
    assert http_client.timings[0].error_category == "invalid_response"


def test_missing_status_fields_are_rejected() -> None:
    transport = FakeTransport(json_response({"receipts": [{"id": RECEIPT_ID}]}))

    with pytest.raises(InvalidResponseError):
        client(transport).list_receipts(HOUSEHOLD_ID)


def test_upload_rejects_wrong_size_and_signed_content_length() -> None:
    transport = FakeTransport(
        json_response(receipt_upload_response(), 201),
        json_response(
            receipt_upload_response(upload_headers={**UPLOAD_HEADERS, "Content-Length": "1"}),
            201,
        ),
    )
    http_client = client(transport)
    grant = http_client.create_receipt(HOUSEHOLD_ID, "image/jpeg", FILE_BYTES)

    with pytest.raises(ClientInputError, match="do not match"):
        http_client.upload_file(grant, b"different length")

    with pytest.raises(InvalidResponseError, match="Content-Length"):
        http_client.create_receipt(HOUSEHOLD_ID, "image/jpeg", FILE_BYTES)


def test_timing_uses_injected_monotonic_clock_and_distinguishes_api_from_s3() -> None:
    ticks = iter([10.0, 10.25, 20.0, 20.75])
    transport = FakeTransport(
        json_response(receipt_upload_response(), 201),
        HttpResponse(200, b""),
    )
    http_client = client(transport, clock=lambda: next(ticks))
    grant = http_client.create_receipt(HOUSEHOLD_ID, "image/jpeg", FILE_BYTES)
    http_client.upload_file(grant, FILE_BYTES)

    assert [(item.kind, item.method, item.elapsed_seconds) for item in http_client.timings] == [
        ("api", "POST", 0.25),
        ("s3", "PUT", 0.75),
    ]
    assert [item.started_at for item in http_client.timings] == [10.0, 20.0]


def test_redirect_handler_does_not_create_a_follow_up_request() -> None:
    handler = _NoRedirectHandler()
    request = Request("https://source.example.test/")

    redirect = handler.redirect_request(
        request,
        object(),
        302,
        "Found",
        {"Location": "https://other.example.test/"},
        "https://other.example.test/",
    )

    assert redirect is None


def test_urllib_transport_returns_redirect_status_without_reading_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def redirect_response(*_: Any, **__: Any) -> Any:
        nonlocal calls
        calls += 1
        raise HTTPError(
            UPLOAD_URL,
            302,
            "Found",
            Message(),
            io.BytesIO(b"sensitive response body"),
        )

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", redirect_response)

    response = UrllibTransport().send(Request(UPLOAD_URL), timeout=1.0)

    assert response.status_code == 302
    assert response.body == b""
    assert calls == 1


def test_urllib_transport_returns_a_simulated_successful_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Request, float]] = []
    simulated_response = SimulatedResponse(200, b"synthetic response")

    def open_response(_opener: object, request: Request, timeout: float) -> SimulatedResponse:
        calls.append((request, timeout))
        return simulated_response

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", open_response)

    request = Request("https://api.example.test/receipts")
    response = UrllibTransport().send(request, timeout=2.5)

    assert response.status_code == 200
    assert response.body == b"synthetic response"
    assert calls == [(request, 2.5)]


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError(f"{UPLOAD_URL}?token={ID_TOKEN}"),
        URLError(TimeoutError(f"{UPLOAD_URL}?token={ID_TOKEN}")),
    ],
)
def test_urllib_transport_sanitizes_timeouts(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    def timeout(*_: Any, **__: Any) -> None:
        raise failure

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", timeout)

    with pytest.raises(RequestTimeoutError) as error:
        UrllibTransport().send(Request(UPLOAD_URL), timeout=1.0)

    assert str(error.value) == "HTTP request timed out."
    assert ID_TOKEN not in str(error.value)
    assert UPLOAD_URL not in str(error.value)


def test_urllib_transport_sanitizes_url_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def url_error(*_: Any, **__: Any) -> None:
        raise URLError(f"{UPLOAD_URL}?token={ID_TOKEN}")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", url_error)

    with pytest.raises(NetworkRequestError) as error:
        UrllibTransport().send(Request(UPLOAD_URL), timeout=1.0)

    assert str(error.value) == "HTTP request failed due to a network error."
    assert ID_TOKEN not in str(error.value)
    assert UPLOAD_URL not in str(error.value)


@pytest.mark.parametrize(
    "read_error",
    [
        http.client.IncompleteRead(b"sensitive response fragment", 100),
        http.client.BadStatusLine("sensitive malformed status line"),
        ConnectionResetError("sensitive connection reset"),
    ],
)
def test_urllib_transport_sanitizes_http_response_read_errors(
    monkeypatch: pytest.MonkeyPatch, read_error: Exception
) -> None:
    def open_response(*_: Any, **__: Any) -> SimulatedResponse:
        return SimulatedResponse(200, read_error=read_error)

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", open_response)

    with pytest.raises(NetworkRequestError) as error:
        UrllibTransport().send(Request(UPLOAD_URL), timeout=1.0)

    assert str(error.value) == "HTTP request failed due to a network error."
    assert "sensitive" not in str(error.value)
    assert UPLOAD_URL not in str(error.value)


def test_urllib_transport_does_not_hide_unexpected_programming_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def programming_error(*_: Any, **__: Any) -> None:
        raise RuntimeError("synthetic programming error")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", programming_error)

    with pytest.raises(RuntimeError, match="synthetic programming error"):
        UrllibTransport().send(Request(UPLOAD_URL), timeout=1.0)


def test_redirect_response_is_an_error_and_is_not_retried() -> None:
    transport = FakeTransport(
        json_response(receipt_upload_response(), 201),
        HttpResponse(302, b""),
    )
    http_client = client(transport)
    grant = http_client.create_receipt(HOUSEHOLD_ID, "image/jpeg", FILE_BYTES)

    with pytest.raises(HttpStatusError) as error:
        http_client.upload_file(grant, FILE_BYTES)

    assert error.value.status_code == 302
    assert len(transport.requests) == 2


def test_direct_script_without_profile_stops_before_any_load_test(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = Path(__file__).with_name("run_e2e_load_test.py")
    monkeypatch.setattr(sys, "argv", [str(script)])

    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(script), run_name="__main__")

    assert error.value.code == EXIT_SAFETY_BLOCKED
    assert "Choose a profile explicitly" in capsys.readouterr().err


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("inf"), float("nan")])
def test_timeout_must_be_finite_and_positive(timeout: float) -> None:
    with pytest.raises(ClientInputError, match="finite positive"):
        E2EHttpClient(API_BASE_URL, ID_TOKEN, timeout_seconds=timeout)


def test_generated_test_receipt_has_a_valid_png_signature() -> None:
    receipt = generate_test_receipt("synthetic-run", 0, width=8, height=6)

    assert receipt.file_bytes.startswith(b"\x89PNG\r\n\x1a\n")


def test_generated_png_chunks_have_valid_crcs_and_decompress() -> None:
    receipt = generate_test_receipt("synthetic-run", 1, width=13, height=7)

    chunks = parse_png_chunks(receipt.file_bytes)
    assert [chunk_type for chunk_type, _ in chunks] == [b"IHDR", b"IDAT", b"IEND"]
    scanlines = zlib.decompress(chunks[1][1])
    assert len(scanlines) == 7 * (1 + 13 * 3)
    assert [scanlines[row * 40] for row in range(7)] == [0] * 7


def test_generated_png_has_configured_dimensions_and_rgb_scanline_layout() -> None:
    receipt = generate_test_receipt("synthetic-run", 2, width=17, height=9)

    header = parse_png_chunks(receipt.file_bytes)[0][1]
    assert struct.unpack(">IIBBBBB", header) == (17, 9, 8, 2, 0, 0, 0)
    assert len(zlib.decompress(parse_png_chunks(receipt.file_bytes)[1][1])) == 9 * (1 + 17 * 3)


def test_default_png_profile_fits_api_limit_and_representative_size_range() -> None:
    receipt = generate_test_receipt("synthetic-run", 3)

    assert 300_000 <= receipt.size_bytes <= 500_000
    assert receipt.size_bytes <= MAX_UPLOAD_BYTES
    assert receipt.size_bytes == len(receipt.file_bytes)


def test_generated_receipt_metadata_matches_actual_png_bytes() -> None:
    receipt = generate_test_receipt("synthetic-run", 4, width=11, height=5)

    assert isinstance(receipt, GeneratedTestReceipt)
    assert receipt.index == 4
    assert receipt.content_type == "image/png"
    assert receipt.size_bytes == len(receipt.file_bytes)
    assert receipt.sha256 == hashlib.sha256(receipt.file_bytes).hexdigest()
    assert "file_bytes=" not in repr(receipt)


def test_two_hundred_receipts_have_distinct_hashes_and_bytes() -> None:
    receipts = [
        generate_test_receipt("synthetic-run", index, width=8, height=8) for index in range(200)
    ]

    assert len({receipt.sha256 for receipt in receipts}) == 200
    assert len({receipt.file_bytes for receipt in receipts}) == 200


def test_generation_is_reproducible_for_the_same_run_and_index() -> None:
    first = generate_test_receipt("stable-run", 19, width=20, height=12)
    second = generate_test_receipt("stable-run", 19, width=20, height=12)

    assert first.file_bytes == second.file_bytes
    assert first.sha256 == second.sha256


def test_generation_changes_for_a_different_run_or_index() -> None:
    original = generate_test_receipt("run-one", 7, width=20, height=12)

    different_run = generate_test_receipt("run-two", 7, width=20, height=12)
    different_index = generate_test_receipt("run-one", 8, width=20, height=12)

    assert original.file_bytes != different_run.file_bytes
    assert original.sha256 != different_run.sha256
    assert original.file_bytes != different_index.file_bytes
    assert original.sha256 != different_index.sha256


def test_invalid_test_receipt_parameters_are_rejected() -> None:
    invalid_height: Any = 1.5
    invalid_calls = (
        lambda: generate_test_receipt("", 0),
        lambda: generate_test_receipt("   ", 0),
        lambda: generate_test_receipt("run", -1),
        lambda: generate_test_receipt("run", True),
        lambda: generate_test_receipt("run", 0, width=0),
        lambda: generate_test_receipt("run", 0, height=invalid_height),
        lambda: generate_test_receipt("run", 0, width=1600, height=1100),
        lambda: generate_test_receipt("x" * 257, 0),
    )

    for generate in invalid_calls:
        with pytest.raises(ClientInputError):
            generate()


def test_load_profiles_keep_rate_and_concurrency_independent() -> None:
    smoke = E2ELoadTestConfig.smoke_test("smoke-run")
    normal = E2ELoadTestConfig.normal_load(
        "normal-run",
        receipt_count=37,
        max_concurrency=8,
        starts_per_second=2.5,
        acceptance_window_seconds=45.0,
    )
    peak = E2ELoadTestConfig.peak_load("peak-run")

    assert (smoke.receipt_count, smoke.max_concurrency) == (3, 1)
    assert (normal.receipt_count, normal.max_concurrency) == (37, 8)
    assert normal.starts_per_second == 2.5
    assert (peak.receipt_count, peak.max_concurrency) == (200, 10)
    assert peak.starts_per_second == 4.0
    assert peak.acceptance_window_seconds == 60.0


def test_invalid_load_test_configuration_is_rejected() -> None:
    valid: dict[str, Any] = {
        "receipt_count": 3,
        "max_concurrency": 2,
        "starts_per_second": 2.0,
        "acceptance_window_seconds": 10.0,
        "run_id": "valid-run",
    }
    invalid_configurations: tuple[dict[str, Any], ...] = (
        {**valid, "receipt_count": 0},
        {**valid, "receipt_count": True},
        {**valid, "max_concurrency": 0},
        {**valid, "starts_per_second": 0.0},
        {**valid, "starts_per_second": float("inf")},
        {**valid, "starts_per_second": float("nan")},
        {**valid, "starts_per_second": 5e-324},
        {**valid, "acceptance_window_seconds": -1.0},
        {**valid, "acceptance_window_seconds": float("inf")},
        {**valid, "acceptance_window_seconds": float("nan")},
        {**valid, "run_id": ""},
    )

    for values in invalid_configurations:
        with pytest.raises(ClientInputError):
            E2ELoadTestConfig(**values)


def test_single_upload_confirms_after_s3_and_notifies_receipt_id_early() -> None:
    clock = FakeClock(10.0)
    receipt = generate_test_receipt("single-run", 0, width=8, height=8)
    events: list[tuple[str, str]] = []
    fake_client = FakeReceiptClient(
        during_upload=lambda grant, _: events.append(("s3", grant.receipt_id))
    )

    result = upload_test_receipt(
        fake_client,
        HOUSEHOLD_ID,
        receipt,
        planned_start_at=10.0,
        deadline_at=20.0,
        clock=clock,
        on_receipt_created=lambda index, receipt_id: events.append(
            ("created", f"{index}:{receipt_id}")
        ),
    )

    assert result.upload_succeeded
    assert result.receipt_id == "synthetic-receipt-1"
    assert result.actual_start_at == 10.0
    assert result.s3_completed_at == result.finished_at == 10.0
    assert result.failure_category is None
    assert events == [
        ("created", "0:synthetic-receipt-1"),
        ("s3", "synthetic-receipt-1"),
    ]


def test_api_failure_is_recorded_before_receipt_id_and_not_retried() -> None:
    receipt = generate_test_receipt("api-error-run", 0, width=8, height=8)
    fake_client = FakeReceiptClient(create_error=HttpStatusError("api", "POST", 429))

    result = upload_test_receipt(
        fake_client,
        HOUSEHOLD_ID,
        receipt,
        planned_start_at=10.0,
        deadline_at=20.0,
        clock=FakeClock(10.0),
    )

    assert not result.upload_succeeded
    assert result.failure_category == "api_http_error"
    assert result.receipt_id is None
    assert result.http_status_code == 429
    assert not result.outcome_uncertain
    assert fake_client.create_calls and len(fake_client.create_calls) == 1
    assert not fake_client.upload_calls


def test_s3_failure_keeps_receipt_id_and_is_not_retried() -> None:
    receipt = generate_test_receipt("s3-error-run", 0, width=8, height=8)
    fake_client = FakeReceiptClient(upload_error=HttpStatusError("s3", "PUT", 503))

    result = upload_test_receipt(
        fake_client,
        HOUSEHOLD_ID,
        receipt,
        planned_start_at=10.0,
        deadline_at=20.0,
        clock=FakeClock(10.0),
    )

    assert not result.upload_succeeded
    assert result.failure_category == "s3_http_error"
    assert result.receipt_id == "synthetic-receipt-1"
    assert result.s3_completed_at is None
    assert result.http_status_code == 503
    assert result.outcome_uncertain
    assert len(fake_client.create_calls) == len(fake_client.upload_calls) == 1


def test_api_http_5xx_is_uncertain_without_inventing_receipt_id() -> None:
    receipt = generate_test_receipt("api-5xx-run", 0, width=8, height=8)
    fake_client = FakeReceiptClient(create_error=HttpStatusError("api", "POST", 503))

    result = upload_test_receipt(
        fake_client,
        HOUSEHOLD_ID,
        receipt,
        planned_start_at=10.0,
        deadline_at=20.0,
        clock=FakeClock(10.0),
    )

    assert result.failure_category == "api_http_error"
    assert result.http_status_code == 503
    assert result.receipt_id is None
    assert result.outcome_uncertain
    assert not fake_client.upload_calls


@pytest.mark.parametrize(
    ("stage", "failure", "expected_receipt_id"),
    [
        ("api", RequestTimeoutError(), None),
        ("api", NetworkRequestError(), None),
        ("s3", RequestTimeoutError(), "synthetic-receipt-1"),
        ("s3", NetworkRequestError(), "synthetic-receipt-1"),
    ],
)
def test_network_failures_are_marked_uncertain(
    stage: str, failure: Exception, expected_receipt_id: str | None
) -> None:
    receipt = generate_test_receipt("uncertain-run", 0, width=8, height=8)
    fake_client = FakeReceiptClient(
        create_error=failure if stage == "api" else None,
        upload_error=failure if stage == "s3" else None,
    )

    result = upload_test_receipt(
        fake_client,
        HOUSEHOLD_ID,
        receipt,
        planned_start_at=10.0,
        deadline_at=20.0,
        clock=FakeClock(10.0),
    )

    assert not result.upload_succeeded
    expected_error = "timeout" if isinstance(failure, RequestTimeoutError) else "network_error"
    assert result.failure_category == f"{stage}_{expected_error}"
    assert result.receipt_id == expected_receipt_id
    assert result.outcome_uncertain


def test_upload_failure_message_does_not_expose_exception_content() -> None:
    receipt = generate_test_receipt("safe-error-run", 0, width=8, height=8)
    sensitive_error = InvalidResponseError(f"{ID_TOKEN} {UPLOAD_URL}")
    fake_client = FakeReceiptClient(create_error=sensitive_error)

    result = upload_test_receipt(
        fake_client,
        HOUSEHOLD_ID,
        receipt,
        planned_start_at=10.0,
        deadline_at=20.0,
        clock=FakeClock(10.0),
    )

    assert result.error_message == "Server response was invalid."
    assert ID_TOKEN not in (result.error_message or "")
    assert UPLOAD_URL not in (result.error_message or "")
    assert ID_TOKEN not in repr(result)
    assert UPLOAD_URL not in repr(result)


def test_single_upload_does_not_start_s3_put_after_deadline() -> None:
    clock = FakeClock(10.0)
    receipt = generate_test_receipt("deadline-between-requests", 0, width=8, height=8)
    fake_client = FakeReceiptClient(after_create=lambda: clock.advance(2.0))

    result = upload_test_receipt(
        fake_client,
        HOUSEHOLD_ID,
        receipt,
        planned_start_at=10.0,
        deadline_at=11.0,
        clock=clock,
    )

    assert result.failure_category == "deadline"
    assert result.receipt_id == "synthetic-receipt-1"
    assert result.completed_after_deadline
    assert not fake_client.upload_calls


def test_successful_s3_put_after_deadline_is_explicitly_late() -> None:
    clock = FakeClock(10.0)
    receipt = generate_test_receipt("late-put-run", 0, width=8, height=8)
    fake_client = FakeReceiptClient(during_upload=lambda _grant, _bytes: clock.advance(2.0))

    result = upload_test_receipt(
        fake_client,
        HOUSEHOLD_ID,
        receipt,
        planned_start_at=10.0,
        deadline_at=11.0,
        clock=clock,
    )

    assert result.upload_succeeded
    assert result.s3_completed_at == 12.0
    assert result.completed_after_deadline


def test_load_scheduler_records_all_receipts_and_paces_actual_starts() -> None:
    clock = FakeClock(50.0)
    receipts = small_test_receipts("paced-run", 4)
    config = E2ELoadTestConfig.normal_load(
        "paced-run",
        receipt_count=4,
        max_concurrency=2,
        starts_per_second=2.0,
        acceptance_window_seconds=5.0,
    )
    fake_client = FakeReceiptClient()

    results = run_upload_load(
        fake_client,
        HOUSEHOLD_ID,
        receipts,
        config,
        clock=clock,
        sleep=clock.sleep,
    )

    assert [result.index for result in results] == [0, 1, 2, 3]
    assert all(result.upload_succeeded for result in results)
    assert [result.planned_start_at for result in results] == [50.0, 50.5, 51.0, 51.5]
    actual_starts = [result.actual_start_at for result in results]
    assert all(start is not None for start in actual_starts)
    actual_starts = [start for start in actual_starts if start is not None]
    assert all(
        actual >= planned
        for actual, planned in zip(actual_starts, (50.0, 50.5, 51.0, 51.5), strict=True)
    )
    assert all(later - earlier >= 0.5 for earlier, later in pairwise(actual_starts))


def test_load_scheduler_paces_client_starts_after_delayed_executor_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_executor = e2e_runner.ThreadPoolExecutor
    delayed_first_submission = True

    class DelayedExecutor:
        def __init__(self, *, max_workers: int) -> None:
            self.executor = real_executor(max_workers=max_workers)

        def __enter__(self) -> DelayedExecutor:
            self.executor.__enter__()
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> bool | None:
            return self.executor.__exit__(exc_type, exc_value, traceback)

        def submit(self, function: Callable[..., Any], *args: Any, **kwargs: Any):
            nonlocal delayed_first_submission
            if delayed_first_submission:
                delayed_first_submission = False

                def delayed_call() -> Any:
                    time.sleep(0.2)
                    return function(*args, **kwargs)

                return self.executor.submit(delayed_call)
            return self.executor.submit(function, *args, **kwargs)

    class TimedReceiptClient(FakeReceiptClient):
        def __init__(self) -> None:
            super().__init__()
            self.api_start_times: list[float] = []

        def create_receipt(
            self, household_id: str, content_type: str, file_bytes: bytes
        ) -> ReceiptUploadGrant:
            self.api_start_times.append(time.perf_counter())
            return super().create_receipt(household_id, content_type, file_bytes)

    monkeypatch.setattr(e2e_runner, "ThreadPoolExecutor", DelayedExecutor)
    receipts = small_test_receipts("delayed-dispatch-run", 3)
    config = E2ELoadTestConfig.normal_load(
        "delayed-dispatch-run",
        receipt_count=3,
        max_concurrency=3,
        starts_per_second=2.0,
        acceptance_window_seconds=5.0,
    )
    fake_client = TimedReceiptClient()

    results = run_upload_load(
        fake_client,
        HOUSEHOLD_ID,
        receipts,
        config,
    )

    api_starts = fake_client.api_start_times
    assert len(api_starts) == 3
    assert all(later - earlier >= 0.45 for earlier, later in pairwise(api_starts))
    assert [result.actual_start_at for result in results] == pytest.approx(api_starts, abs=0.02)


def test_load_scheduler_stops_starting_at_acceptance_deadline() -> None:
    receipts = small_test_receipts("deadline-run", 5)
    config = E2ELoadTestConfig(
        receipt_count=5,
        max_concurrency=1,
        starts_per_second=1.0,
        acceptance_window_seconds=2.5,
        run_id="deadline-run",
    )

    results = run_upload_load(
        FakeReceiptClient(),
        HOUSEHOLD_ID,
        receipts,
        config,
        clock=time.perf_counter,
        sleep=time.sleep,
    )

    assert len(results) == 5
    assert [result.upload_succeeded for result in results] == [
        True,
        True,
        True,
        False,
        False,
    ]
    assert [result.failure_category for result in results[3:]] == [
        "deadline",
        "deadline",
    ]
    assert all(result.actual_start_at is None for result in results[3:])


def test_load_scheduler_records_expected_failures_and_continues() -> None:
    receipts = small_test_receipts("expected-errors-run", 3)
    config = E2ELoadTestConfig(3, 3, 10.0, 5.0, "expected-errors-run")
    fake_client = FakeReceiptClient(upload_error=HttpStatusError("s3", "PUT", 503))
    clock = FakeClock(10.0)

    results = run_upload_load(
        fake_client,
        HOUSEHOLD_ID,
        receipts,
        config,
        clock=clock,
        sleep=clock.sleep,
    )

    assert len(results) == 3
    assert [result.failure_category for result in results] == [
        "s3_http_error",
        "s3_http_error",
        "s3_http_error",
    ]
    assert [result.receipt_id for result in results] == [
        "synthetic-receipt-1",
        "synthetic-receipt-2",
        "synthetic-receipt-3",
    ]
    assert len(fake_client.create_calls) == len(fake_client.upload_calls) == 3


def test_load_scheduler_respects_maximum_concurrency() -> None:
    receipts = small_test_receipts("parallel-run", 5)
    config = E2ELoadTestConfig(
        receipt_count=5,
        max_concurrency=2,
        starts_per_second=1000.0,
        acceptance_window_seconds=5.0,
        run_id="parallel-run",
    )
    lock = threading.Lock()
    release = threading.Event()
    two_uploads_started = threading.Event()
    active = 0
    max_active = 0

    def blocked_upload(_grant: ReceiptUploadGrant, _file_bytes: bytes) -> None:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            if active == 2:
                two_uploads_started.set()
        if not release.wait(timeout=1.0):
            raise AssertionError("Test did not release simulated uploads.")
        with lock:
            active -= 1

    def allow_uploads_to_finish(seconds: float) -> None:
        if two_uploads_started.is_set():
            release.set()
        time.sleep(min(seconds, 0.001))

    results = run_upload_load(
        FakeReceiptClient(during_upload=blocked_upload),
        HOUSEHOLD_ID,
        receipts,
        config,
        sleep=allow_uploads_to_finish,
    )

    assert len(results) == 5
    assert all(result.upload_succeeded for result in results)
    assert max_active == 2


def test_load_scheduler_does_not_swallow_programming_errors() -> None:
    receipt = generate_test_receipt("programming-error-run", 0, width=8, height=8)
    fake_client = FakeReceiptClient(create_error=RuntimeError("unexpected"))
    config = E2ELoadTestConfig(1, 1, 1.0, 5.0, "programming-error-run")
    clock = FakeClock(10.0)

    with pytest.raises(RuntimeError, match="unexpected"):
        run_upload_load(
            fake_client,
            HOUSEHOLD_ID,
            [receipt],
            config,
            clock=clock,
            sleep=clock.sleep,
        )


@pytest.mark.parametrize(
    "headers",
    [
        {**UPLOAD_HEADERS, "content-type": "image/jpeg"},
        {
            **UPLOAD_HEADERS,
            "Content-Type": "image/jpeg\r\nX-Injected: synthetic-secret",
        },
        {
            "Content-Type\r\nX-Injected": "image/jpeg",
            "x-amz-tagging": "status=pending",
        },
    ],
)
def test_create_receipt_rejects_ambiguous_or_invalid_headers(
    headers: dict[str, str],
) -> None:
    transport = FakeTransport(json_response(receipt_upload_response(upload_headers=headers), 201))

    with pytest.raises(InvalidResponseError) as error:
        client(transport).create_receipt(HOUSEHOLD_ID, "image/jpeg", FILE_BYTES)

    assert "synthetic-secret" not in str(error.value)
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    "headers",
    [
        {**UPLOAD_HEADERS, "content-type": "image/jpeg"},
        {
            **UPLOAD_HEADERS,
            "Content-Type": "image/jpeg\r\nX-Injected: synthetic-secret",
        },
        {
            "Content-Type\r\nX-Injected": "image/jpeg",
            "x-amz-tagging": "status=pending",
        },
        {**UPLOAD_HEADERS, "Content-Length": "1"},
        {**UPLOAD_HEADERS, "Authorization": "synthetic-token"},
    ],
)
def test_upload_file_rejects_ambiguous_or_invalid_headers_before_sending(
    headers: dict[str, str],
) -> None:
    grant = ReceiptUploadGrant(
        receipt_id=RECEIPT_ID,
        size_bytes=len(FILE_BYTES),
        expires_in=300,
        upload_url=UPLOAD_URL,
        upload_headers=headers,
    )
    transport = FakeTransport()

    with pytest.raises(InvalidResponseError) as error:
        client(transport).upload_file(grant, FILE_BYTES)

    assert "synthetic-secret" not in str(error.value)
    assert "synthetic-token" not in str(error.value)
    assert not transport.requests


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.test",
        "https://api.example.test:invalid",
        "https://api.example.test:65536",
        "https://api.example.test:0",
        "https://api.example.test:",
        "https://user:password@api.example.test",
        "https://api.example.test/path#fragment",
        "https://api.example.test/\npath",
    ],
)
def test_invalid_api_base_urls_are_rejected_without_network(url: str) -> None:
    with pytest.raises(ClientInputError) as error:
        E2EHttpClient(url, ID_TOKEN)

    assert UPLOAD_URL not in str(error.value)


@pytest.mark.parametrize(
    "upload_url",
    [
        "https://s3.example.test:invalid/upload",
        "https://s3.example.test:65536/upload",
        "https://user:password@s3.example.test/upload",
        "https://s3.example.test/upload#fragment",
        "https://s3.example.test/\r\nupload",
    ],
)
def test_invalid_presigned_urls_are_rejected_without_network(upload_url: str) -> None:
    transport = FakeTransport(json_response(receipt_upload_response(upload_url=upload_url), 201))

    with pytest.raises(InvalidResponseError) as error:
        client(transport).create_receipt(HOUSEHOLD_ID, "image/jpeg", FILE_BYTES)

    assert "password" not in str(error.value)
    assert not transport.requests[1:]


def test_status_monitor_observes_uploaded_then_done_after_upload_phase() -> None:
    clock = FakeClock(100.0)
    http_client = FakeMonitoringClient(
        (
            receipt_status_map((RECEIPT_ID, "uploaded")),
            receipt_status_map((RECEIPT_ID, "done")),
        )
    )
    result = successful_upload_result(0, RECEIPT_ID, s3_completed_at=99.5)

    monitor, wait = finished_monitor(
        http_client,
        clock,
        ((0, RECEIPT_ID),),
        upload_results=(result,),
    )

    record = monitor.snapshot()[0]
    assert [item.status for item in record.status_observations] == ["uploaded", "done"]
    assert record.last_nonterminal_status == "uploaded"
    assert record.last_nonterminal_observed_at == 100.0
    assert record.first_terminal_status == "done"
    assert record.first_terminal_observed_at == 101.0
    assert record.upload_result == result
    assert record.monitoring_outcome == "done"
    assert wait.timeouts == [1.0]
    assert monitor.stop_reason == "all_terminal"
    assert not monitor.thread_is_alive


@pytest.mark.parametrize("terminal_status", ["failed", "duplicate"])
def test_status_monitor_preserves_immediate_terminal_status(
    terminal_status: str,
) -> None:
    http_client = FakeMonitoringClient((receipt_status_map((RECEIPT_ID, terminal_status)),))

    monitor, _ = finished_monitor(
        http_client,
        FakeClock(),
        ((0, RECEIPT_ID),),
    )

    record = monitor.snapshot()[0]
    assert record.first_terminal_status == terminal_status
    assert record.first_terminal_observed_at == 100.0
    assert record.monitoring_outcome == terminal_status
    assert http_client.list_calls == 1


def test_status_monitor_records_missing_receipt_then_observes_it() -> None:
    http_client = FakeMonitoringClient(({}, receipt_status_map((RECEIPT_ID, "done"))))

    monitor, _ = finished_monitor(
        http_client,
        FakeClock(),
        ((0, RECEIPT_ID),),
    )

    record = monitor.snapshot()[0]
    assert record.missing_response_count == 1
    assert record.last_missing_response_at == 100.0
    assert record.first_terminal_status == "done"
    assert monitor.polling_errors == ()


def test_status_monitor_ignores_receipts_outside_the_run() -> None:
    foreign_id = "00000000-0000-0000-0000-000000000099"
    http_client = FakeMonitoringClient(
        (
            receipt_status_map((foreign_id, "done")),
            receipt_status_map((RECEIPT_ID, "failed"), (foreign_id, "done")),
        )
    )

    monitor, _ = finished_monitor(
        http_client,
        FakeClock(),
        ((0, RECEIPT_ID),),
    )

    assert [record.receipt_id for record in monitor.snapshot()] == [RECEIPT_ID]
    assert monitor.snapshot()[0].first_terminal_status == "failed"
    assert http_client.list_calls == 2


def test_status_monitor_observes_multiple_receipts_in_one_list_request() -> None:
    second_id = "00000000-0000-0000-0000-000000000003"
    http_client = FakeMonitoringClient(
        (
            receipt_status_map(
                (RECEIPT_ID, "done"),
                (second_id, "duplicate"),
            ),
        )
    )

    monitor, _ = finished_monitor(
        http_client,
        FakeClock(),
        ((0, RECEIPT_ID), (1, second_id)),
    )

    assert [record.first_terminal_status for record in monitor.snapshot()] == [
        "done",
        "duplicate",
    ]
    assert http_client.list_calls == 1
    assert http_client.max_active_list_calls == 1


def test_status_monitor_preserves_first_terminal_and_records_conflicts() -> None:
    second_id = "00000000-0000-0000-0000-000000000003"
    http_client = FakeMonitoringClient(
        (
            receipt_status_map(
                (RECEIPT_ID, "done"),
                (second_id, "uploaded"),
            ),
            receipt_status_map(
                (RECEIPT_ID, "failed"),
                (second_id, "uploaded"),
            ),
        )
    )

    monitor, _ = finished_monitor(
        http_client,
        FakeClock(),
        ((0, RECEIPT_ID), (1, second_id)),
        processing_timeout_seconds=2.0,
    )

    record = monitor.snapshot()[0]
    assert record.first_terminal_status == "done"
    assert len(record.status_conflicts) == 1
    assert record.status_conflicts[0].later_status == "failed"
    assert record.status_conflicts[0].first_terminal_status == "done"


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (HttpStatusError("api", "GET", 429), "rate_limited"),
        (HttpStatusError("api", "GET", 503), "server_error"),
        (NetworkRequestError(), "network_error"),
        (RequestTimeoutError(), "timeout"),
        (InvalidResponseError("synthetic response body"), "invalid_response"),
    ],
)
def test_status_monitor_retries_transient_poll_errors_only_at_interval(
    error: Exception, category: str
) -> None:
    clock = FakeClock(100.0)
    request_times: list[float] = []
    http_client = FakeMonitoringClient(
        (
            error,
            receipt_status_map((RECEIPT_ID, "done")),
        ),
        on_list=lambda: request_times.append(clock()),
    )

    monitor, wait = finished_monitor(
        http_client,
        clock,
        ((0, RECEIPT_ID),),
    )

    assert len(monitor.polling_errors) == 1
    assert monitor.polling_errors[0].category == category
    assert not monitor.polling_errors[0].fatal
    assert monitor.snapshot()[0].first_terminal_status == "done"
    assert request_times == [100.0, 101.0]
    assert wait.timeouts == [1.0]


@pytest.mark.parametrize(
    ("status_code", "category"),
    [(401, "authentication"), (403, "authorization")],
)
def test_status_monitor_stops_on_authentication_or_authorization_failure(
    status_code: int, category: str
) -> None:
    http_client = FakeMonitoringClient((HttpStatusError("api", "GET", status_code),))

    monitor, _ = finished_monitor(
        http_client,
        FakeClock(),
        ((0, RECEIPT_ID),),
    )

    assert monitor.polling_error_category == category
    assert monitor.stop_reason == category
    assert monitor.polling_errors[0].fatal
    assert http_client.list_calls == 1
    assert monitor.snapshot()[0].monitoring_outcome == "polling_error"


def test_status_monitor_marks_uploaded_receipt_at_processing_deadline() -> None:
    result = successful_upload_result(0, RECEIPT_ID, s3_completed_at=99.5)
    http_client = FakeMonitoringClient(
        default_response=receipt_status_map((RECEIPT_ID, "uploaded"))
    )

    monitor, _ = finished_monitor(
        http_client,
        FakeClock(100.0),
        ((0, RECEIPT_ID),),
        upload_results=(result,),
        processing_timeout_seconds=3.0,
    )

    record = monitor.snapshot()[0]
    assert monitor.processing_deadline_at == 103.0
    assert monitor.stop_reason == "processing_deadline"
    assert record.last_nonterminal_status == "uploaded"
    assert record.monitoring_outcome == "uploaded_timeout"
    assert http_client.list_calls == 3


def test_status_monitor_marks_terminal_observations_after_deadline() -> None:
    clock = FakeClock(100.0)
    http_client = FakeMonitoringClient(
        (receipt_status_map((RECEIPT_ID, "done")),),
        on_list=lambda: clock.advance(3.0),
    )

    monitor, _ = finished_monitor(
        http_client,
        clock,
        ((0, RECEIPT_ID),),
        processing_timeout_seconds=2.0,
    )

    record = monitor.snapshot()[0]
    assert record.first_terminal_status == "done"
    assert record.first_terminal_observed_at == 103.0
    assert record.status_observations[0].observed_after_deadline
    assert record.terminal_observed_after_deadline
    assert monitor.stop_reason == "processing_deadline"
    assert http_client.list_calls == 1


def test_status_monitor_links_uncertain_upload_that_later_reaches_done() -> None:
    receipt = generate_test_receipt("uncertain-status-run", 0, width=8, height=8)
    result = UploadAttemptResult(
        index=0,
        sha256=receipt.sha256,
        size_bytes=receipt.size_bytes,
        receipt_id=RECEIPT_ID,
        planned_start_at=100.0,
        actual_start_at=100.0,
        s3_completed_at=None,
        finished_at=100.5,
        upload_succeeded=False,
        failure_category="s3_timeout",
        outcome_uncertain=True,
    )
    http_client = FakeMonitoringClient((receipt_status_map((RECEIPT_ID, "done")),))
    wait = AdvancingMonitorWait(FakeClock())
    monitor = ReceiptStatusMonitor(
        http_client,
        HOUSEHOLD_ID,
        clock=wait.clock,
        wait=wait,
    )
    monitor.attach_upload_result(result)
    monitor.register_receipt(0, RECEIPT_ID)
    monitor.finish_upload_phase((result,))
    monitor.start(wait.clock())
    monitor.join()

    record = monitor.snapshot()[0]
    assert record.upload_result == result
    assert record.first_terminal_status == "done"
    assert record.monitoring_outcome == "done"
    assert record.upload_result.outcome_uncertain


def test_s3_http_5xx_later_done_remains_unconfirmed_in_report() -> None:
    receipt = generate_test_receipt("s3-5xx-later-done", 0, width=8, height=8)
    upload_client = FakeReceiptClient(upload_error=HttpStatusError("s3", "PUT", 503))
    result = upload_test_receipt(
        upload_client,
        HOUSEHOLD_ID,
        receipt,
        planned_start_at=100.0,
        deadline_at=160.0,
        clock=FakeClock(100.0),
    )
    assert result.receipt_id is not None
    clock = FakeClock(100.0)
    monitor, _ = finished_monitor(
        FakeMonitoringClient((receipt_status_map((result.receipt_id, "done")),)),
        clock,
        ((0, result.receipt_id),),
        upload_results=(result,),
    )
    config = E2ELoadTestConfig.normal_load(
        "s3-5xx-later-done",
        receipt_count=1,
        max_concurrency=1,
        starts_per_second=1.0,
        acceptance_window_seconds=60.0,
    )

    report = build_e2e_load_test_report(config, (result,), (), status_monitor=monitor)

    assert result.failure_category == "s3_http_error"
    assert result.http_status_code == 503
    assert result.outcome_uncertain
    assert result.s3_completed_at is None
    assert len(upload_client.create_calls) == len(upload_client.upload_calls) == 1
    assert report.processing_summary["uncertain_uploads_later_done"] == 1
    assert report.data_quality["e2e_without_confirmed_s3"] == 1
    assert report.upload_results[0].s3_completed_at is None


def test_status_monitor_distinguishes_s3_put_not_started_at_deadline() -> None:
    receipt = generate_test_receipt("unstarted-status-run", 0, width=8, height=8)
    result = UploadAttemptResult(
        index=0,
        sha256=receipt.sha256,
        size_bytes=receipt.size_bytes,
        receipt_id=RECEIPT_ID,
        planned_start_at=100.0,
        actual_start_at=100.0,
        s3_completed_at=None,
        finished_at=100.0,
        upload_succeeded=False,
        failure_category="deadline",
    )
    http_client = FakeMonitoringClient(
        default_response=receipt_status_map((RECEIPT_ID, "uploaded"))
    )

    monitor, _ = finished_monitor(
        http_client,
        FakeClock(100.0),
        ((0, RECEIPT_ID),),
        upload_results=(result,),
        processing_timeout_seconds=2.0,
    )

    record = monitor.snapshot()[0]
    assert record.last_nonterminal_status == "uploaded"
    assert record.monitoring_outcome == "s3_not_started"
    assert record.upload_result is result


def test_load_scheduler_monitors_receipts_while_s3_upload_is_running() -> None:
    receipt_id = "synthetic-receipt-1"
    poll_returned = threading.Event()
    s3_started = threading.Event()
    release_s3 = threading.Event()
    http_client = FakeMonitoringClient(
        (receipt_status_map((receipt_id, "done")),),
        on_list=poll_returned.set,
        during_upload=lambda _grant, _bytes: (
            s3_started.set(),
            release_s3.wait(timeout=2.0),
        ),
    )
    monitor = ReceiptStatusMonitor(
        http_client,
        HOUSEHOLD_ID,
        poll_interval_seconds=0.01,
        processing_timeout_seconds=2.0,
    )
    config = E2ELoadTestConfig(1, 1, 10.0, 1.0, "concurrent-monitor-run")
    receipts = small_test_receipts("concurrent-monitor-run", 1)
    results: list[tuple[UploadAttemptResult, ...]] = []
    errors: list[Exception] = []

    def run_load() -> None:
        try:
            results.append(
                run_upload_load(
                    http_client,
                    HOUSEHOLD_ID,
                    receipts,
                    config,
                    status_monitor=monitor,
                )
            )
        except Exception as error:
            errors.append(error)

    load_thread = threading.Thread(target=run_load)
    load_thread.start()
    assert s3_started.wait(timeout=1.0)
    assert poll_returned.wait(timeout=1.0)

    observation_deadline = time.monotonic() + 1.0
    while (
        not monitor.snapshot() or monitor.snapshot()[0].first_terminal_status is None
    ) and time.monotonic() < observation_deadline:
        time.sleep(0.001)
    assert monitor.snapshot()[0].first_terminal_status == "done"
    assert monitor.snapshot()[0].upload_result is None

    release_s3.set()
    load_thread.join(timeout=2.0)

    assert not load_thread.is_alive()
    assert not errors
    assert len(results) == 1
    record = monitor.snapshot()[0]
    assert record.upload_result == results[0][0]
    assert record.terminal_observed_before_s3_confirmation
    assert record.first_terminal_observed_at is not None
    assert record.upload_result is not None
    assert record.upload_result.s3_completed_at is not None
    assert record.first_terminal_observed_at < record.upload_result.s3_completed_at
    assert not monitor.thread_is_alive
    assert http_client.max_active_list_calls == 1


@pytest.mark.parametrize(
    ("poll_interval_seconds", "processing_timeout_seconds"),
    [
        (0.0, 1.0),
        (float("inf"), 1.0),
        (float("nan"), 1.0),
        (1.0, 0.0),
        (1.0, float("inf")),
        (1.0, float("nan")),
    ],
)
def test_status_monitor_rejects_invalid_timing_configuration(
    poll_interval_seconds: float, processing_timeout_seconds: float
) -> None:
    with pytest.raises(ClientInputError):
        ReceiptStatusMonitor(
            FakeMonitoringClient(),
            HOUSEHOLD_ID,
            poll_interval_seconds=poll_interval_seconds,
            processing_timeout_seconds=processing_timeout_seconds,
        )


def test_nearest_rank_percentile_matches_local_load_test_method() -> None:
    values = tuple(float(value) for value in range(1, 21))

    assert nearest_rank_percentile(values) == 19.0
    assert nearest_rank_percentile((7.0,)) == 7.0
    assert nearest_rank_percentile(()) is None


def test_runtime_statistics_include_median_mean_min_max_and_empty_values() -> None:
    stats = runtime_statistics((4.0, 1.0, 3.0, 2.0))
    empty = runtime_statistics(())

    assert stats.count == 4
    assert stats.minimum_seconds == 1.0
    assert stats.mean_seconds == 2.5
    assert stats.median_seconds == 2.5
    assert stats.p95_seconds == 4.0
    assert stats.maximum_seconds == 4.0
    assert empty.count == 0
    assert empty.minimum_seconds is None
    assert empty.p95_seconds is None


@pytest.mark.parametrize("percentile", [0.0, -0.1, 1.1, float("inf"), float("nan")])
def test_nearest_rank_rejects_invalid_percentiles(percentile: float) -> None:
    with pytest.raises(ClientInputError):
        nearest_rank_percentile((1.0,), percentile)


def test_request_metrics_separate_api_s3_success_failure_and_timeouts() -> None:
    results = report_upload_results(1)
    timings = (
        RequestTiming("api", "POST", 0.2, 201, 100.0, 100.2),
        RequestTiming("api", "GET", 0.8, None, 100.3, 101.1, "timeout"),
        RequestTiming("api", "POST", 0.3, 503, 100.35, 100.65),
        RequestTiming("s3", "PUT", 0.9, 204, 100.4, 101.3),
    )
    report = build_e2e_load_test_report(
        E2ELoadTestConfig(1, 1, 1.0, 60.0, "timing-report"),
        results,
        timings,
        run_started_at=100.0,
    )

    assert report.api_request_metrics["all"].request_count == 3
    assert report.api_request_metrics["all"].succeeded_count == 1
    assert report.api_request_metrics["all"].failed_count == 2
    assert report.api_request_metrics["all"].timeout_count == 1
    assert report.api_request_metrics["all"].http_error_count == 1
    assert report.api_request_metrics["all"].failed_latency.p95_seconds == 0.8
    assert report.api_request_metrics["all"].timeout_latency.p95_seconds == 0.8
    assert report.api_request_metrics["all"].latency.p95_seconds == 0.8
    assert report.api_request_metrics["post"].request_count == 2
    assert report.api_request_metrics["get"].request_count == 1
    assert report.s3_put_metrics.request_count == 1
    assert report.s3_put_metrics.latency.p95_seconds == 0.9


def test_normal_load_e2e_p95_passes_at_exactly_ten_seconds() -> None:
    config = E2ELoadTestConfig.normal_load(
        "normal-boundary",
        receipt_count=20,
        max_concurrency=5,
        starts_per_second=1.0,
        acceptance_window_seconds=60.0,
    )
    results = report_upload_results(20)
    clock = FakeClock(100.0)
    monitor = report_status_monitor(
        results,
        clock,
        on_list=lambda: clock.advance(10.25),
    )

    report = build_e2e_load_test_report(config, results, (), status_monitor=monitor)

    assert report.e2e_processing_latency.p95_seconds == 10.0
    assert report.quality_assessments["normal_e2e_p95_10_seconds"].status == "PASS"


def test_normal_load_e2e_p95_fails_above_ten_seconds() -> None:
    config = E2ELoadTestConfig.normal_load(
        "normal-slow",
        receipt_count=20,
        max_concurrency=5,
        starts_per_second=1.0,
        acceptance_window_seconds=60.0,
    )
    results = report_upload_results(20)
    clock = FakeClock(100.0)
    monitor = report_status_monitor(
        results,
        clock,
        on_list=lambda: clock.advance(10.26),
    )

    report = build_e2e_load_test_report(config, results, (), status_monitor=monitor)

    assert report.e2e_processing_latency.p95_seconds == pytest.approx(10.01)
    assert report.quality_assessments["normal_e2e_p95_10_seconds"].status == "FAIL"


@pytest.mark.parametrize(
    ("profile", "count", "assessment_key"),
    [
        ("smoke", 3, "smoke_functional_check"),
        ("normal", 20, "normal_e2e_p95_10_seconds"),
        ("peak", 200, "peak_200_done_within_180_seconds"),
    ],
)
def test_terminal_status_conflict_with_failure_cannot_pass(
    profile: str, count: int, assessment_key: str
) -> None:
    if profile == "smoke":
        config = E2ELoadTestConfig.smoke_test("status-conflict")
    elif profile == "normal":
        config = E2ELoadTestConfig.normal_load(
            "status-conflict",
            receipt_count=count,
            max_concurrency=5,
            starts_per_second=1.0,
            acceptance_window_seconds=60.0,
        )
    else:
        config = E2ELoadTestConfig.peak_load("status-conflict")
    results = report_upload_results(count)
    receipt_pairs = tuple(
        (result.index, result.receipt_id) for result in results if result.receipt_id is not None
    )
    first_statuses = tuple(
        (receipt_id, "done" if index == 0 else "uploaded") for index, receipt_id in receipt_pairs
    )
    later_statuses = tuple(
        (receipt_id, "failed" if index == 0 else "done") for index, receipt_id in receipt_pairs
    )
    clock = FakeClock(100.0)
    monitor, _ = finished_monitor(
        FakeMonitoringClient(
            (receipt_status_map(*first_statuses), receipt_status_map(*later_statuses)),
            on_list=lambda: clock.advance(0.5),
        ),
        clock,
        receipt_pairs,
        upload_results=results,
        processing_timeout_seconds=180.0,
    )

    report = build_e2e_load_test_report(config, results, (), status_monitor=monitor)

    assert report.receipt_results[0].status_conflicts[0].later_status == "failed"
    assert report.processing_summary["conflicting_terminal_failures"] == 1
    assert report.quality_assessments[assessment_key].status == "FAIL"


def test_non_failure_status_conflict_is_inconclusive_for_smoke() -> None:
    config = E2ELoadTestConfig.smoke_test("ambiguous-status-conflict")
    results = report_upload_results(3)
    receipt_pairs = tuple(
        (result.index, result.receipt_id) for result in results if result.receipt_id is not None
    )
    first_statuses = tuple(
        (receipt_id, "done" if index == 0 else "uploaded") for index, receipt_id in receipt_pairs
    )
    later_statuses = tuple(
        (receipt_id, "uploaded" if index == 0 else "done") for index, receipt_id in receipt_pairs
    )
    clock = FakeClock(100.0)
    monitor, _ = finished_monitor(
        FakeMonitoringClient(
            (receipt_status_map(*first_statuses), receipt_status_map(*later_statuses)),
            on_list=lambda: clock.advance(0.5),
        ),
        clock,
        receipt_pairs,
        upload_results=results,
    )

    report = build_e2e_load_test_report(config, results, (), status_monitor=monitor)

    assert report.processing_summary["conflicting_status_observations"] == 1
    assert report.quality_assessments["smoke_functional_check"].status == "INCONCLUSIVE"


@pytest.mark.parametrize(
    "indices",
    [
        (0, 0, 2),
        (-1, 1, 2),
        (0, 1, 3),
    ],
)
def test_report_rejects_duplicate_or_unexpected_upload_indices(
    indices: tuple[int, int, int],
) -> None:
    config = E2ELoadTestConfig.smoke_test("invalid-report-indices")
    results = report_upload_results(3)
    invalid_results = tuple(
        replace(result, index=index) for result, index in zip(results, indices, strict=True)
    )

    with pytest.raises(ClientInputError, match="indices"):
        build_e2e_load_test_report(config, invalid_results, ())


def test_report_lists_missing_upload_and_status_indices() -> None:
    config = E2ELoadTestConfig.smoke_test("missing-report-indices")
    results = report_upload_results(3)
    tracked_results = results[:2]
    monitor = report_status_monitor(tracked_results, FakeClock(100.0))

    report = build_e2e_load_test_report(config, tracked_results, (), status_monitor=monitor)

    assert report.data_quality["missing_upload_indices"] == [2]
    assert report.data_quality["missing_status_indices"] == [2]
    assert report.quality_assessments["smoke_functional_check"].status == "INCONCLUSIVE"


def test_report_rejects_status_indices_outside_expected_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = E2ELoadTestConfig.smoke_test("invalid-status-index")
    results = (successful_upload_result(0, RECEIPT_ID),)
    clock = FakeClock(100.0)
    monitor, _ = finished_monitor(
        FakeMonitoringClient(
            (receipt_status_map((RECEIPT_ID, "done")),),
        ),
        clock,
        ((0, RECEIPT_ID),),
    )
    snapshot = monitor.snapshot
    monkeypatch.setattr(
        monitor,
        "snapshot",
        lambda: tuple(replace(record, index=-1) for record in snapshot()),
    )

    with pytest.raises(ClientInputError, match="Status record indices"):
        build_e2e_load_test_report(config, results, (), status_monitor=monitor)


def test_report_marks_upload_and_status_receipt_id_mismatch_inconclusive() -> None:
    config = E2ELoadTestConfig.smoke_test("receipt-link-mismatch")
    mismatched_result = successful_upload_result(0, "00000000-0000-0000-0000-000000000003")
    clock = FakeClock(100.0)
    monitor, _ = finished_monitor(
        FakeMonitoringClient((receipt_status_map((RECEIPT_ID, "done")),)),
        clock,
        ((0, RECEIPT_ID),),
        upload_results=(mismatched_result,),
    )

    report = build_e2e_load_test_report(config, (mismatched_result,), (), status_monitor=monitor)

    assert report.data_quality["status_linkage_mismatches"] == [0]
    assert report.quality_assessments["smoke_functional_check"].status == "INCONCLUSIVE"


def test_e2e_overlap_is_excluded_without_clamping_to_zero() -> None:
    config = E2ELoadTestConfig.normal_load(
        "overlap-report",
        receipt_count=20,
        max_concurrency=5,
        starts_per_second=1.0,
        acceptance_window_seconds=60.0,
    )
    results = list(report_upload_results(20))
    first = results[0]
    results[0] = UploadAttemptResult(
        index=0,
        sha256=first.sha256,
        size_bytes=first.size_bytes,
        receipt_id=first.receipt_id,
        planned_start_at=first.planned_start_at,
        actual_start_at=first.actual_start_at,
        s3_completed_at=101.0,
        finished_at=101.0,
        upload_succeeded=True,
        failure_category=None,
    )
    clock = FakeClock(100.0)
    monitor = report_status_monitor(tuple(results), clock, on_list=lambda: clock.advance(0.5))

    report = build_e2e_load_test_report(config, tuple(results), (), status_monitor=monitor)

    assert report.e2e_processing_latency.count == 19
    assert report.e2e_processing_latency.p95_seconds == pytest.approx(0.25)
    assert report.data_quality["e2e_temporal_overlaps"] == 1
    assert report.quality_assessments["normal_e2e_p95_10_seconds"].status == "INCONCLUSIVE"


def test_peak_load_with_200_synthetic_receipts_passes_at_60_seconds() -> None:
    config = E2ELoadTestConfig.peak_load("peak-success")
    results = report_upload_results(200)
    clock = FakeClock(100.0)
    monitor = report_status_monitor(results, clock, on_list=lambda: clock.advance(0.75))
    peak_timings = tuple(
        RequestTiming(
            "api",
            "POST",
            0.5,
            201,
            100.0 + index / 1000,
            100.5 + index / 1000,
        )
        for index in range(200)
    )

    report = build_e2e_load_test_report(config, results, peak_timings, status_monitor=monitor)

    assert report.upload_summary["confirmed_s3_uploads"] == 200
    assert report.upload_summary["confirmed_within_acceptance_window"] == 200
    assert report.processing_summary["done_within_processing_deadline"] == 200
    assert report.quality_assessments["peak_200_uploads_within_60_seconds"].status == "PASS"
    assert report.quality_assessments["peak_200_done_within_180_seconds"].status == "PASS"
    assert report.quality_assessments["peak_api_p95_below_1_second"].status == "PASS"


def test_peak_upload_is_on_time_at_exactly_sixty_seconds() -> None:
    config = E2ELoadTestConfig.peak_load("peak-60-second-boundary")
    results = list(report_upload_results(200))
    last = results[-1]
    results[-1] = UploadAttemptResult(
        index=last.index,
        sha256=last.sha256,
        size_bytes=last.size_bytes,
        receipt_id=last.receipt_id,
        planned_start_at=last.planned_start_at,
        actual_start_at=last.actual_start_at,
        s3_completed_at=160.0,
        finished_at=160.0,
        upload_succeeded=True,
        failure_category=None,
    )
    clock = FakeClock(100.0)
    monitor = report_status_monitor(tuple(results), clock, on_list=lambda: clock.advance(60.0))

    report = build_e2e_load_test_report(config, tuple(results), (), status_monitor=monitor)

    assert report.throughput["duration_to_last_confirmed_upload_seconds"] == 60.0
    assert report.upload_summary["confirmed_within_acceptance_window"] == 200
    assert report.quality_assessments["peak_200_uploads_within_60_seconds"].status == "PASS"


def test_peak_upload_criterion_fails_when_one_of_200_is_unconfirmed() -> None:
    config = E2ELoadTestConfig.peak_load("peak-short")
    results = report_upload_results(200, failed_index=199)
    report = build_e2e_load_test_report(config, results, (), run_started_at=100.0)

    assert report.upload_summary["confirmed_s3_uploads"] == 199
    assert report.upload_summary["s3_errors"] == 1
    assert report.quality_assessments["peak_200_uploads_within_60_seconds"].status == "FAIL"


def test_peak_upload_criterion_fails_when_an_upload_is_late() -> None:
    config = E2ELoadTestConfig.peak_load("peak-late")
    results = report_upload_results(200, late_index=199)
    report = build_e2e_load_test_report(config, results, (), run_started_at=100.0)

    assert report.upload_summary["confirmed_late"] == 1
    assert report.quality_assessments["peak_200_uploads_within_60_seconds"].status == "FAIL"


def test_peak_api_p95_requires_strictly_less_than_one_second() -> None:
    config = E2ELoadTestConfig.peak_load("peak-api-boundary")
    results = report_upload_results(200)
    timings = tuple(
        RequestTiming("api", "POST", 0.999, 201, 100.0 + index / 1000, 100.999 + index / 1000)
        for index in range(200)
    ) + tuple(
        RequestTiming("api", "GET", 1.0, 200, 101.0 + index, 102.0 + index) for index in range(20)
    )
    clock = FakeClock(100.0)
    monitor = report_status_monitor(results, clock, on_list=lambda: clock.advance(2.0))

    report = build_e2e_load_test_report(config, results, timings, status_monitor=monitor)

    assert report.api_request_metrics["peak_window"].latency.p95_seconds == 1.0
    assert report.quality_assessments["peak_api_p95_below_1_second"].status == "FAIL"


def test_peak_api_p95_is_inconclusive_when_a_started_upload_post_is_unmeasured() -> None:
    config = E2ELoadTestConfig.peak_load("peak-api-missing-post")
    timings = tuple(
        RequestTiming("api", "POST", 0.1, 201, 100.0 + index / 1000, 100.1 + index / 1000)
        for index in range(199)
    )

    report = build_e2e_load_test_report(
        config, report_upload_results(200), timings, run_started_at=100.0
    )

    assessment = report.quality_assessments["peak_api_p95_below_1_second"]
    assert assessment.status == "INCONCLUSIVE"
    assert "199/200 expected POST measurements" in assessment.reason
    assert report.data_quality["peak_expected_api_post_measurements"] == 200
    assert report.data_quality["peak_observed_api_post_measurements"] == 199
    assert report.data_quality["peak_missing_api_post_measurements"] == 1


def test_peak_api_post_measurements_use_the_defined_peak_window() -> None:
    config = E2ELoadTestConfig.peak_load("peak-api-window")
    results = list(report_upload_results(200))
    results[-1] = replace(results[-1], actual_start_at=160.0)
    timings = (
        *(
            RequestTiming("api", "POST", 0.1, 201, 100.0 + index / 1000, 100.1 + index / 1000)
            for index in range(199)
        ),
        RequestTiming("api", "POST", 0.1, 201, 160.0, 160.1),
    )

    report = build_e2e_load_test_report(config, tuple(results), timings, run_started_at=100.0)

    assert report.quality_assessments["peak_api_p95_below_1_second"].status == "PASS"
    assert report.data_quality["peak_expected_api_post_measurements"] == 199
    assert report.data_quality["peak_observed_api_post_measurements"] == 199
    assert report.data_quality["peak_unexpected_api_post_measurements"] == 0


def test_invalid_http_success_response_fails_peak_api_quality() -> None:
    http_client = client(FakeTransport(HttpResponse(201, b"not-json")), clock=lambda: 100.0)
    with pytest.raises(InvalidResponseError):
        http_client.create_receipt(HOUSEHOLD_ID, "image/jpeg", FILE_BYTES)
    assert len(http_client.timings) == 1

    timings = http_client.timings + tuple(
        RequestTiming("api", "POST", 0.1, 201, 100.0, 100.1) for _ in range(199)
    )
    report = build_e2e_load_test_report(
        E2ELoadTestConfig.peak_load("peak-api-invalid-json"),
        report_upload_results(200),
        timings,
        run_started_at=100.0,
    )

    assert report.api_request_metrics["peak_window"].request_count == 200
    assert report.api_request_metrics["peak_window"].failed_count == 1
    assert report.quality_assessments["peak_api_p95_below_1_second"].status == "FAIL"


def test_peak_processing_passes_when_done_is_observed_at_180_seconds() -> None:
    config = E2ELoadTestConfig.peak_load("peak-processing-boundary")
    results = report_upload_results(200)
    clock = FakeClock(100.0)
    monitor = report_status_monitor(
        results,
        clock,
        on_list=lambda: clock.advance(180.0),
    )

    report = build_e2e_load_test_report(config, results, (), status_monitor=monitor)

    assert report.processing_summary["done_within_processing_deadline"] == 200
    assert report.quality_assessments["peak_200_done_within_180_seconds"].status == "PASS"


def test_peak_api_failures_do_not_pass_on_low_latency_alone() -> None:
    config = E2ELoadTestConfig.peak_load("peak-api-errors")
    results = report_upload_results(200)
    clock = FakeClock(100.0)
    monitor = report_status_monitor(results, clock, on_list=lambda: clock.advance(1.1))
    timings = (
        *(
            RequestTiming("api", "POST", 0.1, 201, 100.0 + index / 1000, 100.1 + index / 1000)
            for index in range(200)
        ),
        RequestTiming("api", "GET", 0.1, None, 101.0, 101.1, "network_error"),
    )

    report = build_e2e_load_test_report(config, results, timings, status_monitor=monitor)

    assert report.api_request_metrics["peak_window"].latency.p95_seconds == 0.1
    assert report.api_request_metrics["peak_window"].failed_count == 1
    assert report.quality_assessments["peak_api_p95_below_1_second"].status == "FAIL"


def test_processing_aggregation_separates_failed_duplicate_missing_and_uncertain() -> None:
    config = E2ELoadTestConfig.normal_load(
        "processing-summary",
        receipt_count=4,
        max_concurrency=2,
        starts_per_second=2.0,
        acceptance_window_seconds=60.0,
    )
    results = list(report_upload_results(4, uncertain_index=2))
    results[3] = UploadAttemptResult(
        index=3,
        sha256=results[3].sha256,
        size_bytes=results[3].size_bytes,
        receipt_id=None,
        planned_start_at=100.0,
        actual_start_at=100.0,
        s3_completed_at=None,
        finished_at=100.5,
        upload_succeeded=False,
        failure_category="api_http_error",
    )
    clock = FakeClock(100.0)
    states = ("failed", "duplicate", "done")
    monitor = report_status_monitor(tuple(results[:3]), clock, statuses=states)

    report = build_e2e_load_test_report(config, tuple(results), (), status_monitor=monitor)

    assert report.processing_summary["failed"] == 1
    assert report.processing_summary["duplicate"] == 1
    assert report.processing_summary["done_observed"] == 1
    assert report.processing_summary["uncertain_uploads_later_done"] == 1
    assert report.processing_summary["missing_or_unobserved_receipt_ids"] == 1
    assert report.upload_summary["receipt_records_created"] == 3
    assert report.upload_summary["api_errors"] == 1


def test_report_outcome_categories_partition_results_without_double_counting() -> None:
    config = E2ELoadTestConfig.normal_load(
        "partition-report",
        receipt_count=4,
        max_concurrency=2,
        starts_per_second=2.0,
        acceptance_window_seconds=60.0,
    )
    results = list(report_upload_results(4, failed_index=1, uncertain_index=2, late_index=3))
    results[0] = UploadAttemptResult(
        index=0,
        sha256=results[0].sha256,
        size_bytes=results[0].size_bytes,
        receipt_id=None,
        planned_start_at=100.0,
        actual_start_at=None,
        s3_completed_at=None,
        finished_at=None,
        upload_succeeded=False,
        failure_category="not_started",
    )

    report = build_e2e_load_test_report(config, tuple(results), (), run_started_at=100.0)

    categories = report.upload_summary["outcome_categories"]
    assert isinstance(categories, dict)
    assert sum(categories.values()) == config.receipt_count
    assert categories["not_started"] == 1
    assert categories["s3_failed"] == 1
    assert categories["s3_uncertain"] == 1
    assert categories["confirmed_late"] == 1


def test_upload_report_distinguishes_created_receipts_confirmed_puts_and_deadlines() -> None:
    config = E2ELoadTestConfig.normal_load(
        "upload-counts",
        receipt_count=3,
        max_concurrency=2,
        starts_per_second=2.0,
        acceptance_window_seconds=60.0,
    )
    confirmed = report_upload_results(1)[0]
    deadline_receipt = generate_test_receipt("upload-counts", 1, width=8, height=8)
    not_started_receipt = generate_test_receipt("upload-counts", 2, width=8, height=8)
    deadline = UploadAttemptResult(
        index=1,
        sha256=deadline_receipt.sha256,
        size_bytes=deadline_receipt.size_bytes,
        receipt_id="synthetic-receipt-1",
        planned_start_at=100.5,
        actual_start_at=100.5,
        s3_completed_at=None,
        finished_at=160.0,
        upload_succeeded=False,
        failure_category="deadline",
    )
    not_started = UploadAttemptResult(
        index=2,
        sha256=not_started_receipt.sha256,
        size_bytes=not_started_receipt.size_bytes,
        receipt_id=None,
        planned_start_at=101.0,
        actual_start_at=None,
        s3_completed_at=None,
        finished_at=None,
        upload_succeeded=False,
        failure_category="not_started",
    )

    report = build_e2e_load_test_report(
        config, (confirmed, deadline, not_started), (), run_started_at=100.0
    )

    summary = report.upload_summary
    assert summary["planned"] == 3
    assert summary["started"] == 2
    assert summary["receipt_records_created"] == 2
    assert summary["confirmed_s3_uploads"] == 1
    assert summary["not_started"] == 1
    assert summary["s3_put_not_started_after_deadline"] == 1
    assert summary["confirmed_bytes"] == confirmed.size_bytes
    categories = summary["outcome_categories"]
    assert isinstance(categories, dict)
    assert sum(categories.values()) == 3


def test_report_calculates_durations_throughput_and_failure_shares() -> None:
    config = E2ELoadTestConfig.normal_load(
        "throughput-report",
        receipt_count=1,
        max_concurrency=1,
        starts_per_second=1.0,
        acceptance_window_seconds=60.0,
    )
    result = successful_upload_result(0, RECEIPT_ID, s3_completed_at=110.0)
    clock = FakeClock(100.0)
    monitor = report_status_monitor(
        (result,),
        clock,
        on_list=lambda: clock.advance(15.0),
    )

    report = build_e2e_load_test_report(config, (result,), (), status_monitor=monitor)

    assert report.e2e_processing_latency.p95_seconds == 5.0
    assert report.throughput["duration_to_last_confirmed_upload_seconds"] == 10.0
    assert report.throughput["duration_to_last_done_observation_seconds"] == 15.0
    assert report.throughput["total_run_duration_seconds"] == 15.0
    assert report.throughput["confirmed_uploads_per_second"] == 0.1
    assert report.throughput["done_receipts_per_second"] == pytest.approx(1 / 15)
    assert report.throughput["upload_failure_rate_percent"] == 0.0
    assert report.throughput["planned_receipts_not_done_by_deadline_percent"] == 0.0


def test_missing_metrics_and_dlq_are_not_reported_as_pass_or_zero() -> None:
    config = E2ELoadTestConfig.normal_load(
        "incomplete-report",
        receipt_count=2,
        max_concurrency=1,
        starts_per_second=1.0,
        acceptance_window_seconds=60.0,
    )
    results = (successful_upload_result(0, RECEIPT_ID),)

    report = build_e2e_load_test_report(config, results, ())
    report_json = json.loads(report.to_json())

    assert report.e2e_processing_latency.p95_seconds is None
    assert report.throughput["total_run_duration_seconds"] is None
    assert report.data_quality["missing_upload_results"] == 1
    assert report.data_quality["missing_upload_indices"] == [1]
    assert report.quality_assessments["normal_e2e_p95_10_seconds"].status == "INCONCLUSIVE"
    assert report.quality_assessments["dlq_textract_throttling"].status == "NOT_EVALUATED"
    assert isinstance(report_json["file_sizes_bytes"], list)
    assert report.to_dict()["expected_receipts"] == 2
    assert "E2E normal_load run incomplete-report" in report.summary_text()


def test_missing_run_clock_keeps_time_dependent_counts_unavailable() -> None:
    report = build_e2e_load_test_report(
        E2ELoadTestConfig.peak_load("no-clock-report"),
        (),
        (),
    )

    assert report.upload_summary["confirmed_within_acceptance_window"] is None
    assert report.processing_summary["done_within_processing_deadline"] is None
    assert report.throughput["total_run_duration_seconds"] is None
    assert report.quality_assessments["peak_200_uploads_within_60_seconds"].status == "INCONCLUSIVE"


def test_non_finite_timestamps_serialize_as_unavailable() -> None:
    receipt = generate_test_receipt("nonfinite-report", 0, width=8, height=8)
    result = UploadAttemptResult(
        index=0,
        sha256=receipt.sha256,
        size_bytes=receipt.size_bytes,
        receipt_id=RECEIPT_ID,
        planned_start_at=100.0,
        actual_start_at=100.0,
        s3_completed_at=float("nan"),
        finished_at=float("nan"),
        upload_succeeded=True,
        failure_category=None,
    )
    config = E2ELoadTestConfig.normal_load(
        "nonfinite-report",
        receipt_count=1,
        max_concurrency=1,
        starts_per_second=1.0,
        acceptance_window_seconds=60.0,
    )

    payload = json.loads(
        build_e2e_load_test_report(config, (result,), (), run_started_at=100.0).to_json()
    )

    assert payload["upload_results"][0]["s3_completed_at"] is None
    assert payload["throughput"]["duration_to_last_confirmed_upload_seconds"] is None


def test_smoke_profile_does_not_evaluate_performance_objectives() -> None:
    config = E2ELoadTestConfig.smoke_test("smoke-report")
    results = report_upload_results(3)
    monitor = report_status_monitor(results, FakeClock(100.0))

    report = build_e2e_load_test_report(config, results, (), status_monitor=monitor)

    assert report.quality_assessments["smoke_functional_check"].status == "PASS"
    assert report.quality_assessments["normal_e2e_p95_10_seconds"].status == "NOT_EVALUATED"
    assert (
        report.quality_assessments["peak_200_uploads_within_60_seconds"].status == "NOT_EVALUATED"
    )


def test_report_excludes_sensitive_upload_error_details_and_file_bytes() -> None:
    receipt = generate_test_receipt("private-report", 0, width=8, height=8)
    result = UploadAttemptResult(
        index=0,
        sha256=receipt.sha256,
        size_bytes=receipt.size_bytes,
        receipt_id=RECEIPT_ID,
        planned_start_at=100.0,
        actual_start_at=100.0,
        s3_completed_at=None,
        finished_at=100.5,
        upload_succeeded=False,
        failure_category="api_network_error",
        error_message=f"{ID_TOKEN} {UPLOAD_URL} {UPLOAD_HEADERS!r} {receipt.file_bytes!r}",
        outcome_uncertain=True,
    )
    config = E2ELoadTestConfig.normal_load(
        "safe-report",
        receipt_count=1,
        max_concurrency=1,
        starts_per_second=1.0,
        acceptance_window_seconds=60.0,
    )

    report_text = build_e2e_load_test_report(config, (result,), (), run_started_at=100.0).to_json()

    assert ID_TOKEN not in report_text
    assert UPLOAD_URL not in report_text
    assert "x-amz-tagging" not in report_text
    assert repr(receipt.file_bytes) not in report_text


def test_cli_help_exits_without_token_or_network(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        e2e_runner.getpass,
        "getpass",
        lambda *_: pytest.fail("Help must not request a token."),
    )

    with pytest.raises(SystemExit) as error:
        main(["--help"])

    assert error.value.code == 0
    assert "--dry-run" in capsys.readouterr().out


def test_cli_without_profile_is_safely_blocked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        e2e_runner.getpass,
        "getpass",
        lambda *_: pytest.fail("Blocked runs must not request a token."),
    )

    assert main([]) == EXIT_SAFETY_BLOCKED
    assert "Choose a profile explicitly" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("profile", "count", "rate", "concurrency"),
    [
        ("smoke", 3, 1.0, 1),
        ("normal", 20, 1.0, 5),
        ("peak", 200, 4.0, 10),
    ],
)
def test_cli_dry_run_uses_the_existing_profiles_without_network_or_token(
    profile: str,
    count: int,
    rate: float,
    concurrency: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        e2e_runner.getpass,
        "getpass",
        lambda *_: pytest.fail("Dry runs must not request a token."),
    )

    exit_code = main(["--dry-run", "--profile", profile])
    plan = json.loads(capsys.readouterr().out)

    assert exit_code == EXIT_OK
    assert plan["profile"] == profile
    assert plan["receipt_count"] == count
    assert plan["starts_per_second"] == rate
    assert plan["max_concurrency"] == concurrency
    assert plan["quality_assessment"] == "NOT_EVALUATED"
    assert plan["test_data_estimate"]["estimated_total_bytes"] > 0
    assert "No token was requested" in plan["note"]


def test_cli_dry_run_accepts_custom_run_id_and_never_opens_network(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        e2e_runner.getpass,
        "getpass",
        lambda *_: pytest.fail("Dry runs must not request a token."),
    )
    monkeypatch.setattr(
        urllib.request.OpenerDirector,
        "open",
        lambda *_args, **_kwargs: pytest.fail("Dry run attempted network access."),
    )

    assert main(["--dry-run", "--run-id", "dry-run-1"]) == EXIT_OK
    plan = json.loads(capsys.readouterr().out)

    assert plan["run_id"] == "dry-run-1"
    assert plan["note"].endswith(
        "no uploads, network requests, or AWS measurements were performed."
    )


def test_cli_dry_run_reports_profile_deviations_as_unsuitable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--dry-run", "--profile", "normal", "--count", "21"]) == EXIT_OK
    plan = json.loads(capsys.readouterr().out)

    assert plan["receipt_count"] == 21
    assert plan["profile_matches_target"] is False


@pytest.mark.parametrize(
    ("arguments", "argparse_error"),
    [
        (["--dry-run", "--profile", "invalid"], True),
        (["--dry-run", "--profile", "normal", "--count", "0"], False),
        (["--dry-run", "--profile", "normal", "--poll-interval", "nan"], False),
        (["--dry-run", "--profile", "smoke", "--count", "4"], False),
        (["--dry-run", "--household-id", "not-a-uuid"], False),
        (["--dry-run", "--api-url", "http://api.example.test"], False),
    ],
)
def test_cli_rejects_invalid_configuration(
    arguments: list[str],
    argparse_error: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if argparse_error:
        with pytest.raises(SystemExit) as error:
            main(arguments)
        assert error.value.code == EXIT_CONFIGURATION_ERROR
        assert "invalid choice" in capsys.readouterr().err
        return

    assert main(arguments) == EXIT_CONFIGURATION_ERROR
    assert "Configuration error:" in capsys.readouterr().err


def test_confirmed_live_mode_stays_blocked_without_dev_and_mock_verification(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    token_prompts: list[str] = []
    monkeypatch.setattr(
        e2e_runner.getpass,
        "getpass",
        token_prompts.append,
    )

    exit_code = main(
        [
            "--profile",
            "smoke",
            "--confirm-start",
            "--api-url",
            API_BASE_URL,
            "--household-id",
            HOUSEHOLD_ID,
        ]
    )

    assert exit_code == EXIT_SAFETY_BLOCKED
    assert not token_prompts
    error = capsys.readouterr().err
    assert "bonbon-dev" in error
    assert "Textract mock" in error


def test_cli_output_file_is_exclusive_and_contains_only_dry_run_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "report.json"

    assert (
        main(
            [
                "--dry-run",
                "--profile",
                "smoke",
                "--run-id",
                "safe-output",
                "--output",
                str(output),
            ]
        )
        == EXIT_OK
    )
    contents = output.read_text(encoding="utf-8")
    assert json.loads(contents)["run_id"] == "safe-output"
    assert ID_TOKEN not in contents
    assert UPLOAD_URL not in contents

    assert (
        main(
            [
                "--dry-run",
                "--profile",
                "smoke",
                "--run-id",
                "replacement",
                "--output",
                str(output),
            ]
        )
        == EXIT_EXECUTION_ERROR
    )
    assert output.read_text(encoding="utf-8") == contents
    assert "Could not write JSON output" in capsys.readouterr().err


def test_cli_full_flow_uses_simulated_client_and_keeps_token_out_of_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    token = "synthetic-token-must-not-leak"
    clock = FakeClock(100.0)
    all_receipts_registered = threading.Event()
    captured: dict[str, object] = {}

    class SimulatedHttpClient:
        @staticmethod
        def _validate_api_base_url(api_url: str) -> str:
            return E2EHttpClient._validate_api_base_url(api_url)

        def __init__(
            self,
            api_url: str,
            id_token: str,
            *,
            timeout_seconds: float,
            clock: Callable[[], float],
        ) -> None:
            captured["api_url"] = api_url
            captured["token"] = id_token
            captured["timeout_seconds"] = timeout_seconds
            self.timings: tuple[RequestTiming, ...] = ()
            self.receipt_ids: list[str] = []
            self._lock = threading.Lock()

        def create_receipt(
            self, household_id: str, content_type: str, file_bytes: bytes
        ) -> ReceiptUploadGrant:
            with self._lock:
                receipt_id = str(UUID(int=len(self.receipt_ids) + 1))
                self.receipt_ids.append(receipt_id)
            return ReceiptUploadGrant(
                receipt_id=receipt_id,
                size_bytes=len(file_bytes),
                expires_in=300,
                upload_url=UPLOAD_URL,
                upload_headers=UPLOAD_HEADERS,
            )

        def upload_file(self, grant: ReceiptUploadGrant, file_bytes: bytes) -> None:
            assert grant.receipt_id in self.receipt_ids
            assert file_bytes.startswith(b"\x89PNG\r\n\x1a\n")

        def list_receipts(self, household_id: str) -> dict[str, ReceiptSummary]:
            assert household_id == HOUSEHOLD_ID
            assert all_receipts_registered.wait(timeout=1.0)
            return receipt_status_map(*((receipt_id, "done") for receipt_id in self.receipt_ids))

    base_monitor = ReceiptStatusMonitor

    class SimulatedReceiptStatusMonitor(base_monitor):
        def register_receipt(self, index: int, receipt_id: str) -> None:
            super().register_receipt(index, receipt_id)
            if len(self.snapshot()) == 3:
                all_receipts_registered.set()

    monkeypatch.setattr(e2e_runner, "E2EHttpClient", SimulatedHttpClient)
    monkeypatch.setattr(e2e_runner, "ReceiptStatusMonitor", SimulatedReceiptStatusMonitor)
    monkeypatch.setattr(
        e2e_runner,
        "_require_verified_live_target",
        lambda: None,
    )
    monkeypatch.setattr(e2e_runner.getpass, "getpass", lambda _prompt: token)

    output = tmp_path / "live-report.json"
    exit_code = main(
        [
            "--profile",
            "smoke",
            "--confirm-start",
            "--api-url",
            API_BASE_URL,
            "--household-id",
            HOUSEHOLD_ID,
            "--output",
            str(output),
        ],
        clock=clock,
        sleep=clock.sleep,
    )

    stdout = capsys.readouterr().out
    report_json = output.read_text(encoding="utf-8")
    assert exit_code == EXIT_OK
    assert captured["token"] == token
    assert captured["timeout_seconds"] == 10.0
    assert "3/3 S3 uploads confirmed, 3/3 done observed" in stdout
    assert token not in stdout
    assert token not in report_json
    assert UPLOAD_URL not in report_json
    assert "DLQ/Textract-throttling: NOT_EVALUATED" in stdout
    assert (
        json.loads(report_json)["quality_assessments"]["dlq_textract_throttling"]["status"]
        == "NOT_EVALUATED"
    )


def test_report_exit_code_marks_unmeasured_targets_as_not_met() -> None:
    report = build_e2e_load_test_report(
        E2ELoadTestConfig.smoke_test("unmeasured-exit-code"),
        (),
        (),
    )

    assert _report_exit_code(report) == EXIT_TARGETS_NOT_MET


def test_peak_exit_code_does_not_treat_unchecked_dlq_as_pass() -> None:
    report = build_e2e_load_test_report(
        E2ELoadTestConfig.peak_load("unchecked-dlq-exit-code"),
        (),
        (),
    )
    for name in (
        "peak_200_uploads_within_60_seconds",
        "peak_200_done_within_180_seconds",
        "peak_api_p95_below_1_second",
    ):
        report.quality_assessments[name] = QualityAssessment(
            status="PASS", reason="Synthetic passing measurement."
        )

    assert report.quality_assessments["dlq_textract_throttling"].status == "NOT_EVALUATED"
    assert _report_exit_code(report) == EXIT_TARGETS_NOT_MET
