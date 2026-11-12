//! Vendor calibration extractors and automatic schema detection.

mod braket;
mod cirq;
mod neutral_atom;
mod pytket;
mod qiskit;

pub use braket::extract_from_braket_json;
pub use cirq::{extract_from_cirq_json, extract_from_cirq_json_with_order};
pub use neutral_atom::{build_neutral_atom_calibration, NeutralAtomConfig};
pub use pytket::extract_from_pytket_json;
pub use qiskit::extract_from_qiskit_json;

use serde_json::Value;

use crate::layout::QubitLayout;
use crate::schema::{HardwareCalibration, ClientError};

/// Convert a duration with an optional unit label into microseconds.
pub(crate) fn to_us(value: f64, unit: Option<&str>) -> Option<f64> {
    if !value.is_finite() {
        return None;
    }
    let scale = match unit.map(|u| u.trim().to_ascii_lowercase()).as_deref() {
        None | Some("") | Some("us") | Some("µs") | Some("μs") => 1.0,
        Some("s") => 1.0e6,
        Some("ms") => 1.0e3,
        Some("ns") => 1.0e-3,
        _ => 1.0,
    };
    let out = value * scale;
    if out.is_finite() && out > 0.0 {
        Some(out)
    } else {
        None
    }
}

/// Convert a duration with an optional unit label into nanoseconds.
pub(crate) fn to_ns(value: f64, unit: Option<&str>) -> Option<f64> {
    if !value.is_finite() {
        return None;
    }
    let scale = match unit.map(|u| u.trim().to_ascii_lowercase()).as_deref() {
        None | Some("") | Some("ns") => 1.0,
        Some("s") => 1.0e9,
        Some("ms") => 1.0e6,
        Some("us") | Some("µs") | Some("μs") => 1.0e3,
        _ => 1.0,
    };
    let out = value * scale;
    if out.is_finite() && out > 0.0 {
        Some(out)
    } else {
        None
    }
}

/// Parse a JSON number that may be wrapped as `{"value": x, "unit": "s"}`.
pub(crate) fn parse_valued(node: &Value) -> Option<(f64, Option<&str>)> {
    if let Some(n) = node.as_f64() {
        return Some((n, None));
    }
    if let Some(obj) = node.as_object() {
        let value = obj.get("value")?.as_f64()?;
        let unit = obj.get("unit").and_then(|u| u.as_str());
        return Some((value, unit));
    }
    None
}

pub(crate) fn apply_layout(
    mut calib: HardwareCalibration,
    layout: Option<&QubitLayout>,
) -> HardwareCalibration {
    calib.populate_defaults_from_medians();
    let calib = calib.sanitize();
    match layout {
        Some(layout) => calib.remap_qubits(&layout.physical_to_logical()),
        None => calib,
    }
}

/// Inspect top-level JSON and dispatch to the matching vendor extractor.
pub fn auto_extract_calibration_json(
    raw: &Value,
    layout: Option<&QubitLayout>,
) -> Result<HardwareCalibration, ClientError> {
    if looks_like_qiskit(raw) {
        return extract_from_qiskit_json(raw, layout);
    }
    if looks_like_braket(raw) {
        return extract_from_braket_json(raw, layout);
    }
    if looks_like_pytket(raw) {
        return extract_from_pytket_json(raw, layout);
    }
    if looks_like_cirq(raw) {
        return extract_from_cirq_json(raw, layout);
    }
    Err(ClientError::UnsupportedSchema)
}

fn looks_like_qiskit(raw: &Value) -> bool {
    raw.get("backend_name").is_some()
        || raw.get("qubit_properties").is_some()
        || (raw.get("gates").is_some() && raw.get("qubits").is_some())
        || raw.get("operations").is_some()
}

fn looks_like_braket(raw: &Value) -> bool {
    raw.get("standardized").is_some()
        || raw.pointer("/provider/fidelity").is_some()
        || raw.pointer("/provider/properties/one_qubit").is_some()
        || raw.pointer("/provider/specs").is_some()
}

fn looks_like_pytket(raw: &Value) -> bool {
    raw.get("nodes").is_some()
        && (raw.get("averaged_node_gate_errors").is_some()
            || raw.get("averaged_edge_gate_errors").is_some()
            || raw.get("all_readout_errors").is_some())
}

fn looks_like_cirq(raw: &Value) -> bool {
    raw.get("single_qubit_idle_t1_micros").is_some()
        || raw.get("t1_us").is_some()
        || raw.get("single_qubit_rb_pauli_error_per_gate").is_some()
        || raw.get("two_qubit_cz_pauli_error").is_some()
        || raw
            .get("two_qubit_parallel_sycamore_gate_xeb_pauli_error_per_cycle")
            .is_some()
}
