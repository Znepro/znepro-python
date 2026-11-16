# Public benchmarks

These figures are recorded service results for published circuits. They are not a claim about every device or every noise model. Re-run the examples with your own API key; do not commit that key.

## Qiskit hardware profiles

`examples/run_arxiv_qiskit_benchmarks.py` builds one single-run ticket per case through `znepro.ZNEProClient`.

| Case | Published reference | Raw expectation | Mitigated expectation |
|---|---|---:|---:|
| Weight-1 Z, theta = 1 | ideal cos(1) = 0.540302 | 0.500000 | 0.547087 |
| Long-range ZZ on a 50-qubit register | ideal 1 | 0.350000 | 0.371643 |
| Native X / Y / Z at one scale | raw 0.90 | 0.900000 | 0.932058 / 0.936730 / 0.927409 |
| H2 STO-3G, single run | reference -1.13618945 Ha | -0.715000 | -0.856010 |

The multi-scale H2 profile in the same script is an offline helper. Its recorded mitigated value is -1.110451 Ha. That does not recover the reference energy.

## Braket case studies

Recorded uploads and receipts live in `benchmarks/braket_case_studies/`. Presigned query strings are not stored.

| Case | Raw QPU | Unblinded result | Ideal | Error reduction |
|---|---:|---:|---:|---:|
| LANL QAOA on Ankaa | -0.340 | -0.514081 | -0.612 | 2.78x |
| QuEra Aquila, 256 sites | 0.760 | 0.937873 | 0.960 | 9.04x |
| PennyLane LiH, 1.6 A | -6.820 | -7.275283 | -8.016420 | 1.61x |

The LiH identity offset -4.15 Ha stays on the client. Only the shifted remainder is uploaded. Customer sign masks used by those recorded jobs stay in the case-study code and are not a server secret.

Offline checks of the original device numbers:

```bash
python -m unittest benchmarks.braket_case_studies.test_braket_case_studies
```

A fresh live pass requires `ZNEPRO_RUN_LIVE=1` and `ZNEPRO_API_KEY`.
