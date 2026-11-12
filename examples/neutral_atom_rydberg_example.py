"""Build a neutral-atom calibration card and one single-run payload."""

from __future__ import annotations

import json
import os

from znepro import ZNEProClient, build_neutral_atom_calibration


def main() -> None:
    card = build_neutral_atom_calibration(
        num_qubits=8,
        cz_fidelity=0.995,
        single_qubit_fidelity=0.9992,
        t1_s=4.0,
        t2_ms=15.0,
        readout_error=0.008,
        atom_loss_prob=0.004,
    )
    payload = json.loads(
        ZNEProClient.build_job_json(
            qasm="OPENQASM 2.0;\nqreg q[8];\nh q[0];\n",
            counts={"00000000": 4000},
            shots=4000,
            observable="Z",
            calibration=card,
        )
    )
    assert "hardware_calibration" in payload
    assert "hardware_scales" not in payload
    print(card.qubit_count(), card.edge_count())
    if os.environ.get("ZNEPRO_API_KEY"):
        client = ZNEProClient(api_key=os.environ["ZNEPRO_API_KEY"])
        result = client.submit_and_wait(json.dumps(payload), observable="Z")
        print(result["mitigated_expectation"])


if __name__ == "__main__":
    main()
