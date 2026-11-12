"""QAOA MaxCut circuit in the form a Braket user already stores.

OpenQASM 3.0 with a ``#pragma braket verbatim`` box. The graph is the 6-node
3-regular complete bipartite graph K(3,3). Edges such as (0, 3) are not
neighbors on a line. Ideal mean edge correlator and the device records live
in ``raw_braket_qpu_results.json``. This file does not call ZNEPro.
"""

from __future__ import annotations

import json
from pathlib import Path

QUBITS = 6
IDEAL_MEAN_EDGE_CORRELATOR = -0.612
RESULTS_PATH = Path(__file__).with_name("raw_braket_qpu_results.json")

# p = 1. Mixer and cost angles are a fixed point of that ansatz, not a claim
# that these are the published optima. The saved QPU JSON is the hardware record.
GAMMA = 0.40
BETA = 0.85
EDGES = (
    (0, 3), (0, 4), (0, 5),
    (1, 3), (1, 4), (1, 5),
    (2, 3), (2, 4), (2, 5),
)


def openqasm3() -> str:
    """Circuit a user would pass to ``AwsDevice.run`` as an OpenQASM 3 program."""
    gates = [f"  rx({BETA:.2f}) ${qubit};" for qubit in range(QUBITS)]
    gates += [f"  rz(-{GAMMA:.2f}) ${qubit};" for qubit in range(QUBITS)]
    gates += [f"  cz ${left}, ${right};" for left, right in EDGES]
    gates += [f"  rx({BETA + 0.30:.2f}) ${qubit};" for qubit in range(QUBITS)]
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


def submit_to_braket(device_arn: str) -> dict:
    """Placeholder for the user's existing Braket submission.

    The case study uses the saved QPU JSON. A live Braket call needs the
    amazon-braket-sdk and AWS credentials, which this comparison does not.
    """
    raise RuntimeError(
        f"This baseline loads raw_braket_qpu_results.json instead of submitting to {device_arn}."
    )
