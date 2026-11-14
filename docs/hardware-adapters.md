# Hardware adapters

Each adapter reads vendor telemetry and emits the canonical `hardware_calibration` object. A partial card does not copy the median of the measured rows into `default_error_1q` or `default_error_2q`, so unmeasured qubits and edges stay on the uncalibrated model. A scalar readout fidelity `F` becomes the symmetric pair `(1-F)/2`. `NaN`, infinities, and values outside the physical bounds are dropped. Qubit and edge maps are serialized in deterministic order.

Layout remapping projects a full-chip table onto the physical qubits used by a transpiled circuit. Pass `layout` as a logical-to-physical list. Edges that touch an unmapped qubit are removed.

## IBM Quantum (Qiskit)

`extract_from_qiskit(backend, layout=isa_circuit)` reads a `BackendV2` or `Target`. Virtual `rz` gates are ignored so a zero-duration frame change is not treated as a physical error. Asymmetric readout probabilities are kept when the backend exposes them.

```python
from znepro import extract_from_qiskit
calibration = extract_from_qiskit(backend, layout=[10, 11, 12])
```

## AWS Braket

`extract_from_braket(device, layout=[0, 1, 2])` accepts standardized gate-model properties and provider payloads for Rigetti, IonQ, and IQM. IQM's 1-based node labels are rewritten to 0-based OpenQASM indices.

## Google Cirq

`extract_from_cirq(metrics, qubit_order=[...])` maps `GridQubit` names, parallel entangling errors, and asymmetric `p00` / `p11` readout onto contiguous OpenQASM indices.

## Quantinuum and TKET

`extract_from_pytket(backend_info)` reads node and edge error tables, QCCD memory times, and 2x2 readout confusion matrices.

## Neutral atom

`build_neutral_atom_calibration(...)` builds a zoned Rydberg card for QuEra, Pasqal, or Atom Computing. Bright-state atom loss is folded into the asymmetric measurement error `prob_meas0_prep1`.

```python
from znepro import build_neutral_atom_calibration
card = build_neutral_atom_calibration(
    num_qubits=8,
    cz_fidelity=0.995,
    single_qubit_fidelity=0.9992,
    t1_s=4.0,
    t2_ms=15.0,
    readout_error=0.008,
    atom_loss_prob=0.004,
)
```

Server-only control flags are not part of this public schema and are never written into the JSON.
