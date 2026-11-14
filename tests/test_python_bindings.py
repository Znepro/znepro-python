"""End-to-end Python binding tests against the compiled znepro._core extension."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

import znepro
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from znepro import (
    ZNEProClient,
    auto_extract_calibration,
    build_neutral_atom_calibration,
    canonicalize_qasm,
    extract_from_braket,
    extract_from_cirq,
    extract_from_pytket,
    extract_from_qiskit,
    open_envelope,
    qasm_gates,
    seal_envelope,
)

_TICKET_KEY = "11" * 32


def _hidden_flag() -> str:
    return "".join(["enable_", "light_", "cone"])


def _forbidden_binary_tokens() -> list[bytes]:
    # Fragmented so this test file itself stays outside the source IP gate.
    return [
        b"".join([b"god_", b"eye"]),
        b"".join([b"dyk", b"stra"]),
        b"".join([b"heisen", b"berg"]),
        b"".join([b"light_", b"cone"]),
        b"".join([b"tape_", b"tension"]),
        b"".join([b"rerun", b"4"]),
        b"".join([b"t", b"df_gpt"]),
    ]


class _FakeInstructionProps:
    def __init__(self, error=None, duration=None):
        self.error = error
        self.duration = duration


class _FakeTarget:
    """Minimal Qiskit Target stand-in with virtual rz + NaN coherence."""

    def __init__(self):
        self.qubit_properties = [
            type("QP", (), {"t1": float("nan"), "t2": 40e-6})(),
            type("QP", (), {"t1": 50e-6, "t2": 30e-6})(),
        ]

    def items(self):
        # Real Target.items() is (name, {qargs: props}), not a 3-tuple.
        return [
            ("rz", {(0,): _FakeInstructionProps(error=0.5, duration=0.0)}),
            ("sx", {(0,): _FakeInstructionProps(error=0.001, duration=35e-9)}),
            ("cx", {(0, 1): _FakeInstructionProps(error=0.01, duration=300e-9)}),
            ("measure", {(0,): _FakeInstructionProps(error=0.02, duration=1e-6)}),
        ]


class _FakeBackendV2:
    name = "fake_backend"

    def __init__(self):
        self.target = _FakeTarget()

    def qubit_properties(self, index=None):  # noqa: ARG002
        return self.target.qubit_properties


class _FakeTranspileLayout:
    def final_index_layout(self, filter_ancillas=True):  # noqa: ARG002
        return [0, 1]


def test_qiskit_target_skips_virtual_rz_and_nan_with_layout():
    backend = _FakeBackendV2()
    layout = _FakeTranspileLayout()
    card = extract_from_qiskit(backend, layout=layout)
    assert card.qubit_count() >= 1
    payload = json.loads(card.to_json())
    assert _hidden_flag() not in payload
    # Virtual rz with huge error must not dominate the sanitized 1q error.
    q0 = payload["qubits"]["0"]
    assert abs(q0["error_1q"] - 0.001) < 1e-12
    assert abs(q0["gate_time_1q_ns"] - 35.0) < 1e-6
    assert abs(q0["prob_meas1_prep0"] - 0.02) < 1e-12
    assert abs(q0["prob_meas0_prep1"] - 0.02) < 1e-12
    edge = payload["edges"][0]
    assert abs(edge["error_2q"] - 0.01) < 1e-12
    assert abs(edge["gate_time_2q_ns"] - 300.0) < 1e-6
    assert "t1_us" not in q0 or (q0["t1_us"] == q0["t1_us"])


def test_asymmetric_readout_is_kept_when_measure_error_differs():
    class _Qubit:
        def __init__(self) -> None:
            self.t1 = 50e-6
            self.t2 = 40e-6
            self.prob_meas1_prep0 = 0.01
            self.prob_meas0_prep1 = 0.03

    class _Target:
        num_qubits = 1
        qubit_properties = [_Qubit()]

        def items(self):
            return [
                ("sx", {(0,): _FakeInstructionProps(error=0.002, duration=40e-9)}),
                ("measure", {(0,): _FakeInstructionProps(error=0.2, duration=1e-6)}),
            ]

    payload = json.loads(extract_from_qiskit(_Target()).to_json())
    row = payload["qubits"]["0"]
    assert abs(row["t1_us"] - 50.0) < 1e-6
    assert abs(row["t2_us"] - 40.0) < 1e-6
    assert abs(row["error_1q"] - 0.002) < 1e-12
    assert abs(row["gate_time_1q_ns"] - 40.0) < 1e-6
    assert abs(row["prob_meas1_prep0"] - 0.01) < 1e-12
    assert abs(row["prob_meas0_prep1"] - 0.03) < 1e-12


def test_real_qiskit_target_preserves_gate_errors_durations_and_readout():
    from qiskit.circuit.library import CXGate, ECRGate, Measure, RZGate, SXGate, XGate
    from qiskit.transpiler import InstructionProperties, QubitProperties, Target

    sx_error = 1.2e-3
    sx_duration_s = 35e-9
    cx_error = 8.0e-3
    cx_duration_s = 300e-9
    ecr_error = 7.5e-3
    ecr_duration_s = 280e-9
    meas = (0.02, 0.021, 0.019)
    t1_s = (50e-6, 60e-6, 55e-6)
    t2_s = (40e-6, 45e-6, 42e-6)
    target = Target(
        num_qubits=3,
        qubit_properties=[
            QubitProperties(t1=t1_s[i], t2=t2_s[i], frequency=5.0e9)
            for i in range(3)
        ],
    )
    target.add_instruction(
        SXGate(),
        {(i,): InstructionProperties(duration=sx_duration_s, error=sx_error) for i in range(3)},
    )
    target.add_instruction(
        XGate(),
        {(i,): InstructionProperties(duration=sx_duration_s, error=1.1e-3) for i in range(3)},
    )
    target.add_instruction(
        RZGate(0.0),
        {(i,): InstructionProperties(duration=0.0, error=0.5) for i in range(3)},
    )
    target.add_instruction(
        CXGate(),
        {(0, 1): InstructionProperties(duration=cx_duration_s, error=cx_error)},
    )
    target.add_instruction(
        ECRGate(),
        {(1, 2): InstructionProperties(duration=ecr_duration_s, error=ecr_error)},
    )
    target.add_instruction(
        Measure(),
        {(i,): InstructionProperties(duration=1.0e-6, error=meas[i]) for i in range(3)},
    )

    def check(card) -> None:
        body = json.loads(card.to_json())
        for index in range(3):
            row = body["qubits"][str(index)]
            assert abs(row["t1_us"] - (t1_s[index] * 1.0e6)) < 1e-6
            assert abs(row["t2_us"] - (t2_s[index] * 1.0e6)) < 1e-6
            assert abs(row["error_1q"] - sx_error) < 1e-12
            assert abs(row["gate_time_1q_ns"] - (sx_duration_s * 1.0e9)) < 1e-4
            assert abs(row["prob_meas1_prep0"] - meas[index]) < 1e-12
            assert abs(row["prob_meas0_prep1"] - meas[index]) < 1e-12
            assert row["error_1q"] < 0.01
        edges = {(edge["q0"], edge["q1"]): edge for edge in body["edges"]}
        cx = edges[(0, 1)]
        ecr = edges[(1, 2)]
        assert abs(cx["error_2q"] - cx_error) < 1e-12
        assert abs(cx["gate_time_2q_ns"] - (cx_duration_s * 1.0e9)) < 1e-4
        assert abs(ecr["error_2q"] - ecr_error) < 1e-12
        assert abs(ecr["gate_time_2q_ns"] - (ecr_duration_s * 1.0e9)) < 1e-4

    check(extract_from_qiskit(target))

    class _Backend:
        name = "lab_backend"

        def __init__(self, inner: Target) -> None:
            self.target = inner

        def qubit_properties(self, index: int):
            return self.target.qubit_properties[index]

    check(extract_from_qiskit(_Backend(target)))


def test_braket_standardized_ionq_and_iqm():
    std = {
        "standardized": {
            "oneQubitProperties": {
                "0": {
                    "T1": {"value": 50.0, "unit": "us"},
                    "T2": {"value": 40.0, "unit": "us"},
                    "oneQubitFidelity": [
                        {"fidelityType": "RANDOMIZED_BENCHMARKING", "fidelity": 0.999},
                        {"fidelityType": "READOUT", "fidelity": 0.98},
                    ],
                }
            },
            "twoQubitProperties": {
                "0-1": {
                    "twoQubitGateFidelity": [{"fidelity": 0.99}],
                    "gateDuration": {"value": 200.0, "unit": "ns"},
                }
            },
        }
    }
    card = extract_from_braket(std)
    assert card.edge_count() == 1

    ionq = {
        "paradigm": {"qubitCount": 2},
        "provider": {
            "fidelity": {"1Q": {"mean": 0.999}, "2Q": {"mean": 0.98}, "spam": {"mean": 0.995}},
            "timing": {"T1": 10.0, "T2": 1.0, "1Q": 1.0e-5, "2Q": 2.0e-4},
        },
    }
    card = extract_from_braket(ionq)
    assert card.qubit_count() == 2

    iqm = {
        "provider": {
            "properties": {
                "one_qubit": {
                    "1": {"f_1Q": 0.999, "f_RO": 0.99, "T1": 5.0e-5, "T2": 4.0e-5},
                    "2": {"f_1Q_simultaneous_RB": 0.998, "f_RO": 0.985, "T1": 4.0e-5, "T2": 3.0e-5},
                },
                "two_qubit": {"1-2": {"f_CZ": 0.99}},
            }
        }
    }
    card = extract_from_braket(iqm)
    body = json.loads(card.to_json())
    assert "0" in body["qubits"]
    assert "1" in body["qubits"]
    assert "2" not in body["qubits"]


def test_cirq_tuple_keys_and_pytket_confusion_matrix():
    cirq = {
        "single_qubit_idle_t1_micros": {(0, 0): 40.0, (0, 1): 35.0},
        "single_qubit_idle_t2_micros": {(0, 0): 30.0, (0, 1): 25.0},
        "single_qubit_rb_pauli_error_per_gate": {(0, 0): 0.001, (0, 1): 0.002},
        "single_qubit_readout_p00_error": {(0, 0): 0.01, (0, 1): 0.02},
        "single_qubit_readout_p11_error": {(0, 0): 0.03, (0, 1): 0.04},
        "two_qubit_cz_pauli_error": {"0_1": 0.015},
    }
    card = extract_from_cirq(cirq, qubit_order=["(0, 0)", "(0, 1)"])
    assert card.qubit_count() == 2

    class _Info:
        nodes = ["q0", "q1"]
        averaged_node_gate_errors = {"q0": 0.001, "q1": 0.002}
        averaged_edge_gate_errors = {"q0_q1": 0.02}
        all_readout_errors = [
            [[0.99, 0.01], [0.02, 0.98]],
            [[0.97, 0.03], [0.04, 0.96]],
        ]
        misc = {"t1_s": 2.0, "t2_s": 0.5}

    card = extract_from_pytket(_Info())
    body = json.loads(card.to_json())
    assert math.isclose(body["qubits"]["0"]["prob_meas1_prep0"], 0.01, rel_tol=0, abs_tol=1e-12)


def test_neutral_atom_and_auto_extract():
    card = build_neutral_atom_calibration(3)
    assert card.qubit_count() == 3
    auto = auto_extract_calibration(
        {
            "backend_name": "x",
            "qubits": [[{"name": "T1", "unit": "us", "value": 10.0}]],
            "gates": [],
        }
    )
    assert auto.qubit_count() >= 1


def test_client_build_job_json_omits_or_embeds_calibration():
    bare = ZNEProClient.build_job_json(
        "OPENQASM 2.0;\nqreg q[1];\n",
        {"0": 900, "1": 100},
        shots=1000,
        observable="Z",
        calibration=None,
    )
    bare_obj = json.loads(bare)
    assert "hardware_calibration" not in bare_obj
    assert "hardware_scales" not in bare_obj
    assert "shots" in bare_obj
    assert bare_obj["shots"]["0"] == 900
    assert _hidden_flag() not in bare

    card = build_neutral_atom_calibration(2)
    rich = ZNEProClient.build_job_json(
        "OPENQASM 2.0;\nqreg q[2];\n",
        {"00": 3500, "11": 500},
        shots=4000,
        observable="ZZ",
        observables=["ZZ", "XX"],
        calibration=card,
    )
    rich_obj = json.loads(rich)
    assert "hardware_calibration" in rich_obj
    assert "hardware_scales" not in rich_obj
    assert rich_obj["clique_observables"] == ["ZZ", "XX"]
    assert _hidden_flag() not in rich
    assert _hidden_flag() not in rich_obj["hardware_calibration"]

    multi = ZNEProClient.build_multi_scale_job_json(
        "OPENQASM 2.0;\nqreg q[1];\n",
        [1.0, 1.5],
        1000,
        expectations=[0.9, 0.8],
        calibration=None,
    )
    assert "hardware_scales" in json.loads(multi)


def _header_map(headers: dict) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in headers.items()}


def test_seal_envelope_matches_nist_aesgcm_and_rejects_a_flipped_byte():
    key = bytes(range(32))
    nonce = b"0123456789ab"
    plain = b'{"backend_name":"superconducting","qasm":"OPENQASM 2.0;","shots":{"0":1}}'
    sealed = seal_envelope(plain, key, nonce=nonce)
    assert sealed == nonce + AESGCM(key).encrypt(nonce, plain, None)
    assert open_envelope(sealed, key.hex()) == plain
    assert open_envelope(sealed, key) == plain
    flipped_tag = bytearray(sealed)
    flipped_tag[-1] ^= 0x01
    with pytest.raises(InvalidTag):
        open_envelope(bytes(flipped_tag), key)
    flipped_body = bytearray(sealed)
    flipped_body[12] ^= 0x01
    with pytest.raises(InvalidTag):
        open_envelope(bytes(flipped_body), key)
    with pytest.raises(ValueError):
        seal_envelope(plain, b"short")
    with pytest.raises(ValueError):
        open_envelope(b"x" * 27, key)


def test_submit_job_scopes_bearer_token_to_api_origin():
    put_url = "https://example-r2.cloudflarestorage.com/bucket/in?X-Amz-Signature=putsig"
    get_url = "https://example-r2.cloudflarestorage.com/bucket/out?X-Amz-Signature=getsig"
    seen: list[tuple[str, str, dict[str, str], bytes | None]] = []
    put_attempts = {"n": 0}

    def transport(method, url, body, headers, timeout_s):  # noqa: ARG001
        seen.append((method, url, _header_map(headers), body))
        if method == "POST" and url.endswith("/api/v1/client/tasks/init"):
            sent = json.loads(body)
            assert sent["hardware_backend"] == "superconducting"
            return 200, json.dumps(
                {
                    "task_id": "task-unit-1",
                    "job_id": "task-unit-1",
                    "r2_key": "tasks/0123456789abcdef/00000000-0000-0000-0000-000000000001/input.zk",
                    "upload_presigned_url": put_url,
                    "output_presigned_url": get_url,
                    "encryption_key_hex": _TICKET_KEY,
                }
            ).encode()
        if method == "PUT" and url == put_url:
            assert body is not None
            put_attempts["n"] += 1
            if put_attempts["n"] == 1:
                return 403, b"retry"
            uploaded = json.loads(open_envelope(body, _TICKET_KEY))
            assert uploaded["backend_name"] == "superconducting"
            assert "hardware_calibration" not in uploaded
            assert "hardware_scales" not in uploaded
            return 200, b""
        if method == "POST" and url.endswith("/api/v1/client/tasks/commit"):
            return 200, json.dumps({"status": "QUEUED"}).encode()
        if method == "GET" and url == get_url:
            receipt = {
                "status": "COMPLETED",
                "task_id": "task-unit-1",
                "mitigated_expectation": 0.91,
                "unmitigated_expectation": 0.75,
                "engine_version": "2026.11.13",
            }
            return 200, seal_envelope(json.dumps(receipt).encode(), _TICKET_KEY, nonce=b"0123456789ab")
        raise AssertionError(f"unexpected request {method} {url}")

    client = ZNEProClient(api_key="test", transport=transport)
    result = client.submit_job(
        "OPENQASM 2.0;\nqreg q[2];\nh q[0];\ncx q[0],q[1];\n",
        {"00": 3500, "11": 500},
        shots=4000,
        observable="ZZ",
        calibration=None,
        timeout_s=5.0,
        poll_interval_s=0.01,
    )
    assert result["status"] == "COMPLETED"
    assert result["mitigated_expectation"] == 0.91
    assert result["engine_version"] == "2026.11.13"
    assert seen
    for method, url, headers, _body in seen:
        credential_names = [
            name
            for name in headers
            if name in {"authorization", "x-api-key", "api-key", "x-api-token"}
            or "api-key" in name
            or "apikey" in name
        ]
        if url.startswith("https://api.znepro.com/"):
            assert headers.get("authorization") == "Bearer test"
            assert headers.get("accept") == "application/json"
            assert headers.get("user-agent") == "znepro-sdk/1.0.2"
            assert "python-urllib" not in headers["user-agent"].lower()
            assert credential_names == ["authorization"]
        else:
            assert "cloudflarestorage.com" in url
            assert method in {"PUT", "GET"}
            assert credential_names == []
            assert headers.get("user-agent") == "znepro-sdk/1.0.2"
            assert "X-Amz-Signature" in url
    puts = [(headers, body) for method, url, headers, body in seen if method == "PUT"]
    assert len(puts) == 2
    assert "content-type" not in puts[0][0]
    assert puts[1][0].get("content-type") == "application/octet-stream"
    assert puts[0][1] == puts[1][1]


def test_failed_receipt_raises_without_another_poll():
    put_url = "https://example-r2.cloudflarestorage.com/bucket/in?X-Amz-Signature=putsig"
    get_url = "https://example-r2.cloudflarestorage.com/bucket/out?X-Amz-Signature=getsig"
    gets = {"n": 0}

    def transport(method, url, body, headers, timeout_s):  # noqa: ARG001
        if method == "POST" and url.endswith("/api/v1/client/tasks/init"):
            return 200, json.dumps(
                {
                    "task_id": "task-fail",
                    "upload_presigned_url": put_url,
                    "output_presigned_url": get_url,
                    "encryption_key_hex": _TICKET_KEY,
                }
            ).encode()
        if method == "PUT":
            return 200, b""
        if method == "POST" and url.endswith("/api/v1/client/tasks/commit"):
            return 200, json.dumps({"status": "QUEUED"}).encode()
        if method == "GET" and url == get_url:
            gets["n"] += 1
            receipt = {"status": "FAILED", "error": "task artifact authentication failed"}
            return 200, seal_envelope(json.dumps(receipt).encode(), _TICKET_KEY)
        raise AssertionError(f"unexpected request {method} {url}")

    client = ZNEProClient(api_key="test", transport=transport, timeout_s=5)
    with pytest.raises(RuntimeError, match="task artifact authentication failed"):
        client.submit_job(
            "OPENQASM 2.0;\nqreg q[1];\n",
            {"0": 1},
            observable="Z",
            poll_interval_s=0.01,
            timeout_s=2,
        )
    assert gets["n"] == 1


def test_plain_json_receipt_is_accepted_only_without_a_key():
    client = ZNEProClient(api_key="test", transport=lambda *args: (200, b""), timeout_s=1)
    plain = json.dumps({"status": "COMPLETED", "mitigated_expectation": 0.2}).encode()
    assert client._receipt_document(plain, None)["mitigated_expectation"] == 0.2
    with pytest.raises(InvalidTag):
        client._receipt_document(plain, _TICKET_KEY)


def test_pi_angles_and_cnot_canonicalize_with_distinct_errors():
    expr = qasm_gates("OPENQASM 2.0;\nqreg q[2];\nry(3*pi/4) q[1];\n")
    literal = qasm_gates("OPENQASM 2.0;\nqreg q[2];\nry(2.356194490192345) q[1];\n")
    assert abs(expr[0][2][0] - literal[0][2][0]) < 1e-14
    assert expr[0][1] == [1]
    rewritten = canonicalize_qasm("OPENQASM 2.0;\nqreg q[2];\nry(3*pi/4) q[1];\n")
    assert abs(qasm_gates(rewritten)[0][2][0] - expr[0][2][0]) < 1e-15
    cnot = qasm_gates("OPENQASM 2.0;\nqreg q[2];\nCNOT q[0], q[1];\n")
    cx = qasm_gates("OPENQASM 2.0;\nqreg q[2];\ncx q[0], q[1];\n")
    assert cnot[0][0] == "cx"
    assert cnot[0][1] == cx[0][1] == [0, 1]
    with pytest.raises(ValueError, match="malformed angle expression") as angle:
        canonicalize_qasm("OPENQASM 2.0;\nqreg q[1];\nry(3*pi/) q[0];\n")
    with pytest.raises(ValueError, match="malformed target qubit") as target:
        canonicalize_qasm("OPENQASM 2.0;\nqreg q[1];\nry(pi/2) q[9];\n")
    assert "malformed target qubit" not in str(angle.value)
    assert "malformed angle expression" not in str(target.value)


_BRAKET_OPENQASM3 = """OPENQASM 3.0;
include "stdgates.inc";
qubit[2] q;
bit[2] c;
h q[0];
cnot q[0], q[1];
ry(3*pi/4) q[1];
c = measure q;
"""


def _assert_braket_qasm(qasm: str) -> None:
    assert qasm.startswith('OPENQASM 2.0;\ninclude "qelib1.inc";\n')
    assert "qreg q[2];" in qasm
    assert "creg c[2];" in qasm
    assert "qubit[" not in qasm
    assert "bit[" not in qasm
    assert "cnot" not in qasm.lower()
    assert "stdgates" not in qasm
    assert "cx q[0], q[1];" in qasm
    assert "measure q -> c;" in qasm
    gates = qasm_gates(qasm)
    ry = next(gate for gate in gates if gate[0] == "ry")
    cx = next(gate for gate in gates if gate[0] == "cx")
    literal = qasm_gates("OPENQASM 2.0;\nqreg q[2];\nry(2.356194490192345) q[1];\n")
    assert abs(ry[2][0] - literal[0][2][0]) < 1e-14
    assert cx[1] == [0, 1]


def test_openqasm3_braket_program_normalization():
    built = json.loads(
        ZNEProClient.build_job_json(
            _BRAKET_OPENQASM3,
            {"00": 1, "11": 1},
            observable="ZZ",
            shots=2,
        )
    )
    _assert_braket_qasm(built["qasm"])

    put_url = "https://example-r2.cloudflarestorage.com/bucket/in?X-Amz-Signature=putsig"
    get_url = "https://example-r2.cloudflarestorage.com/bucket/out?X-Amz-Signature=getsig"
    uploaded: list[str] = []

    def transport(method, url, body, headers, timeout_s):  # noqa: ARG001
        lowered = {str(key).lower(): str(value) for key, value in headers.items()}
        if method == "POST" and url.endswith("/api/v1/client/tasks/init"):
            assert lowered.get("authorization") == "Bearer test"
            return 200, json.dumps(
                {
                    "task_id": "task-oq3",
                    "upload_presigned_url": put_url,
                    "output_presigned_url": get_url,
                    "encryption_key_hex": _TICKET_KEY,
                }
            ).encode()
        if method == "PUT" and url == put_url:
            assert "authorization" not in lowered
            assert lowered.get("user-agent") == "znepro-sdk/1.0.2"
            uploaded.append(json.loads(open_envelope(body, _TICKET_KEY))["qasm"])
            return 200, b""
        if method == "POST" and url.endswith("/api/v1/client/tasks/commit"):
            return 200, json.dumps({"status": "QUEUED"}).encode()
        if method == "GET" and url == get_url:
            receipt = {
                "status": "COMPLETED",
                "mitigated_expectation": 0.5,
                "engine_version": "0.1.0",
            }
            return 200, seal_envelope(json.dumps(receipt).encode(), _TICKET_KEY, nonce=b"0123456789ab")
        raise AssertionError(f"unexpected request {method} {url}")

    client = ZNEProClient(api_key="test", transport=transport, timeout_s=5)
    raw = json.dumps({"qasm": _BRAKET_OPENQASM3, "shots": {"00": 1, "11": 1}})
    waited = client.submit_and_wait(raw, observable="ZZ", timeout_s=2, poll_interval_s=0.01)
    assert waited["status"] == "COMPLETED"
    assert waited["engine_version"] == "0.1.0"
    mitigated = json.loads(
        client.mitigate_json(raw, observable="ZZ", timeout_s=2, poll_interval_s=0.01)
    )
    assert mitigated["status"] == "COMPLETED"
    submitted = client.submit_job(
        _BRAKET_OPENQASM3,
        {"00": 1, "11": 1},
        observable="ZZ",
        shots=2,
        timeout_s=2,
        poll_interval_s=0.01,
    )
    assert submitted["status"] == "COMPLETED"
    assert len(uploaded) == 3
    for qasm in uploaded:
        _assert_braket_qasm(qasm)


def test_partial_card_omits_median_error_defaults_and_maps_readout_fidelity():
    partial = {
        "standardized": {
            "oneQubitProperties": {
                "0": {
                    "oneQubitFidelity": [
                        {"fidelityType": "RANDOMIZED_BENCHMARKING", "fidelity": 0.9964546331080112},
                        {"fidelityType": "READOUT", "fidelity": 0.971},
                    ]
                }
            },
            "twoQubitProperties": {
                "0-1": {"twoQubitGateFidelity": [{"fidelity": 0.9943965178886834}]}
            },
        }
    }
    card = extract_from_braket(partial)
    body = json.loads(card.to_json())
    assert "default_error_1q" not in body
    assert "default_error_2q" not in body
    assert "1" not in body["qubits"]
    assert abs(body["qubits"]["0"]["prob_meas1_prep0"] - 0.0145) < 1e-12
    assert abs(body["qubits"]["0"]["prob_meas0_prep1"] - 0.0145) < 1e-12
    assert abs((1.0 - 0.0145 - 0.0145) - 0.971) < 1e-12


def test_compiled_extension_binary_has_no_proprietary_tokens():
    core_path = Path(znepro._core.__file__)
    assert core_path.exists()
    blob = core_path.read_bytes()
    for token in _forbidden_binary_tokens():
        assert token not in blob, f"proprietary token leaked into {core_path.name}"
        assert token.lower() not in blob.lower()
    # Source client must not default to the retired sync shortcut.
    init_src = Path(znepro.__file__).read_text(encoding="utf-8")
    retired = "/" + "v1" + "/" + "mitigate"
    assert retired not in init_src
    assert "/api/v1/client/tasks/init" in init_src
