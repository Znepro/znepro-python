# What the customer adds

The files in `1_original_braket_project/` stay as the user already had them: an OpenQASM 3.0 program with `#pragma braket verbatim`, plus the saved Rigetti Ankaa and IonQ Aria-1 records.

## Before

The user runs the verbatim box on Braket and stops at the device record.

```python
program = openqasm3()          # $ wires, pragma braket verbatim, box { ... }
record = load_hardware_results()
# Ankaa <Z_u Z_v> = -0.340, -0.255, -0.191
# Aria-1 <Z_u Z_v> = -0.510
# ideal = -0.612
```

## After

`add_znepro_mitigation.py` imports that module. It does not edit it. The added steps are:

1. Rewrite `$n` and the verbatim box into OpenQASM 2 so the worker can execute the same gates.
2. Choose a local sign `s_k = -1` and a local qubit permutation. Neither is placed in the uploaded JSON as a labeled secret.
3. Send the Ankaa three-scale series. Aria-1 stays in the original JSON as the single-scale device record.
4. Seal, PUT to Cloudflare R2, commit, GET the receipt, and multiply the server number by `s_k`.

```python
SIGN_MASK = -1
PERMUTATION = [3, 0, 5, 1, 4, 2]
job = execute_blinded_job(
    qasm=to_qasm2(qaoa.openqasm3()),
    shots=correlator_shots(raw, 1000, qaoa.QUBITS),
    observable="ZZ",
    scales=ankaa_scales,
    sign_mask=SIGN_MASK,
    permutation=PERMUTATION,
    upload_dir=CASE / "3_uploaded_to_r2",
    download_dir=CASE / "4_downloaded_from_r2",
    expectation_qubits=[0, 1],
    forbidden_text=("ankaa", "aria", "rigetti", "ionq", "lanl", "maxcut", "arxiv", "braket"),
)
restored = job["sign_mask"] * job["server"]["mitigated_expectation"]
```

Because `s_k = -1`, `3_uploaded_to_r2/blinded_inner_payload.json` carries positive correlators (`+0.340`, `+0.255`, `+0.191`) and relabeled `q[i]` wires. `4_downloaded_from_r2/server_blinded_output.json` is still on that inverted sign. `final_unblinded_result.json` multiplies it back.
