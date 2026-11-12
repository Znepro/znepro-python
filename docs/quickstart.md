# Quickstart

One hardware execution becomes one R2 ticket. The client sends OpenQASM, the measured bitstring histogram, the target observable, and an optional calibration card. The service performs single-run mitigation. Callers do not fold the circuit and do not submit a multi-scale sweep for a production job.

The default API host is `https://api.znepro.com`.

## Python

```bash
pip install znepro
```

```python
from znepro import ZNEProClient

client = ZNEProClient(api_key="your-api-key")
result = client.submit_job(
    qasm="OPENQASM 2.0;\ninclude \"qelib1.inc\";\nqreg q[1];\nh q[0];\n",
    counts={"0": 2100, "1": 1900},
    shots=4000,
    observable="Z",
    calibration=None,
)
print(result["mitigated_expectation"])
```

`submit_job` runs the ticket lifecycle:

1. `POST /api/v1/client/tasks/init`
2. Seal the job JSON with the one-time key and `PUT` it to the presigned URL
3. `POST /api/v1/client/tasks/commit`
4. Poll the result object, or `GET /v1/tasks/{task_id}`

Leave the API key in the environment (`ZNEPRO_API_KEY`). Do not commit it.

## Rust

```rust
use std::collections::BTreeMap;
use znepro_sdk::{QubitLayout, ZneproJobRequest, PATH_CLIENT_TASK_INIT};

fn main() {
    let mut counts = BTreeMap::new();
    counts.insert("0".into(), 2100);
    counts.insert("1".into(), 1900);
    let job = ZneproJobRequest::single(
        "OPENQASM 2.0;\nqreg q[1];\nh q[0];\n",
        counts,
        None,
    );
    assert!(job.to_json_value().get("hardware_calibration").is_none());
    assert!(job.to_json_value().get("hardware_scales").is_none());
    assert_eq!(PATH_CLIENT_TASK_INIT, "/api/v1/client/tasks/init");
    let _ = QubitLayout::LogicalToPhysical(vec![0]);
}
```

## Calibrated job

Pass a `HardwareCalibration` from one of the five adapters. The JSON field `hardware_calibration` is present only when a card is attached. The zero-telemetry payload omits that field entirely.

See [hardware-adapters.md](hardware-adapters.md) and [wire-schema-and-receipts.md](wire-schema-and-receipts.md).
