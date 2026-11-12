"""Recorded Braket transport helpers.

Sign masking and qubit permutation stay on the customer side. The ticket
routes upload the job JSON and download the JSON receipt.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

ROOT = Path(__file__).resolve().parent
API_URL_DEFAULT = "https://api.znepro.com"
USER_AGENT = "znepro-customer-benchmark/1.0"


def load_environment() -> None:
    """Fill missing variables from .env. Existing environment values win."""
    path = ROOT.parents[3] / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def api_settings() -> dict[str, str]:
    load_environment()
    url = os.environ.get("ZNEPRO_API_URL", API_URL_DEFAULT).rstrip("/")
    key = os.environ.get("ZNEPRO_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ZNEPRO_API_KEY is not set")
    return {"url": url, "key": key}


def _session(api_key: str | None) -> requests.Session:
    session = requests.Session()
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if api_key is not None:
        headers["Authorization"] = f"Bearer {api_key}"
    session.headers.update(headers)
    return session


def _body(response: requests.Response) -> dict[str, Any]:
    text = response.text or ""
    if not text.strip():
        return {}
    try:
        parsed = response.json()
    except ValueError:
        return {"raw": text[:500]}
    if isinstance(parsed, dict):
        return parsed
    return {"raw": parsed}


def strip_qasm_comments(qasm: str) -> str:
    """Drop comments so paper names and coordinates never enter the job JSON."""
    kept: list[str] = []
    for line in qasm.splitlines():
        code = line.split("//", 1)[0].rstrip()
        if code:
            kept.append(code)
    return "\n".join(kept) + "\n"


def qasm_width(qasm: str) -> int:
    match = re.search(r"qreg\s+q\[(\d+)\]", qasm)
    if match is None:
        raise ValueError("OpenQASM is missing qreg q[n]")
    width = int(match.group(1))
    if width < 1:
        raise ValueError("register width is empty")
    return width


def measured_qubits(qasm: str) -> list[int]:
    found: list[int] = []
    for match in re.finditer(r"measure\s+q\[(\d+)\]", qasm):
        qubit = int(match.group(1))
        if qubit not in found:
            found.append(qubit)
    return found


def rewrite_qubits(qasm: str, permutation: list[int]) -> str:
    """Relabel q[i] in one pass. Classical bits stay put."""

    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1))
        if index >= len(permutation):
            raise ValueError(f"qubit {index} is outside the permutation")
        return f"q[{permutation[index]}]"

    lines: list[str] = []
    for line in qasm.splitlines():
        if line.strip().startswith("qreg"):
            lines.append(line)
        else:
            lines.append(re.sub(r"q\[(\d+)\]", replace, line))
    return "\n".join(lines) + "\n"


def map_shot_histogram(
    shots: dict[str, int],
    width: int,
    permutation: list[int],
    flip_qubit: int | None,
) -> dict[str, int]:
    """Move each bit to its virtual qubit. One flipped well reverses the parity."""
    mapped: dict[str, int] = {}
    for key, count in shots.items():
        if count < 0 or any(mark not in "01" for mark in key):
            raise ValueError(f"invalid shot key {key!r}")
        padded = key.rjust(width, "0")
        if len(padded) != width:
            raise ValueError(f"shot key {key!r} is wider than q[{width}]")
        old = [padded[width - 1 - qubit] for qubit in range(width)]
        if flip_qubit is not None:
            old[flip_qubit] = "1" if old[flip_qubit] == "0" else "0"
        moved = ["0"] * width
        for qubit, bit in enumerate(old):
            moved[permutation[qubit]] = bit
        blinded = "".join(moved[width - 1 - qubit] for qubit in range(width))
        mapped[blinded] = mapped.get(blinded, 0) + count
    return mapped


def wire_observable(observable: str, permutation: list[int], qubits: list[int] | None) -> str:
    """Name each Pauli on its virtual well. A 1-qubit X/Y/Z at well 0 stays the bare letter."""
    if observable in {"X", "Y", "Z"} and permutation[0] == 0:
        return observable
    letters = [char.upper() for char in observable if char.upper() in {"X", "Y", "Z"}]
    if observable in {"X", "Y", "Z"}:
        support = [0]
    elif qubits is not None:
        support = list(qubits)
    else:
        support = list(range(len(letters)))
    if len(letters) != len(support):
        raise ValueError(f"observable {observable} does not match support {support}")
    return " ".join(f"{letter}{permutation[qubit]}" for letter, qubit in zip(letters, support))


def client_permutation(width: int, permutation: list[int] | None) -> list[int]:
    if permutation is None:
        order = list(range(width))
        secrets.SystemRandom().shuffle(order)
        return order
    if sorted(permutation) != list(range(width)):
        raise ValueError("permutation is not a bijection of the register")
    return list(permutation)


def blind_hardware_job(
    qasm: str,
    shots: dict[str, int],
    *,
    sign_mask: int | None,
    permutation: list[int] | None,
    expectation_qubits: list[int] | None,
    observable: str,
    hardware_scales: list[dict[str, float]] | None,
    observable_unit: str | None,
    clip_box: bool | None,
) -> dict[str, Any]:
    """Sign-mask and permute a job. The sign and the map stay in this object."""
    sign = secrets.choice((-1, 1)) if sign_mask is None else int(sign_mask)
    if sign not in (-1, 1):
        raise ValueError("sign mask must be -1 or +1")
    anonymous = strip_qasm_comments(qasm)
    width = qasm_width(anonymous)
    order = client_permutation(width, permutation)
    support = list(expectation_qubits) if expectation_qubits is not None else [
        index for index, letter in enumerate(observable) if letter not in {"I", "i"}
    ]
    if observable in {"X", "Y", "Z"}:
        support = [0]
    flip = None if sign == 1 else (measured_qubits(anonymous) or support or [0])[0]
    blinded_shots = map_shot_histogram(shots, width, order, flip)
    blinded_qasm = rewrite_qubits(anonymous, order)
    blinded_support = [order[qubit] for qubit in support]
    visible = pauli_expectation(blinded_shots, observable if observable not in {"X", "Y", "Z"} else "Z", blinded_support)
    blinded_scales = None
    if hardware_scales is not None:
        blinded_scales = [
            {"lambda": float(row["lambda"]), "expectation": sign * float(row["expectation"])}
            for row in hardware_scales
        ]
        visible = sign * float(hardware_scales[0]["expectation"])
    payload: dict[str, Any] = {
        "qasm": blinded_qasm,
        "shots": blinded_shots,
        "backend_name": "superconducting",
    }
    if blinded_scales is not None:
        payload["hardware_scales"] = blinded_scales
    if observable_unit is not None:
        payload["observable_unit"] = observable_unit
    if clip_box is not None:
        payload["clip_box"] = clip_box
    return {
        "sign_mask": sign,
        "permutation": order,
        "flip_qubit": flip,
        "server_visible_expectation": visible,
        "blinded_support": blinded_support,
        "payload": payload,
    }


def r2_object_url(url: str) -> str:
    """Keep the R2 host and path. Drop the presigned query string."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc.endswith("r2.cloudflarestorage.com") or not parsed.path:
        raise ValueError(f"not a Cloudflare R2 URL host: {parsed.netloc!r}")
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def stored_object_url(url: str) -> str:
    """Object path for the saved record, without the account id or account host."""
    if not url:
        return url
    parsed = urlsplit(r2_object_url(url))
    path = re.sub(r"/\d{12}(?=/)", "/redacted", parsed.path)
    return f"https://r2.cloudflarestorage.com{path}"


PUBLIC_RECEIPT_TOP = (
    "status",
    "job_id",
    "task_id",
    "backend_name",
    "target_observable",
    "total_shots",
    "execution_time_ms",
    "error",
)
PUBLIC_METRIC_FIELDS = (
    "mitigated_expectation",
    "raw_hardware_expectation",
    "unmitigated_expectation",
    "calibrated_expectation",
    "mitigation_factor",
    "mitigation_method",
)


def _receipt_metrics(document: dict[str, Any]) -> dict[str, Any]:
    """Read expectation fields from nested ``metrics`` or a legacy flat receipt."""
    nested = document.get("metrics")
    if isinstance(nested, dict) and any(name in nested for name in PUBLIC_METRIC_FIELDS):
        return nested
    return document


def public_receipt(document: dict[str, Any]) -> dict[str, Any]:
    """Keep the customer-visible receipt fields. Drop anything else the service adds."""
    body = {key: document[key] for key in PUBLIC_RECEIPT_TOP if key in document}
    metrics = {
        key: _receipt_metrics(document)[key]
        for key in PUBLIC_METRIC_FIELDS
        if key in _receipt_metrics(document)
    }
    if metrics:
        body["metrics"] = metrics
    return body


def _unblind_metrics(document: dict[str, Any], sign: int) -> dict[str, Any]:
    """Multiply the published hardware expectations by the local sign mask."""
    restored = public_receipt(document)
    metrics = dict(restored.get("metrics") or {})
    for name in (
        "mitigated_expectation",
        "raw_hardware_expectation",
        "unmitigated_expectation",
        "calibrated_expectation",
    ):
        value = metrics.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            metrics[name] = sign * float(value)
    if metrics:
        restored["metrics"] = metrics
        # Flat aliases for case-study helpers that read one expectation.
        for name, value in metrics.items():
            restored[name] = value
    return restored


def _object_put(url: str, body: bytes) -> requests.Response:
    """PUT the job JSON to object storage. The API bearer is not attached."""
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    return requests.put(url, data=body, headers=headers, timeout=120)


def _object_get(url: str) -> requests.Response:
    return requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)


def poll_r2_receipt(get_url: str, key: bytes | None = None, timeout_s: float = 180.0) -> dict[str, Any]:
    """GET the JSON receipt until it parses or the wait expires."""
    _ = key
    deadline = time.perf_counter() + timeout_s
    last_status = 0
    last_error = "receipt was not ready"
    while True:
        response = _object_get(get_url)
        last_status = response.status_code
        if response.status_code == 200 and response.content:
            try:
                opened = json.loads(response.content)
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                last_error = str(exc)
            else:
                if isinstance(opened, dict):
                    return {
                        "http_status": response.status_code,
                        "nbytes": len(response.content),
                        "document": opened,
                    }
                last_error = "receipt is not an object"
        if time.perf_counter() >= deadline:
            return {
                "http_status": last_status,
                "nbytes": 0,
                "document": None,
                "error": last_error,
            }
        time.sleep(0.5)

