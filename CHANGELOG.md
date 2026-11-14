# Changelog

## 1.0.2

- AWS Braket OpenQASM 3 programs (`OPENQASM 3.0`, `qubit[N]` / `bit[N]`, `c = measure q`, `cnot`, `ry(3*pi/4)`) are rewritten to OpenQASM 2 before upload.
- `build_job_json`, `submit_job`, `submit_and_wait`, and `mitigate_json` all run that rewrite, including a raw payload that never passed through `build_job_json`.

## 1.0.1

- Partial calibration cards omit median `default_error_1q` and `default_error_2q` instead of applying them to unmeasured qubits and edges.
- A scalar readout fidelity `F` maps to `prob_meas1_prep0 = prob_meas0_prep1 = (1-F)/2`.
- Outbound OpenQASM rewrites `cnot` to `cx` and evaluates compound `pi` angles before the R2 upload.
- Decrypted receipts keep `engine_version` when the service sends it.
