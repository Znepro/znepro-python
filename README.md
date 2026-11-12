# ZNEPro SDK (`znepro` / `znepro-sdk`)

Official open-source client and multi-platform hardware calibration extractor for the **ZNEPro** Quantum Error Mitigation (QEM) service.

Built around a zero-internal-dependency Rust core with native Python `abi3` bindings (`Python >= 3.10`), this SDK normalizes raw device telemetry—coherence times ($T_1, T_2$), native 1Q/2Q gate infidelities, gate durations, and asymmetric readout assignment errors—into deterministic JSON payloads for the live **R2 ticket** API at `https://api.znepro.com`.

**Primary contract:** one hardware execution (OpenQASM + bitstring histogram + target observable, optional calibration) → one R2 ticket. Callers do **not** fold circuits or submit multi-scale sweeps; the service performs single-run mitigation server-side. Pre-measured multi-scale sample arrays remain available only as an optional offline / benchmark helper.

---

## Key Capabilities

- **R2 Ticket Workflow:** `POST /api/v1/client/tasks/init` → PUT the job JSON to the returned presigned URL → `POST /api/v1/client/tasks/commit` → poll the result object (or `GET /v1/tasks/{task_id}`). The API bearer is not attached to the presigned storage request.
- **Single-Run Primary Jobs:** Build one-shot bitstring histograms (`shots`) with optional `hardware_calibration`. Multi-scale `hardware_scales` payloads are optional for offline harnesses only.
- **Five Built-in Quantum Hardware Adapters:** IBM Quantum (`Qiskit`), AWS Braket (Rigetti / IonQ / IQM), Google Quantum AI (`Cirq`), Quantinuum & TKET (`pytket`), and Neutral-Atom QPUs (QuEra / Pasqal / Atom Computing).
- **Automatic Transpile Layout Remapping:** Projects full-chip calibration tables onto the physical-to-logical qubit subset used by a transpiled OpenQASM circuit.
- **Strict Numerical Sanitization:** Scrubs `NaN`, `Inf`, and non-physical values inside Rust, imputes missing device defaults from calibrated medians, and guarantees deterministic `BTreeMap` JSON serialization.
- **Zero Runtime Bloat:** Neither the Python wheel nor the Rust crate requires vendor quantum SDKs unless you pass live vendor objects at runtime.

---

## Installation

### Python (`pip`)

```bash
pip install znepro
```

Optional extras:

```bash
pip install "znepro[qiskit]"
pip install "znepro[braket]"
pip install "znepro[cirq]"
pip install "znepro[pytket]"
```

### Rust

Add the crate path (or the published package) to your `Cargo.toml`. Dependencies are only `serde`, `serde_json`, and `thiserror`.

---

## Live R2 Ticket Routes

| Step | Method | Path |
|---|---|---|
| Mint ticket | `POST` | `/api/v1/client/tasks/init` |
| Upload job JSON | `PUT` | *presigned URL from init* |
| Queue task | `POST` | `/api/v1/client/tasks/commit` |
| Status / result | `GET` | `/v1/tasks/{task_id}` |
| Sealed receipt | `GET` | *presigned `output_presigned_url`* |

`ZNEProClient.submit_job` / `mitigate` / `submit_and_wait` run this flow end-to-end. Do **not** call retired sync shortcuts; the client never posts to them.

---

## Python Quickstart

### 1. Uncalibrated single hardware run (primary)

```python
from znepro import ZNEProClient

client = ZNEProClient(api_key="znepro_live_...")  # base_url defaults to https://api.znepro.com

# One device execution → one ticket. No circuit folding on the client.
result = client.submit_job(
    qasm="OPENQASM 2.0;\ninclude \"qelib1.inc\";\nqreg q[1];\nh q[0];\n",
    counts={"0": 2100, "1": 1900},
    shots=4000,
    observable="Z",
    calibration=None,  # omits hardware_calibration from JSON
)
print(result["mitigated_expectation"])
```

Equivalent payload builder:

```python
payload = client.build_job_json(
    qasm=qasm_str,
    counts={"0": 2100, "1": 1900},
    shots=4000,
    observable="Z",
    calibration=None,
)
result = client.submit_and_wait(payload, observable="Z")
```

### 2. Calibrated single-histogram mitigation

```python
from znepro import ZNEProClient, extract_from_qiskit

calibration = extract_from_qiskit(backend, layout=isa_circuit)
client = ZNEProClient(api_key="znepro_live_...")

result = client.submit_job(
    qasm=qasm_str,
    counts={"00": 3100, "01": 400, "10": 350, "11": 150},
    shots=4000,
    observable="ZZ",
    observables=["ZZ", "XX"],  # optional joint clique labels
    calibration=calibration,
)
print(result["mitigated_expectation"], result["unmitigated_expectation"])
```

### 3. Optional offline multi-scale harness (not required)

```python
# Only for pre-measured benchmark arrays. Production apps use submit_job.
payload = client.build_multi_scale_job_json(
    qasm=qasm_str,
    noise_scales=[1.0, 1.5, 2.0],
    expectations=[0.91, 0.84, 0.77],
    shots=4000,
    calibration=None,
)
result = client.submit_and_wait(payload, observable="Z")
```

---

## Hardware Adapter Examples (Python)

```python
import znepro

ibm_cal = znepro.extract_from_qiskit(backend, layout=[10, 11, 12])
braket_cal = znepro.extract_from_braket(aws_device, layout=[0, 1, 2])
cirq_cal = znepro.extract_from_cirq(cirq_metrics_dict, qubit_order=["(0, 0)", "(0, 1)"])
tket_cal = znepro.extract_from_pytket(quantinuum_backend.backend_info)
rydberg_cal = znepro.build_neutral_atom_calibration(
    num_qubits=8,
    cz_fidelity=0.995,
    single_qubit_fidelity=0.9992,
    t1_s=4.0,
    t2_ms=15.0,
    readout_error=0.008,
    atom_loss_prob=0.004,
)
print(rydberg_cal.to_json(pretty=True))
```

Normalized `hardware_calibration` JSON (server-side flags are never emitted):

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

---

## Rust Quickstart

```rust
use std::collections::BTreeMap;
use znepro_sdk::{
    extract_from_braket_json, ClientError, QubitLayout, ZneproJobRequest, PATH_CLIENT_TASK_INIT,
};

fn main() -> Result<(), ClientError> {
    let layout = QubitLayout::LogicalToPhysical(vec![10, 11]);
    let calibration = extract_from_braket_json(&braket_dump, Some(&layout))?;

    // Primary: one hardware histogram → one sealed job object.
    let mut counts = BTreeMap::new();
    counts.insert("00".into(), 3500);
    counts.insert("11".into(), 500);
    let job = ZneproJobRequest::single_with_observables(
        "OPENQASM 2.0;\nqreg q[2];\nh q[0];\ncx q[0],q[1];\n",
        counts,
        Some(vec!["ZZ".into()]),
        Some(calibration),
    );
    assert!(job.to_json_value().get("hardware_scales").is_none());
    println!("{}", serde_json::to_string_pretty(&job.to_json_value()).unwrap());

    // Uncalibrated single-run omits hardware_calibration entirely.
    let mut bare = BTreeMap::new();
    bare.insert("0".into(), 4000);
    let uncal = ZneproJobRequest::single("OPENQASM 2.0;\nqreg q[1];\nh q[0];\n", bare, None);
    assert!(uncal.to_json_value().get("hardware_calibration").is_none());
    assert_eq!(PATH_CLIENT_TASK_INIT, "/api/v1/client/tasks/init");
    Ok(())
}
```

Optional offline multi-scale helper (benchmarks only):

```rust
let multi = ZneproJobRequest::multi_scale(
    "OPENQASM 2.0;\nqreg q[1];\n",
    &[1.0, 1.5, 2.0],
    &[0.875, 0.790, 0.612],
    4000,
    None,
    None,
);
```

---

## Documentation

- [Quickstart](docs/quickstart.md) — one hardware run, one R2 ticket, Python and Rust
- [Hardware adapters](docs/hardware-adapters.md) — IBM Qiskit, AWS Braket, Cirq, TKET, neutral atom
- [Wire schema and receipts](docs/wire-schema-and-receipts.md) — `hardware_calibration` and receipt attestation
- [Benchmarks](docs/benchmarks.md) — public case studies

## Repository layout

| Path | Contents |
|---|---|
| `src/` | Rust schema, layout remapper, R2 client types, five adapters, PyO3 |
| `python/znepro/` | `ZNEProClient` and the vendor-object bridge |
| `examples/` | Customer quickstarts and the public Qiskit benchmark script |
| `benchmarks/braket_case_studies/` | Recorded Braket studies and public receipts |
| `tests/` | Adapter security tests, Python bindings, customer ticket tests, leak scan |

## License

Apache-2.0. Copyright 2026 QRefinery Labs LLC / ZNEPro. See `LICENSE`.
