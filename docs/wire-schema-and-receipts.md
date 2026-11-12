# Wire schema and receipts

## Job object

A primary job is one histogram:

```json
{
  "qasm": "OPENQASM 2.0;\nqreg q[1];\nh q[0];\n",
  "shots": {"0": 2100, "1": 1900},
  "backend_name": "superconducting"
}
```

`hardware_scales` is absent on this path. An optional offline helper can still attach pre-measured scale rows for benchmark harnesses. Production applications use the histogram form.

## Calibration card

Present only on the calibrated arm. The zero-telemetry arm omits the object.

| Field | Unit | Range |
|---|---|---|
| `t1_us`, `t2_us` | microseconds | strictly positive |
| `gate_time_1q_ns`, `gate_time_2q_ns` | nanoseconds | strictly positive |
| `error_1q`, `error_2q` | gate infidelity | `[0, 0.999999]` |
| `prob_meas1_prep0` | P(meas 1 given prep 0) | `[0, 0.5]` |
| `prob_meas0_prep1` | P(meas 0 given prep 1) | `[0, 0.5]` |

```json
{
  "default_error_1q": 0.001,
  "default_error_2q": 0.01,
  "default_gate_time_1q_ns": 30.0,
  "default_gate_time_2q_ns": 300.0,
  "qubits": {
    "0": {
      "t1_us": 60.0,
      "t2_us": 45.0,
      "error_1q": 0.001,
      "prob_meas1_prep0": 0.008,
      "prob_meas0_prep1": 0.04
    }
  },
  "edges": [{"q0": 0, "q1": 1, "error_2q": 0.01, "gate_time_2q_ns": 300.0}]
}
```

Qubit keys are the logical OpenQASM indices after layout remap.

## Ticket routes

| Step | Method | Path |
|---|---|---|
| Mint ticket | POST | `/api/v1/client/tasks/init` |
| Upload job JSON | PUT | presigned URL from init |
| Queue | POST | `/api/v1/client/tasks/commit` |
| Status | GET | `/v1/tasks/{task_id}` |

The init body carries `target_observable` and an optional `hardware_backend`. The uploaded object is the job JSON above. Presigned query strings are credentials and must not be stored in a repository. The API bearer is sent only to the API origin, never to the presigned storage host.

## Public receipt

A completed receipt exposes:

- `status`, `job_id`, `task_id`
- `backend_name`, `target_observable` when set
- `total_shots`, `execution_time_ms`
- `metrics.mitigated_expectation`
- `metrics.unmitigated_expectation`
- `metrics.mitigation_factor`, `metrics.mitigation_method`

When the service applied a calibration card it also attests that use:

- `server_calibration_used` is true on the calibrated arm and false on the zero-telemetry arm
- `server_calibration_sha256` is the canonical hash of the card that was applied
- `calibration_applied` and `calibration_sha256` repeat that attestation under the client-facing names

Those fields are the confirmation that the card was used. A client must not invent them from the request it sent. If the receipt omits them, a comparison that depends on calibration remains provisional. Any further receipt keys are retained on the status document.

`server_version` and `clipping_policy`, when present, must stay constant across a paired run. An optional `unclipped_estimate` is the value before a physical-range projection, when the service publishes one.
