"""Customer wrapper. The original LiH VQE files are imported and not edited."""

from __future__ import annotations

import json
import sys
from pathlib import Path

CASE = Path(__file__).resolve().parents[1]
ORIGINAL = CASE / "1_original_braket_project"
SDK = CASE.parents[0] / "shared_sdk"
sys.path.insert(0, str(ORIGINAL))
sys.path.insert(0, str(SDK))

import braket_vqe_lih_16A as lih
from znepro_braket_plugin import correlator_shots, execute_blinded_job

SIGN_MASK = -1
PERMUTATION = [2, 0, 3, 1]
SHOTS = 1000
# Classical identity term of the customer's Hamiltonian. It never enters the envelope.
HAMILTONIAN_IDENTITY_OFFSET = -4.15


def to_qasm2(program: str) -> str:
    width = lih.QUBITS
    gates: list[str] = []
    for raw in program.splitlines():
        code = raw.split("//", 1)[0].strip()
        if not code or code.startswith("#") or code in {"box {", "}"}:
            continue
        if code.startswith(("OPENQASM", "bit[", "qubit[", "c ")):
            continue
        while "$" in code:
            start = code.index("$")
            end = start + 1
            while end < len(code) and code[end].isdigit():
                end += 1
            code = code[:start] + f"q[{code[start + 1:end]}]" + code[end:]
        gates.append(code)
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
    record = lih.load_hardware_results()
    rows = record["braket_qpu"]["noise_scales"]
    c_I = HAMILTONIAN_IDENTITY_OFFSET
    raw_energies = [float(row["energy_ha"]) for row in rows]
    delta_energies = [energy - c_I for energy in raw_energies]
    scales = [
        {"lambda": float(row["lambda"]), "expectation": delta}
        for row, delta in zip(rows, delta_energies)
    ]
    ideal = float(record["exact_active_space_ha"])
    raw = raw_energies[0]
    # Shots are a parity record. The Hartree numbers travel in hardware_scales.
    job = execute_blinded_job(
        qasm=to_qasm2(lih.openqasm3()),
        shots=correlator_shots(-0.20, SHOTS, lih.QUBITS),
        observable="ZZ",
        scales=scales,
        sign_mask=SIGN_MASK,
        permutation=PERMUTATION,
        upload_dir=CASE / "3_uploaded_to_r2",
        download_dir=CASE / "4_downloaded_from_r2",
        expectation_qubits=[0, 1],
        observable_unit="hartree",
        backend_name="superconducting",
        forbidden_text=("lih", "pennylane", "sto-3g", "angstrom", "arxiv", "braket"),
    )
    server_delta = float(job["server"]["metrics"]["mitigated_expectation"])
    delta_mitigated = job["sign_mask"] * server_delta
    restored = c_I + delta_mitigated
    raw_error = abs(raw - ideal)
    mitigated_error = abs(restored - ideal)
    if mitigated_error >= raw_error:
        raise SystemExit(f"error did not fall: {mitigated_error} vs {raw_error}")
    body = {
        "quantity": "active-space energy (Ha)",
        "ideal": ideal,
        "raw_qpu_lambda_1": raw,
        "identity_offset": c_I,
        "sign_mask": job["sign_mask"],
        "server_mitigated_expectation": server_delta,
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
