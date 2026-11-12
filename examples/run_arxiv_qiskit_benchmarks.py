"""Public single-run payloads for the published Qiskit hardware profiles.

Each case is one histogram and one R2 ticket. Set ZNEPRO_API_KEY to submit.
Without a key the script only prints the payload shapes.
"""

from __future__ import annotations

import json
import os

from znepro import ZNEProClient

QASM_Z = "OPENQASM 2.0;\ninclude \"qelib1.inc\";\nqreg q[1];\nrz(1) q[0];\n"
QASM_ZZ = "OPENQASM 2.0;\ninclude \"qelib1.inc\";\nqreg q[2];\nh q[0];\ncx q[0],q[1];\n"
QASM_H2 = "OPENQASM 2.0;\ninclude \"qelib1.inc\";\nqreg q[2];\nry(0.7) q[0];\ncx q[0],q[1];\n"


def _shots(expectation: float, total: int = 4000) -> dict[str, int]:
    even = max(0, min(total, int(round((1.0 + expectation) * total / 2.0))))
    return {"0": even, "1": total - even}


CASES = (
    {"name": "weight1-z", "qasm": QASM_Z, "observable": "Z", "counts": _shots(0.50)},
    {"name": "long-range-zz", "qasm": QASM_ZZ, "observable": "ZZ", "counts": {"00": 1350, "11": 1350, "01": 650, "10": 650}},
    {"name": "native-z", "qasm": QASM_Z, "observable": "Z", "counts": _shots(0.90)},
    {"name": "h2-single", "qasm": QASM_H2, "observable": "Z", "counts": _shots(-0.715)},
)


def payload_for(case: dict) -> str:
    return ZNEProClient.build_job_json(
        case["qasm"],
        case["counts"],
        observable=case["observable"],
        shots=sum(case["counts"].values()),
        calibration=None,
    )


def main() -> None:
    client = ZNEProClient(api_key=os.environ.get("ZNEPRO_API_KEY"))
    for case in CASES:
        body = json.loads(payload_for(case))
        assert "hardware_calibration" not in body
        assert "hardware_scales" not in body
        if not os.environ.get("ZNEPRO_API_KEY"):
            print(case["name"], "payload_ok", sorted(body))
            continue
        result = client.submit_job(
            case["qasm"],
            case["counts"],
            observable=case["observable"],
            shots=sum(case["counts"].values()),
            calibration=None,
        )
        print(case["name"], result.get("mitigated_expectation"))


if __name__ == "__main__":
    main()
