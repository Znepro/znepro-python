"""Customer wrapper. The original Braket files are imported and not edited."""

from __future__ import annotations

import json
import sys
from pathlib import Path

CASE = Path(__file__).resolve().parents[1]
ORIGINAL = CASE / "1_original_braket_project"
SDK = CASE.parents[0] / "shared_sdk"
sys.path.insert(0, str(ORIGINAL))
sys.path.insert(0, str(SDK))

import braket_qaoa_maxcut as qaoa
from znepro_braket_plugin import correlator_shots, execute_blinded_job

SIGN_MASK = -1
PERMUTATION = [3, 0, 5, 1, 4, 2]
SHOTS = 1000


def to_qasm2(program: str) -> str:
    """Drop Braket pragmas and rewrite ``$n`` wires into OpenQASM 2."""
    width = qaoa.QUBITS
    gates: list[str] = []
    for raw in program.splitlines():
        code = raw.split("//", 1)[0].strip()
        if not code or code.startswith("#") or code in {"box {", "}"}:
            continue
        if code.startswith(("OPENQASM", "bit[", "qubit[", "c ")):
            continue
        code = code.replace("$", "qtemp")
        # qtemp0 -> q[0]
        out = []
        cursor = 0
        token = "qtemp"
        while True:
            found = code.find(token, cursor)
            if found < 0:
                out.append(code[cursor:])
                break
            out.append(code[cursor:found])
            end = found + len(token)
            digits = []
            while end < len(code) and code[end].isdigit():
                digits.append(code[end])
                end += 1
            out.append(f"q[{''.join(digits)}]")
            cursor = end
        gates.append("".join(out))
    lines = [
        "OPENQASM 2.0;",
        'include "qelib1.inc";',
        f"qreg q[{width}];",
        "creg c[2];",
        *gates,
        "measure q[0] -> c[0];",
        "measure q[1] -> c[1];",
    ]
    return "\n".join(lines) + "\n"


def main() -> dict:
    record = qaoa.load_hardware_results()
    scales = [
        {"lambda": row["lambda"], "expectation": row["expectation"]}
        for row in record["rigetti_ankaa"]["noise_scales"]
    ]
    ideal = float(record["ideal_mean_edge_correlator"])
    raw = float(scales[0]["expectation"])
    job = execute_blinded_job(
        qasm=to_qasm2(qaoa.openqasm3()),
        shots=correlator_shots(raw, SHOTS, qaoa.QUBITS),
        observable="ZZ",
        scales=scales,
        sign_mask=SIGN_MASK,
        permutation=PERMUTATION,
        upload_dir=CASE / "3_uploaded_to_r2",
        download_dir=CASE / "4_downloaded_from_r2",
        expectation_qubits=[0, 1],
        backend_name="superconducting",
        forbidden_text=("ankaa", "aria", "rigetti", "ionq", "lanl", "maxcut", "arxiv", "braket"),
    )
    return _write_result(job, ideal, raw, "mean edge correlator")


def _write_result(job: dict, ideal: float, raw: float, quantity: str) -> dict:
    server = float(job["server"]["mitigated_expectation"])
    restored = float(job["unblinded"]["mitigated_expectation"])
    raw_error = abs(raw - ideal)
    mitigated_error = abs(restored - ideal)
    if mitigated_error >= raw_error:
        raise SystemExit(f"error did not fall: {mitigated_error} vs {raw_error}")
    body = {
        "quantity": quantity,
        "ideal": ideal,
        "raw_qpu_lambda_1": raw,
        "sign_mask": job["sign_mask"],
        "server_mitigated_expectation": server,
        "unblinded_mitigated_expectation": restored,
        "raw_absolute_error": raw_error,
        "mitigated_absolute_error": mitigated_error,
        "error_reduction_factor": raw_error / mitigated_error,
        "task_id": job["task_id"],
        "wire_observable": job["wire_observable"],
        "server_visible_scale_0": job["server_visible_expectation"],
    }
    path = CASE / "4_downloaded_from_r2" / "final_unblinded_result.json"
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return body


if __name__ == "__main__":
    main()
