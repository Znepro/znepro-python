"""q0_left wire histogram: character i is q[i], and Pauli index i is q[i]."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from znepro import (
    ZNEProClient,
    counts_from_braket,
    counts_from_qiskit,
    normalize_counts_bit_order,
    open_envelope,
    seal_envelope,
)

_TICKET_KEY = "22" * 32
_QASM = "OPENQASM 2.0;\nqreg q[3];\ncreg c[3];\nmeasure q[0] -> c[0];\nmeasure q[1] -> c[1];\nmeasure q[2] -> c[2];\n"
_PAULI = {
    "ZII": -1.0,
    "IZI": 1.0,
    "IIZ": 1.0,
    "ZZI": -1.0,
    "IZZ": 1.0,
}


def _z_expectation(counts: dict[str, int], pauli: str) -> float:
    total = sum(counts.values())
    total_sign = 0
    for key, count in counts.items():
        sign = 1
        for index, letter in enumerate(pauli):
            if letter == "I":
                continue
            if letter != "Z":
                raise AssertionError(letter)
            if key[index] == "1":
                sign *= -1
        total_sign += sign * count
    return total_sign / total


def test_asymmetric_qiskit_and_braket_counts_share_one_wire_payload():
    braket = ZNEProClient.build_job_json(
        _QASM,
        {"100": 1000},
        bit_order="braket",
        shots=1000,
        observable="ZII",
    )
    default = ZNEProClient.build_job_json(
        _QASM,
        {"100": 1000},
        shots=1000,
        observable="ZII",
    )
    qiskit = ZNEProClient.build_job_json(
        _QASM,
        {"001": 1000},
        bit_order="qiskit",
        shots=1000,
        observable="ZII",
    )
    braket_shots = json.loads(braket)["shots"]
    assert json.loads(default)["shots"] == braket_shots == {"100": 1000}
    assert json.loads(qiskit)["shots"] == braket_shots
    assert braket == qiskit
    for label, expected in _PAULI.items():
        assert _z_expectation(braket_shots, label) == expected
        assert _z_expectation(counts_from_qiskit({"001": 1000}), label) == expected
        assert _z_expectation(counts_from_braket({"100": 1000}), label) == expected

    class _QiskitResult:
        def get_counts(self) -> dict[str, int]:
            return {"0 01": 1000}

    assert counts_from_qiskit(_QiskitResult()) == {"100": 1000}
    assert normalize_counts_bit_order({"0 01": 1000}, "qiskit") == {"100": 1000}


def test_qiskit_spaces_are_stripped_and_bad_keys_raise():
    assert normalize_counts_bit_order({"0 10": 4}, bit_order="qiskit") == {"010": 4}
    with pytest.raises(ValueError, match="invalid shot key"):
        normalize_counts_bit_order({"10x": 1}, bit_order="qiskit")
    with pytest.raises(ValueError, match="invalid shot key"):
        normalize_counts_bit_order({"102": 1})
    with pytest.raises(ValueError, match="width"):
        normalize_counts_bit_order({"10": 1, "1": 1}, bit_order="q0_right")
    with pytest.raises(ValueError, match="width"):
        normalize_counts_bit_order({"100": 1, "00": 1}, num_qubits=3)
    with pytest.raises(ValueError, match="unknown bit_order"):
        normalize_counts_bit_order({"1": 1}, bit_order="sideways")


def test_submit_paths_upload_the_same_q0_left_histogram():
    put_url = "https://example-r2.cloudflarestorage.com/bucket/in?X-Amz-Signature=putsig"
    get_url = "https://example-r2.cloudflarestorage.com/bucket/out?X-Amz-Signature=getsig"
    uploaded: list[dict[str, int]] = []

    def transport(method, url, body, headers, timeout_s):  # noqa: ARG001
        lowered = {str(key).lower(): str(value) for key, value in headers.items()}
        if method == "POST" and url.endswith("/api/v1/client/tasks/init"):
            return 200, json.dumps(
                {
                    "task_id": "task-bits",
                    "upload_presigned_url": put_url,
                    "output_presigned_url": get_url,
                    "encryption_key_hex": _TICKET_KEY,
                }
            ).encode()
        if method == "PUT" and url == put_url:
            assert "authorization" not in lowered
            uploaded.append(json.loads(open_envelope(body, _TICKET_KEY))["shots"])
            return 200, b""
        if method == "POST" and url.endswith("/api/v1/client/tasks/commit"):
            return 200, json.dumps({"status": "QUEUED"}).encode()
        if method == "GET" and url == get_url:
            receipt = {"status": "COMPLETED", "mitigated_expectation": -0.8, "engine_version": "0.1.1"}
            return 200, seal_envelope(json.dumps(receipt).encode(), _TICKET_KEY, nonce=b"0123456789ab")
        raise AssertionError(f"unexpected request {method} {url}")

    client = ZNEProClient(api_key="test", transport=transport, timeout_s=5)
    raw_qiskit = json.dumps({"qasm": _QASM, "shots": {"001": 900, "000": 100}})
    waited = client.submit_and_wait(
        raw_qiskit,
        observable="ZII",
        bit_order="qiskit",
        timeout_s=2,
        poll_interval_s=0.01,
    )
    mitigated = json.loads(
        client.mitigate_json(
            raw_qiskit,
            observable="ZII",
            bit_order="qiskit",
            timeout_s=2,
            poll_interval_s=0.01,
        )
    )
    submitted = client.submit_job(
        _QASM,
        {"001": 900, "000": 100},
        observable="ZII",
        shots=1000,
        bit_order="qiskit",
        timeout_s=2,
        poll_interval_s=0.01,
    )
    assert waited["engine_version"] == mitigated["engine_version"] == submitted["engine_version"] == "0.1.1"
    assert uploaded == [{"000": 100, "100": 900}] * 3


def test_repository_has_no_stale_bit_order_comments():
    root = Path(__file__).resolve().parents[1]
    needles = ("right" + "most", "little-" + "end" + "ian", "end" + "ian")
    skip = {".git", ".venv", "target", "__pycache__", ".pytest_cache"}
    hits: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in skip for part in path.parts):
            continue
        if path.suffix not in {".py", ".pyi", ".rs", ".md", ".toml"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        for needle in needles:
            if needle in text:
                hits.append(f"{path.relative_to(root)}:{needle}")
    assert hits == []
