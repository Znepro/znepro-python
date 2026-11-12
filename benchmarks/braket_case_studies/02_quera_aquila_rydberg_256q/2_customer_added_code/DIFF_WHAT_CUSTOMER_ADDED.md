# What the customer adds

`1_original_braket_project/aquila_ahs_mis_program.py` still builds the 256-site register, the Rabi and detuning sweeps, and reads `raw_aquila_qpu_results.json`. Nothing in that folder is edited.

## Before

```python
program = analog_program()     # 16 x 16 sites at 6.7e-6 m, C6 = 5.42e-24
record = load_hardware_results()
# Z2 order = 0.760, 0.695, 0.635 at lambda = 1.0, 1.3, 1.6
# ideal = 0.960
```

## After

The wrapper imports that module. Locally it stretches every site by `lambda ** (1/6)`, which divides the van der Waals interaction by lambda. Those coordinates are not uploaded.

The uploaded object is a sign-masked scale series plus a small measurement circuit with permuted wires. `s_k = -1`, so the server sees `-0.760`, `-0.695`, and `-0.635` instead of the Aquila Z2 numbers, and no lattice spacing.

```python
SIGN_MASK = -1
stretched = rescaled_sites(aquila.atom_sites(), lam=1.6)   # local only
job = execute_blinded_job(
    qasm=proxy_qasm(),
    shots=correlator_shots(0.760, 1000, 8),
    observable="ZZ",
    scales=[{"lambda": 1.0, "expectation": 0.760},
            {"lambda": 1.3, "expectation": 0.695},
            {"lambda": 1.6, "expectation": 0.635}],
    sign_mask=SIGN_MASK,
    permutation=[4, 7, 1, 6, 0, 3, 5, 2],
    backend_name="neutral_atom",
    forbidden_text=("aquila", "quera", "rydberg", "6.7e-6", "5.42e-24"),
)
restored = job["sign_mask"] * job["server"]["mitigated_expectation"]
```

`blinded_inner_payload.json` therefore has the opposite sign from the Aquila JSON. `final_unblinded_result.json` applies `s_k` and is the physical Z2 estimate.
