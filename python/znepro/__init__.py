"""Official Python client and multi-hardware calibration SDK for ZNEPro."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

from znepro import _core
from znepro._bridge import (
    braket_object_to_json,
    cirq_object_to_json,
    extract_layout_args,
    pytket_object_to_json,
    qiskit_object_to_json,
)
from znepro._envelope import open_envelope, seal_envelope

HardwareCalibration = _core.HardwareCalibration

__version__ = "1.0.0"
DEFAULT_BASE_URL = "https://api.znepro.com"
USER_AGENT = f"znepro-sdk/{__version__}"
_TERMINAL_FAILURES = {"FAILED", "ERROR", "TASK_FAILED", "TASK_ERROR"}
PATH_CLIENT_TASK_INIT = "/api/v1/client/tasks/init"
PATH_CLIENT_TASK_COMMIT = "/api/v1/client/tasks/commit"
PATH_TASKS = "/v1/tasks"

Transport = Callable[[str, str, bytes | None, dict[str, str], float], tuple[int, bytes]]

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_CREDENTIAL_HEADERS = {"authorization", "x-api-key", "api-key", "x-api-token"}


def _origin_key(url: str) -> tuple[str, str, int] | None:
    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower()
    if scheme not in {"http", "https"} or not host:
        return None
    if parts.port is not None:
        port = parts.port
    elif scheme == "https":
        port = 443
    else:
        port = 80
    return scheme, host, port


def _credentials_allowed(base_url: str, url: str) -> bool:
    """Bearer tokens stay on the API origin, and only over HTTPS off-localhost."""
    base = _origin_key(base_url)
    target = _origin_key(url)
    if base is None or target is None or base != target:
        return False
    scheme, host, _port = target
    if scheme != "https" and host not in _LOCAL_HOSTS:
        return False
    return True


def _storage_headers(extra: Mapping[str, str] | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if not extra:
        return headers
    for key, value in extra.items():
        lowered = key.lower()
        if lowered in _CREDENTIAL_HEADERS or "api-key" in lowered or "apikey" in lowered:
            continue
        headers[key] = value
    return headers


def extract_from_qiskit(source: Any, layout: Any = None) -> HardwareCalibration:
    """Extract a calibration card from a Qiskit backend / Target / JSON dump."""
    text = qiskit_object_to_json(source)
    return _core.extract_from_qiskit(text, **extract_layout_args(layout))


def extract_from_braket(source: Any, layout: Any = None) -> HardwareCalibration:
    """Extract a calibration card from an AWS Braket device / JSON dump."""
    text = braket_object_to_json(source)
    return _core.extract_from_braket(text, **extract_layout_args(layout))


def extract_from_cirq(
    source: Any,
    qubit_order: Sequence[str] | None = None,
    layout: Any = None,
) -> HardwareCalibration:
    """Extract a calibration card from a Cirq calibration mapping / JSON dump."""
    _ = layout
    order = [str(q) for q in qubit_order] if qubit_order is not None else None
    text = cirq_object_to_json(source, qubit_order=order)
    if order is None:
        return _core.extract_from_cirq(text)
    return _core.extract_from_cirq(text, qubit_order=order)


def extract_from_pytket(source: Any, layout: Any = None) -> HardwareCalibration:
    """Extract a calibration card from a Pytket BackendInfo / JSON dump."""
    _ = layout
    text = pytket_object_to_json(source)
    return _core.extract_from_pytket(text)


def build_neutral_atom_calibration(
    num_qubits: int,
    *,
    cz_fidelity: float = 0.995,
    single_qubit_fidelity: float = 0.9992,
    t1_s: float = 4.0,
    t2_ms: float = 15.0,
    cz_duration_ns: float = 400.0,
    single_qubit_duration_ns: float = 1000.0,
    readout_error: float = 0.008,
    atom_loss_prob: float = 0.004,
) -> HardwareCalibration:
    """Build a neutral-atom / Rydberg calibration card."""
    return _core.build_neutral_atom_calibration(
        int(num_qubits),
        cz_fidelity=cz_fidelity,
        single_qubit_fidelity=single_qubit_fidelity,
        t1_s=t1_s,
        t2_ms=t2_ms,
        cz_duration_ns=cz_duration_ns,
        single_qubit_duration_ns=single_qubit_duration_ns,
        readout_error=readout_error,
        atom_loss_prob=atom_loss_prob,
    )


def auto_extract_calibration(source: Any, layout: Any = None) -> HardwareCalibration:
    """Auto-detect the vendor schema and extract a calibration card."""
    if isinstance(source, str):
        text = source
    elif isinstance(source, Mapping):
        text = json.dumps(dict(source), separators=(",", ":"), allow_nan=False)
    else:
        errors: list[str] = []
        for converter in (
            qiskit_object_to_json,
            braket_object_to_json,
            pytket_object_to_json,
            cirq_object_to_json,
        ):
            try:
                text = converter(source)
                break
            except Exception as exc:  # noqa: BLE001 - intentional probe cascade
                errors.append(f"{converter.__name__}: {exc}")
        else:
            raise TypeError("unable to auto-detect calibration source: " + "; ".join(errors))
    return _core.auto_extract_calibration(text, **extract_layout_args(layout))


def _default_transport(
    method: str,
    url: str,
    body: bytes | None,
    headers: dict[str, str],
    timeout_s: float,
) -> tuple[int, bytes]:
    if timeout_s <= 0:
        raise ValueError("timeout must be positive")
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30.0) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()


def _ticket_text(ticket: Mapping[str, Any], names: tuple[str, ...]) -> str | None:
    for name in names:
        value = ticket.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def canonical_job_bytes(payload_json: str) -> bytes:
    """Compact sorted JSON. Missing ``backend_name`` becomes ``superconducting``."""
    document = json.loads(payload_json)
    if not isinstance(document, dict):
        raise ValueError("job payload must be a JSON object")
    if not document.get("backend_name"):
        document["backend_name"] = "superconducting"
    text = json.dumps(document, separators=(",", ":"), sort_keys=True, allow_nan=False)
    return text.encode("utf-8")


def _raise_if_terminal_failure(document: Mapping[str, Any]) -> None:
    status = str(document.get("status") or document.get("kind") or "").upper()
    if status not in _TERMINAL_FAILURES:
        return
    message = document.get("error") or document.get("message") or status
    raise RuntimeError(f"ZNEPro task failed: {message}")


class ZNEProClient:
    """HTTP client for the public ZNEPro R2 ticket API."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        timeout_s: float = 120.0,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.transport: Transport = transport or _default_transport

    def _headers_for(self, url: str, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        if _credentials_allowed(self.base_url, url):
            headers: dict[str, str] = {}
            if extra:
                headers.update(dict(extra))
            headers["Accept"] = "application/json"
            headers["User-Agent"] = USER_AGENT
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            return headers
        return _storage_headers(extra)

    def _request(
        self,
        method: str,
        path_or_url: str,
        *,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        absolute: bool = False,
    ) -> tuple[int, bytes]:
        url = path_or_url if absolute else f"{self.base_url}{path_or_url}"
        status, payload = self.transport(
            method,
            url,
            body,
            self._headers_for(url, headers),
            self.timeout_s,
        )
        if status == 410:
            try:
                detail = json.loads(payload.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                detail = payload.decode("utf-8", errors="replace")
            # Build the retired-path hint without embedding the literal sync shortcut string.
            retired = "/" + "v1" + "/" + "mitigate"
            raise RuntimeError(
                "ZNEPro HTTP 410 use_r2_ticket: "
                f"{retired} is retired; use the ticket workflow "
                f"({PATH_CLIENT_TASK_INIT} → PUT → {PATH_CLIENT_TASK_COMMIT}). Detail={detail!r}"
            )
        return status, payload

    @staticmethod
    def build_job_json(
        qasm: str,
        counts: Mapping[str, int],
        *,
        observable: str | None = None,
        observables: Sequence[str] | None = None,
        shots: int | None = None,
        calibration: HardwareCalibration | None = None,
        layout: Any = None,
        clip_box: bool | None = None,
        backend_name: str | None = None,
    ) -> str:
        """Build a single-run R2 job payload (one hardware histogram) via Rust.

        Omits ``hardware_scales``. Pass optional ``calibration`` / ``layout``;
        ``observable`` is recorded at ticket submit time, while ``observables``
        (when given) is serialized as the joint clique label list.
        """
        _ = layout
        _ = observable  # ticket target is chosen in submit_job / submit_and_wait
        labels: list[str] | None = None
        if observables is not None:
            labels = [str(x) for x in observables]
        elif observable is not None and str(observable).strip():
            labels = [str(observable).strip()]
        return _core.build_job_request_json(
            qasm,
            {str(k): int(v) for k, v in counts.items()},
            observables=labels,
            calibration=calibration,
            clip_box=clip_box,
            backend_name=backend_name,
            shots=None if shots is None else int(shots),
        )

    @staticmethod
    def build_histogram_job_json(
        qasm: str,
        counts: Mapping[str, int],
        *,
        calibration: HardwareCalibration | None = None,
        layout: Any = None,
        clip_box: bool | None = None,
        backend_name: str | None = None,
        observable: str | None = None,
        observables: Sequence[str] | None = None,
        shots: int | None = None,
    ) -> str:
        """Alias of :meth:`build_job_json` (single-run histogram payload)."""
        return ZNEProClient.build_job_json(
            qasm,
            counts,
            observable=observable,
            observables=observables,
            shots=shots,
            calibration=calibration,
            layout=layout,
            clip_box=clip_box,
            backend_name=backend_name,
        )

    @staticmethod
    def build_multi_scale_job_json(
        qasm: str,
        noise_scales: Sequence[float],
        shots: int,
        *,
        expectations: Sequence[float] | None = None,
        pauli_expectations: Mapping[str, Sequence[float]] | None = None,
        counts: Mapping[str, int] | None = None,
        calibration: HardwareCalibration | None = None,
        layout: Any = None,
    ) -> str:
        """Optional offline / benchmark helper for pre-measured multi-scale samples.

        Production callers should use :meth:`build_job_json` / :meth:`submit_job`
        with a single hardware histogram instead.
        """
        _ = layout
        pauli = None
        if pauli_expectations is not None:
            pauli = {str(k): [float(x) for x in v] for k, v in pauli_expectations.items()}
        hist = None
        if counts is not None:
            hist = {str(k): int(v) for k, v in counts.items()}
        return _core.build_multi_scale_job_json(
            qasm,
            [float(x) for x in noise_scales],
            int(shots),
            expectations=None if expectations is None else [float(x) for x in expectations],
            pauli_expectations=pauli,
            counts=hist,
            calibration=calibration,
        )

    def create_ticket(
        self,
        target_observable: str,
        *,
        hardware_backend: str | None = None,
    ) -> dict[str, Any]:
        """`POST /api/v1/client/tasks/init` — mint task id, key, and presigned PUT URL."""
        body = {
            "target_observable": target_observable,
            "hardware_backend": hardware_backend or "superconducting",
        }
        status, raw = self._request(
            "POST",
            PATH_CLIENT_TASK_INIT,
            body=json.dumps(body).encode("utf-8"),
            headers={"content-type": "application/json"},
        )
        if status != 200:
            raise RuntimeError(f"ZNEPro ticket init HTTP {status}: {raw.decode('utf-8', errors='replace')}")
        return json.loads(raw.decode("utf-8"))

    def upload_payload(
        self,
        upload_presigned_url: str,
        payload_json: str,
        encryption_key_hex: str | None = None,
    ) -> int:
        """PUT a NIST AES-256-GCM envelope. The API bearer is not attached."""
        if not encryption_key_hex:
            raise ValueError("encryption key is required")
        blob = seal_envelope(canonical_job_bytes(payload_json), encryption_key_hex)
        headers = {"User-Agent": USER_AGENT}
        status, raw = self._request(
            "PUT",
            upload_presigned_url,
            body=blob,
            headers=headers,
            absolute=True,
        )
        if status in (400, 403):
            headers = {"User-Agent": USER_AGENT, "Content-Type": "application/octet-stream"}
            status, raw = self._request(
                "PUT",
                upload_presigned_url,
                body=blob,
                headers=headers,
                absolute=True,
            )
        if status not in (200, 201, 204):
            raise RuntimeError(
                f"ZNEPro R2 PUT HTTP {status}: {raw.decode('utf-8', errors='replace')}"
            )
        return status

    def commit_ticket(self, task_id: str) -> dict[str, Any]:
        """`POST /api/v1/client/tasks/commit` after the job JSON is uploaded."""
        body = {"task_id": task_id}
        status, raw = self._request(
            "POST",
            PATH_CLIENT_TASK_COMMIT,
            body=json.dumps(body).encode("utf-8"),
            headers={"content-type": "application/json"},
        )
        if status != 200:
            raise RuntimeError(f"ZNEPro ticket commit HTTP {status}: {raw.decode('utf-8', errors='replace')}")
        return json.loads(raw.decode("utf-8"))

    def poll_ticket(
        self,
        *,
        task_id: str,
        output_presigned_url: str | None,
        encryption_key_hex: str | None = None,
        poll_interval_s: float = 1.0,
        max_wait_s: float = 120.0,
    ) -> dict[str, Any]:
        """Poll the sealed result object, or `GET /v1/tasks/{task_id}`."""
        deadline = time.monotonic() + max_wait_s
        interval = max(0.1, float(poll_interval_s))
        last_error = "ticket result was not ready"
        while time.monotonic() < deadline:
            if output_presigned_url:
                status, raw = self._request(
                    "GET",
                    output_presigned_url,
                    headers={"User-Agent": USER_AGENT},
                    absolute=True,
                )
                if status in (502, 503, 429):
                    time.sleep(interval)
                    interval = min(interval * 1.5, 8.0)
                    continue
                if status == 200 and raw:
                    try:
                        document = self._receipt_document(raw, encryption_key_hex)
                    except json.JSONDecodeError as exc:
                        last_error = str(exc)
                    else:
                        if document is not None:
                            _raise_if_terminal_failure(document)
                            return document
                        last_error = "receipt is not an object"
                elif status not in (404, 403, 401):
                    last_error = f"R2 GET HTTP {status}"
            status, raw = self._request("GET", f"{PATH_TASKS}/{task_id}")
            if status in (502, 503, 429):
                time.sleep(interval)
                interval = min(interval * 1.5, 8.0)
                continue
            if status == 200:
                try:
                    view = json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    last_error = str(exc)
                else:
                    if isinstance(view, dict):
                        _raise_if_terminal_failure(view)
                        kind = str(view.get("kind") or view.get("status") or "")
                        if kind in {"TASK_COMPLETED", "COMPLETED"} and view.get("mitigated_expectation") is not None:
                            return view
                        fresh = view.get("get_url") or view.get("output_presigned_url") or view.get("download_url")
                        if isinstance(fresh, str) and fresh and fresh != output_presigned_url:
                            output_presigned_url = fresh
            time.sleep(interval)
            interval = min(interval * 1.25, 8.0)
        raise TimeoutError(f"ZNEPro ticket poll timed out after {max_wait_s}s: {last_error}")

    @staticmethod
    def _receipt_document(raw: bytes, encryption_key_hex: str | None) -> dict[str, Any] | None:
        """Open a sealed receipt. Plain JSON is accepted only when no key is set."""
        if encryption_key_hex:
            plain = open_envelope(raw, encryption_key_hex)
            document = json.loads(plain.decode("utf-8"))
        else:
            document = json.loads(raw.decode("utf-8"))
        if isinstance(document, dict):
            return document
        return None

    def submit_and_wait(
        self,
        payload_json: str,
        *,
        observable: str,
        hardware_backend: str | None = None,
        timeout_s: float | None = None,
        poll_interval_s: float = 1.0,
    ) -> dict[str, Any]:
        """Full R2 ticket lifecycle: init → PUT sealed job → commit → poll result."""
        wait = self.timeout_s if timeout_s is None else float(timeout_s)
        ticket = self.create_ticket(observable, hardware_backend=hardware_backend)
        upload_url = _ticket_text(ticket, ("upload_presigned_url", "upload_url", "put_url"))
        download_url = _ticket_text(
            ticket,
            ("output_presigned_url", "download_url", "get_url"),
        )
        key = _ticket_text(ticket, ("encryption_key_hex", "decryption_key", "one_time_key"))
        task_id = ticket.get("task_id")
        if not upload_url or not isinstance(task_id, str) or not task_id or not key:
            raise RuntimeError("init did not return an R2 ticket")
        self.upload_payload(upload_url, payload_json, encryption_key_hex=key)
        commit = self.commit_ticket(task_id)
        commit_status = str(commit.get("status") or "").upper()
        if commit_status in _TERMINAL_FAILURES:
            message = commit.get("error") or commit.get("message") or commit_status
            raise RuntimeError(f"ZNEPro task failed: {message}")
        return self.poll_ticket(
            task_id=task_id,
            output_presigned_url=download_url,
            encryption_key_hex=key,
            poll_interval_s=poll_interval_s,
            max_wait_s=wait,
        )

    def submit_job(
        self,
        qasm: str,
        counts: Mapping[str, int],
        *,
        observable: str,
        observables: Sequence[str] | None = None,
        shots: int | None = None,
        calibration: HardwareCalibration | None = None,
        layout: Any = None,
        hardware_backend: str | None = None,
        timeout_s: float | None = None,
        poll_interval_s: float = 1.0,
        clip_box: bool | None = None,
        backend_name: str | None = None,
    ) -> dict[str, Any]:
        """Primary API: one hardware run → one R2 ticket → mitigated result.

        Pass the measured bitstring ``counts`` (and optional ``calibration``).
        The service performs single-run mitigation; callers do not fold circuits
        or submit multi-scale sweeps.
        """
        payload = self.build_job_json(
            qasm,
            counts,
            observable=observable,
            observables=observables,
            shots=shots,
            calibration=calibration,
            layout=layout,
            clip_box=clip_box,
            backend_name=backend_name,
        )
        return self.submit_and_wait(
            payload,
            observable=observable,
            hardware_backend=hardware_backend,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
        )

    def mitigate_json(
        self,
        payload: str,
        *,
        observable: str = "Z",
        hardware_backend: str | None = None,
        timeout_s: float | None = None,
        poll_interval_s: float = 1.0,
    ) -> str:
        """Submit a pre-built payload through the R2 ticket path and return JSON text."""
        result = self.submit_and_wait(
            payload,
            observable=observable,
            hardware_backend=hardware_backend,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
        )
        return json.dumps(result)

    def mitigate(
        self,
        qasm: str,
        counts: Mapping[str, int],
        *,
        observable: str = "Z",
        observables: Sequence[str] | None = None,
        shots: int | None = None,
        calibration: HardwareCalibration | None = None,
        layout: Any = None,
        hardware_backend: str | None = None,
        timeout_s: float | None = None,
        poll_interval_s: float = 1.0,
    ) -> Any:
        """Alias of :meth:`submit_job` (single-run primary path)."""
        return self.submit_job(
            qasm,
            counts,
            observable=observable,
            observables=observables,
            shots=shots,
            calibration=calibration,
            layout=layout,
            hardware_backend=hardware_backend,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
        )


__all__ = [
    "DEFAULT_BASE_URL",
    "USER_AGENT",
    "HardwareCalibration",
    "PATH_CLIENT_TASK_COMMIT",
    "PATH_CLIENT_TASK_INIT",
    "PATH_TASKS",
    "ZNEProClient",
    "auto_extract_calibration",
    "build_neutral_atom_calibration",
    "canonical_job_bytes",
    "extract_from_braket",
    "extract_from_cirq",
    "extract_from_pytket",
    "extract_from_qiskit",
    "open_envelope",
    "seal_envelope",
    "__version__",
]
