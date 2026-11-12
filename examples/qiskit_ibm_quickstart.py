"""Extract an IBM BackendV2 calibration and submit one R2 ticket."""

from __future__ import annotations

import os

from znepro import ZNEProClient, extract_from_qiskit


def main() -> None:
    from qiskit_ibm_runtime import QiskitRuntimeService

    service = QiskitRuntimeService()
    backend = service.backend(os.environ.get("QISKIT_BACKEND", "ibm_fez"))
    # Pass the transpiled circuit, or an explicit physical index list, as layout.
    calibration = extract_from_qiskit(backend, layout=None)
    client = ZNEProClient(api_key=os.environ["ZNEPRO_API_KEY"])
    result = client.submit_job(
        qasm="OPENQASM 2.0;\ninclude \"qelib1.inc\";\nqreg q[2];\nh q[0];\ncx q[0],q[1];\n",
        counts={"00": 3100, "01": 400, "10": 350, "11": 150},
        shots=4000,
        observable="ZZ",
        calibration=calibration,
    )
    print(result["mitigated_expectation"])


if __name__ == "__main__":
    main()
