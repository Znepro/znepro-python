"""Extract AWS Braket device telemetry and submit one R2 ticket.

Works with standardized gate-model properties and with Rigetti, IonQ, or IQM
provider payloads accepted by ``extract_from_braket``.
"""

from __future__ import annotations

import os

from znepro import ZNEProClient, extract_from_braket


def main() -> None:
    from braket.aws import AwsDevice

    device = AwsDevice(os.environ.get("BRAKET_DEVICE_ARN", "arn:aws:braket:::device/qpu/ionq/Aria-1"))
    calibration = extract_from_braket(device, layout=[0, 1])
    client = ZNEProClient(api_key=os.environ["ZNEPRO_API_KEY"])
    result = client.submit_job(
        qasm="OPENQASM 2.0;\ninclude \"qelib1.inc\";\nqreg q[2];\nh q[0];\ncx q[0],q[1];\n",
        counts={"00": 2800, "11": 1200},
        shots=4000,
        observable="ZZ",
        calibration=calibration,
    )
    print(result["mitigated_expectation"], calibration.qubit_count())


if __name__ == "__main__":
    main()
