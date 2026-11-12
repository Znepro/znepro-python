# Braket case studies on ZNEPro

Three published Braket workloads. Each folder keeps the original project, the customer wrapper, the exact bytes PUT to Cloudflare R2, and the exact bytes GET back.

Presigned query strings are not stored. `r2_upload_metadata.json` keeps the host, object URL path, byte count, and SHA-256.

| Case | Task | R2 key | input.zk | output.zk | Raw QPU | Server (blinded) | Unblinded | Ideal | Error reduction |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 01_lanl_qaoa_ankaa_aria | `task-08d910e9-020b-496d-9cc6-f883378400a5` | `tasks/8d93d5320106d58f/08d910e9-020b-496d-9cc6-f883378400a5/input.zk` | 929 B | 489 B | -0.340000 | 0.514081 | -0.514081 | -0.612000 | 2.78x |
| 02_quera_aquila_rydberg_256q | `task-c0a2ec2b-58e1-469e-85fc-316b0f874626` | `tasks/8d93d5320106d58f/c0a2ec2b-58e1-469e-85fc-316b0f874626/input.zk` | 553 B | 488 B | 0.760000 | -0.937873 | 0.937873 | 0.960000 | 9.04x |
| 03_braket_pennylane_vqe_lih | `task-70cd12e4-81c0-45c8-a1d7-db616e7cf6ad` | `tasks/8d93d5320106d58f/70cd12e4-81c0-45c8-a1d7-db616e7cf6ad/input.zk` | 920 B | 485 B | -6.820000 | 3.125283 | -7.275283 | -8.016420 | 1.61x |

## Layout

- `shared_sdk/znepro_braket_plugin.py` — init, blind, R2 PUT of the job JSON, commit, R2 GET, unblind.
- `01_lanl_qaoa_ankaa_aria` — OpenQASM 3 verbatim QAOA, Ankaa scales `-0.340 / -0.255 / -0.191`, Aria-1 raw `-0.510`, ideal `-0.612`. The R2 job uses the Ankaa series. `s_k = -1`.
- `02_quera_aquila_rydberg_256q` — 256-site Aquila program, Z2 order `0.760 / 0.695 / 0.635`, ideal `0.960`. Site stretch `lambda^(1/6)` stays local. `s_k = -1`.
- `03_braket_pennylane_vqe_lih` — 4-qubit LiH at 1.6 A, energies `-6.820 / -6.295 / -5.810` Ha, target `-8.01642` Ha. The classical identity offset `-4.15` Ha stays on the client; only the remainder is masked and uploaded. `s_k = -1`.

In every blinded payload the lambda = 1 sample has the opposite sign from the original QPU file, and the OpenQASM wire labels are the permuted ones.

## Reproduce

```bash
python3 -m unittest braket_case_studies.test_braket_case_studies
```
