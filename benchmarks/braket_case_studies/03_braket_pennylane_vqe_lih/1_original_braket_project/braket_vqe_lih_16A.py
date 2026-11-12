"""Four-qubit LiH VQE circuit in the form a Braket user already stores.

Bond length 1.6 angstrom, STO-3G active space, parity mapping onto four
qubits. The ansatz is a depth-2 hardware-efficient circuit. The exact
active-space energy and the noisy device energies live in
``raw_braket_vqe_results.json``. This file does not call ZNEPro.
"""

from __future__ import annotations

import json
from pathlib import Path

QUBITS = 4
BOND_ANGSTROM = 1.6
EXACT_ACTIVE_SPACE_HA = -8.01642
RESULTS_PATH = Path(__file__).with_name("raw_braket_vqe_results.json")

# One fixed parameter point of the hardware-efficient ansatz.
THETA = (
    (0.21, -0.44, 0.18, 0.07),
    (-0.33, 0.12, 0.27, -0.09),
    (0.48, 0.05, -0.16, 0.11),
    (-0.19, 0.36, 0.08, -0.22),
)


def openqasm3() -> str:
    gates: list[str] = []
    for layer in range(2):
        for qubit, row in enumerate(THETA):
            gates.append(f"  ry({row[layer]:.2f}) ${qubit};")
            gates.append(f"  rz({row[layer + 2]:.2f}) ${qubit};")
        gates.append("  cx $0, $1;")
        gates.append("  cx $1, $2;")
        gates.append("  cx $2, $3;")
    body = "\n".join(gates)
    return (
        "OPENQASM 3.0;\n"
        f"bit[{QUBITS}] c;\n"
        f"qubit[{QUBITS}] q;\n"
        "#pragma braket verbatim\n"
        "box {\n"
        f"{body}\n"
        "}\n"
        "c = measure q;\n"
    )


def load_hardware_results() -> dict:
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
