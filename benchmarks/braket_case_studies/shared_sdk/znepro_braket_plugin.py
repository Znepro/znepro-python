"""Thin client a Braket user adds on top of an existing project.

The helper never sends OpenQASM or hardware expectations in the API body.
It blinds them locally, PUTs that JSON to the Cloudflare R2 URL from
``POST /api/v1/client/tasks/init``, commits the task, then GETs the JSON
receipt and unblinds it with the local sign.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import r2_bridge as znepro

OPAQUE_R2_KEY = re.compile(
    r"^tasks/[0-9a-f]{16}/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/input\.zk$"
)


_PUBLIC_TOP = {
    "status",
    "job_id",
    "task_id",
    "backend_name",
    "target_observable",
    "total_shots",
    "execution_time_ms",
    "error",
    "metrics",
}
_PUBLIC_METRICS = {
    "mitigated_expectation",
    "raw_hardware_expectation",
    "unmitigated_expectation",
    "calibrated_expectation",
    "mitigation_factor",
    "mitigation_method",
}


def _require_public_receipt(document: dict[str, Any]) -> None:
    """The decrypted receipt must be the public metrics object and nothing else."""
    metrics = document.get("metrics")
    if not isinstance(metrics, dict) or "mitigated_expectation" not in metrics:
        raise RuntimeError("receipt is missing metrics.mitigated_expectation")
    if set(document) - _PUBLIC_TOP or set(metrics) - _PUBLIC_METRICS:
        raise RuntimeError("receipt included a non-public field")


def execute_blinded_job(
    *,
    qasm: str,
    shots: dict[str, int],
    observable: str,
    scales: list[dict[str, float]],
    sign_mask: int,
    permutation: list[int],
    upload_dir: Path,
    download_dir: Path,
    expectation_qubits: list[int] | None = None,
    observable_unit: str | None = None,
    backend_name: str = "superconducting",
    forbidden_text: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Run one blinded job and write the uploaded and downloaded artifacts."""
    if sign_mask not in (-1, 1):
        raise ValueError("sign_mask must be -1 or +1")
    blinded = znepro.blind_hardware_job(
        qasm,
        shots,
        sign_mask=sign_mask,
        permutation=permutation,
        expectation_qubits=expectation_qubits,
        observable=observable,
        hardware_scales=scales,
        observable_unit=observable_unit,
        clip_box=False if observable_unit == "hartree" else None,
    )
    payload = dict(blinded["payload"])
    payload["backend_name"] = backend_name
    plaintext = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    leaked = [token for token in forbidden_text if token.lower() in plaintext.lower().decode("utf-8", "ignore")]
    if leaked:
        raise RuntimeError(f"blinded payload still contains {leaked}")

    settings = znepro.api_settings()
    session = znepro._session(settings["key"])
    wire = znepro.wire_observable(observable, blinded["permutation"], expectation_qubits)
    init = session.post(
        f"{settings['url']}/api/v1/client/tasks/init",
        json={"target_observable": wire, "hardware_backend": backend_name},
        timeout=30,
    )
    init_body = znepro._body(init)
    if init.status_code != 200:
        raise RuntimeError(f"init HTTP {init.status_code}: {init_body.get('error')}")
    put_raw = str(init_body.get("upload_presigned_url") or init_body.get("put_url") or "")
    get_raw = str(init_body.get("output_presigned_url") or init_body.get("get_url") or "")
    task_id = str(init_body["task_id"])
    r2_key = str(init_body.get("r2_key") or "")
    if OPAQUE_R2_KEY.fullmatch(r2_key) is None:
        raise RuntimeError("init r2_key is not tasks/<16 hex>/<uuid>/input.zk")
    uploaded = znepro._object_put(put_raw, plaintext)
    if uploaded.status_code != 200:
        raise RuntimeError(f"R2 PUT HTTP {uploaded.status_code}")
    commit = session.post(
        f"{settings['url']}/api/v1/client/tasks/commit",
        json={"task_id": task_id},
        timeout=30,
    )
    commit_body = znepro._body(commit)
    if commit.status_code != 200 or commit_body.get("status") != "QUEUED":
        raise RuntimeError(f"commit HTTP {commit.status_code}: {commit_body}")
    receipt_bytes, document = _poll_receipt(get_raw)
    _require_public_receipt(document)

    upload_dir.mkdir(parents=True, exist_ok=True)
    download_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / "input.zk").write_bytes(plaintext)
    (upload_dir / "blinded_inner_payload.json").write_bytes(plaintext)
    (download_dir / "output.zk").write_bytes(receipt_bytes)
    (download_dir / "server_blinded_output.json").write_text(
        json.dumps(znepro.public_receipt(document), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    put_public = _redacted_object_url(put_raw)
    get_public = _redacted_object_url(get_raw)
    metadata = {
        "task_id": task_id,
        "r2_key": r2_key,
        "r2_host": "r2.cloudflarestorage.com",
        "input_object_url": put_public,
        "output_object_url": get_public,
        "put_http_status": uploaded.status_code,
        "get_http_status": 200,
        "commit_status": commit_body.get("status"),
        "wire_observable": wire,
        "sign_mask": sign_mask,
        "input_bytes": len(plaintext),
        "output_bytes": len(receipt_bytes),
        "input_sha256": hashlib.sha256(plaintext).hexdigest(),
        "output_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "blinded_plaintext_sha256": hashlib.sha256(plaintext).hexdigest(),
    }
    (upload_dir / "r2_upload_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    public = znepro.public_receipt(document)
    unblinded = znepro._unblind_metrics(document, sign_mask)
    if document.get("status") != "COMPLETED":
        raise RuntimeError(f"task {task_id} {document.get('status')}: {document.get('error')}")
    # Flat aliases match the published metrics object for case-study helpers.
    server_view = dict(public)
    for key, value in (public.get("metrics") or {}).items():
        server_view[key] = value
    return {
        "task_id": task_id,
        "sign_mask": sign_mask,
        "wire_observable": wire,
        "metadata": metadata,
        "server": server_view,
        "unblinded": unblinded,
        "server_visible_expectation": blinded["server_visible_expectation"],
    }


def _redact_account(value: str) -> str:
    return re.sub(r"\b\d{12}\b", "redacted", value)


def _redacted_object_url(url: str) -> str:
    """Host and path only, with the account id removed from both."""
    from urllib.parse import urlsplit

    parsed = urlsplit(znepro.r2_object_url(url))
    path = _redact_account(parsed.path)
    return f"https://r2.cloudflarestorage.com{path}"


def _poll_receipt(get_url: str, timeout_s: float = 180.0) -> tuple[bytes, dict[str, Any]]:
    import time

    deadline = time.perf_counter() + timeout_s
    last = "receipt was not ready"
    while True:
        response = znepro._object_get(get_url)
        if response.status_code == 200 and response.content:
            try:
                document = json.loads(response.content)
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                last = str(exc)
            else:
                if isinstance(document, dict):
                    return response.content, document
                last = "receipt is not an object"
        if time.perf_counter() >= deadline:
            raise RuntimeError(last)
        time.sleep(0.5)


def correlator_shots(expectation: float, total: int, width: int, qubits: tuple[int, int] = (0, 1)) -> dict[str, int]:
    """Histogram whose parity on ``qubits`` equals ``expectation``."""
    even = int(round((1.0 + expectation) * total / 2.0))
    even = max(0, min(total, even))
    odd = total - even
    low = odd // 2
    left, right = qubits

    def key(ones: set[int]) -> str:
        chars = ["0"] * width
        for qubit in ones:
            chars[width - 1 - qubit] = "1"
        return "".join(chars)

    return {
        key(set()): even,
        key({left, right}): 0,
        key({left}): odd - low,
        key({right}): low,
    }
