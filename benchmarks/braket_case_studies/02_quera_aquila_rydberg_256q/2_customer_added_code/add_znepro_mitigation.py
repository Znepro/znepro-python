"""Customer wrapper. The original Aquila program is imported and not edited."""

from __future__ import annotations

import json
import sys
from pathlib import Path

CASE = Path(__file__).resolve().parents[1]
ORIGINAL = CASE / "1_original_braket_project"
SDK = CASE.parents[0] / "shared_sdk"
sys.path.insert(0, str(ORIGINAL))
sys.path.insert(0, str(SDK))

import aquila_ahs_mis_program as aquila
from znepro_braket_plugin import correlator_shots, execute_blinded_job

SIGN_MASK = -1
PERMUTATION = [4, 7, 1, 6, 0, 3, 5, 2]
PROXY_QUBITS = 8
SHOTS = 1000


def rescaled_sites(sites: list[list[float]], lam: float) -> list[list[float]]:
    """Stretch the register by lambda^(1/6) so the van der Waals term falls as 1/lambda.

    The coordinates stay in this process. They are not written into the R2 payload.
    """
    factor = lam ** (1.0 / 6.0)
    return [[x * factor, y * factor] for x, y in sites]


def proxy_qasm() -> str:
    """Small measurement circuit for the staggered pair. No atom coordinates."""
    lines = [
        "OPENQASM 2.0;",
        'include "qelib1.inc";',
        f"qreg q[{PROXY_QUBITS}];",
        "creg c[2];",
        "h q[0];",
        "cz q[0],q[1];",
        "rz(0.15) q[2];",
        "rx(0.22) q[3];",
        "measure q[0] -> c[0];",
        "measure q[1] -> c[1];",
    ]
    return "\n".join(lines) + "\n"


def main() -> dict:
    record = aquila.load_hardware_results()
    scales = [
        {"lambda": row["lambda"], "expectation": row["expectation"]}
        for row in record["aquila"]["noise_scales"]
    ]
    # Local rescaling only. Discarded after the assert that it actually moves the sites.
    sites = aquila.atom_sites()
    stretched = rescaled_sites(sites, scales[-1]["lambda"])
    if stretched[1][0] <= sites[1][0]:
        raise RuntimeError("lambda^(1/6) rescaling did not stretch the register")
    ideal = float(record["ideal_z2_order"])
    raw = float(scales[0]["expectation"])
    job = execute_blinded_job(
        qasm=proxy_qasm(),
        shots=correlator_shots(raw, SHOTS, PROXY_QUBITS),
        observable="ZZ",
        scales=scales,
        sign_mask=SIGN_MASK,
        permutation=PERMUTATION,
        upload_dir=CASE / "3_uploaded_to_r2",
        download_dir=CASE / "4_downloaded_from_r2",
        expectation_qubits=[0, 1],
        backend_name="neutral_atom",
        forbidden_text=("aquila", "quera", "rydberg", "rubidium", "arxiv", "6.7e-6", "5.42e-24"),
    )
    server = float(job["server"]["mitigated_expectation"])
    restored = float(job["unblinded"]["mitigated_expectation"])
    raw_error = abs(raw - ideal)
    mitigated_error = abs(restored - ideal)
    if mitigated_error >= raw_error:
        raise SystemExit(f"error did not fall: {mitigated_error} vs {raw_error}")
    body = {
        "quantity": "Z2 order",
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
        "local_rescaled_site_count": len(stretched),
    }
    path = CASE / "4_downloaded_from_r2" / "final_unblinded_result.json"
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return body


if __name__ == "__main__":
    main()
