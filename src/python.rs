//! Thin PyO3 bindings over the audited Rust calibration core.
//!
//! All numeric normalization, median imputation, layout remapping, and request
//! serialization stay in the Rust modules. This file only marshals arguments.

use std::collections::BTreeMap;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use serde_json::Value;

use crate::adapters::{
    auto_extract_calibration_json, build_neutral_atom_calibration, extract_from_braket_json,
    extract_from_cirq_json_with_order, extract_from_pytket_json, extract_from_qiskit_json,
    NeutralAtomConfig,
};
use crate::client::ZneproJobRequest;
use crate::layout::QubitLayout;
use crate::qasm::canonicalize_qasm;
use crate::schema::{ClientError, HardwareCalibration};

fn client_err(err: ClientError) -> PyErr {
    PyValueError::new_err(err.to_string())
}

fn parse_json(payload: &str) -> PyResult<Value> {
    serde_json::from_str(payload).map_err(|err| PyValueError::new_err(err.to_string()))
}

fn layout_from_kwargs(
    logical_to_physical: Option<Vec<u32>>,
    physical_to_logical: Option<BTreeMap<u32, u32>>,
) -> Option<QubitLayout> {
    if let Some(map) = physical_to_logical {
        if !map.is_empty() {
            return Some(QubitLayout::PhysicalToLogical(map));
        }
    }
    if let Some(list) = logical_to_physical {
        if !list.is_empty() {
            return Some(QubitLayout::LogicalToPhysical(list));
        }
    }
    None
}

/// Python-visible hardware calibration card.
#[pyclass(name = "HardwareCalibration", module = "znepro._core")]
#[derive(Clone)]
pub struct PyHardwareCalibration {
    pub(crate) inner: HardwareCalibration,
}

impl PyHardwareCalibration {
    pub(crate) fn from_inner(inner: HardwareCalibration) -> Self {
        Self { inner }
    }
}

#[pymethods]
impl PyHardwareCalibration {
    /// Serialize the sanitized card to JSON text.
    #[pyo3(signature = (pretty=false))]
    fn to_json(&self, pretty: bool) -> PyResult<String> {
        let value = self.inner.to_json_value();
        if pretty {
            serde_json::to_string_pretty(&value).map_err(|err| PyValueError::new_err(err.to_string()))
        } else {
            serde_json::to_string(&value).map_err(|err| PyValueError::new_err(err.to_string()))
        }
    }

    /// Remap physical device indices onto contiguous logical indices.
    #[pyo3(signature = (*, logical_to_physical=None, physical_to_logical=None))]
    fn remap(
        &self,
        logical_to_physical: Option<Vec<u32>>,
        physical_to_logical: Option<BTreeMap<u32, u32>>,
    ) -> PyResult<Self> {
        let layout = layout_from_kwargs(logical_to_physical, physical_to_logical)
            .ok_or_else(|| PyValueError::new_err("remap requires a non-empty layout"))?;
        Ok(Self::from_inner(
            self.inner.remap_qubits(&layout.physical_to_logical()),
        ))
    }

    /// Number of qubit rows present on the card.
    fn qubit_count(&self) -> usize {
        self.inner.qubits.len()
    }

    /// Number of coupler / edge rows present on the card.
    fn edge_count(&self) -> usize {
        self.inner.edges.len()
    }

    fn __repr__(&self) -> String {
        format!(
            "HardwareCalibration(qubits={}, edges={})",
            self.inner.qubits.len(),
            self.inner.edges.len()
        )
    }
}

#[pyfunction]
#[pyo3(name = "extract_from_qiskit", signature = (json_payload, *, logical_to_physical=None, physical_to_logical=None))]
fn py_extract_qiskit(
    json_payload: &str,
    logical_to_physical: Option<Vec<u32>>,
    physical_to_logical: Option<BTreeMap<u32, u32>>,
) -> PyResult<PyHardwareCalibration> {
    let value = parse_json(json_payload)?;
    let layout = layout_from_kwargs(logical_to_physical, physical_to_logical);
    let calib = extract_from_qiskit_json(&value, layout.as_ref()).map_err(client_err)?;
    Ok(PyHardwareCalibration::from_inner(calib))
}

#[pyfunction]
#[pyo3(name = "extract_from_braket", signature = (json_payload, *, logical_to_physical=None, physical_to_logical=None))]
fn py_extract_braket(
    json_payload: &str,
    logical_to_physical: Option<Vec<u32>>,
    physical_to_logical: Option<BTreeMap<u32, u32>>,
) -> PyResult<PyHardwareCalibration> {
    let value = parse_json(json_payload)?;
    let layout = layout_from_kwargs(logical_to_physical, physical_to_logical);
    let calib = extract_from_braket_json(&value, layout.as_ref()).map_err(client_err)?;
    Ok(PyHardwareCalibration::from_inner(calib))
}

#[pyfunction]
#[pyo3(name = "extract_from_cirq", signature = (json_payload, *, qubit_order=None))]
fn py_extract_cirq(
    json_payload: &str,
    qubit_order: Option<Vec<String>>,
) -> PyResult<PyHardwareCalibration> {
    let value = parse_json(json_payload)?;
    let order_ref = qubit_order.as_deref();
    let calib = extract_from_cirq_json_with_order(&value, None, order_ref).map_err(client_err)?;
    Ok(PyHardwareCalibration::from_inner(calib))
}

#[pyfunction]
#[pyo3(name = "extract_from_pytket", signature = (json_payload))]
fn py_extract_pytket(json_payload: &str) -> PyResult<PyHardwareCalibration> {
    let value = parse_json(json_payload)?;
    let calib = extract_from_pytket_json(&value, None).map_err(client_err)?;
    Ok(PyHardwareCalibration::from_inner(calib))
}

#[pyfunction]
#[pyo3(
    name = "build_neutral_atom_calibration",
    signature = (
        num_qubits,
        *,
        cz_fidelity=0.995,
        single_qubit_fidelity=0.9992,
        t1_s=4.0,
        t2_ms=15.0,
        cz_duration_ns=400.0,
        single_qubit_duration_ns=1000.0,
        readout_error=0.008,
        atom_loss_prob=0.004
    )
)]
fn py_build_neutral_atom(
    num_qubits: u32,
    cz_fidelity: f64,
    single_qubit_fidelity: f64,
    t1_s: f64,
    t2_ms: f64,
    cz_duration_ns: f64,
    single_qubit_duration_ns: f64,
    readout_error: f64,
    atom_loss_prob: f64,
) -> PyResult<PyHardwareCalibration> {
    let config = NeutralAtomConfig {
        num_qubits,
        coupling_edges: Vec::new(),
        cz_fidelity,
        single_qubit_fidelity,
        t1_s,
        t2_ms,
        cz_duration_ns,
        single_qubit_duration_ns,
        readout_error,
        atom_loss_prob,
    };
    let calib = build_neutral_atom_calibration(&config, None).map_err(client_err)?;
    Ok(PyHardwareCalibration::from_inner(calib))
}

#[pyfunction]
#[pyo3(name = "auto_extract_calibration", signature = (json_payload, *, logical_to_physical=None, physical_to_logical=None))]
fn py_auto_extract(
    json_payload: &str,
    logical_to_physical: Option<Vec<u32>>,
    physical_to_logical: Option<BTreeMap<u32, u32>>,
) -> PyResult<PyHardwareCalibration> {
    let value = parse_json(json_payload)?;
    let layout = layout_from_kwargs(logical_to_physical, physical_to_logical);
    let calib = auto_extract_calibration_json(&value, layout.as_ref()).map_err(client_err)?;
    Ok(PyHardwareCalibration::from_inner(calib))
}

#[pyfunction]
#[pyo3(
    name = "build_job_request_json",
    signature = (
        qasm,
        counts,
        *,
        observables=None,
        calibration=None,
        clip_box=None,
        backend_name=None,
        shots=None
    )
)]
fn py_build_job_request_json(
    qasm: String,
    counts: BTreeMap<String, u64>,
    observables: Option<Vec<String>>,
    calibration: Option<&PyHardwareCalibration>,
    clip_box: Option<bool>,
    backend_name: Option<String>,
    shots: Option<u64>,
) -> PyResult<String> {
    if counts.is_empty() {
        return Err(PyValueError::new_err("counts histogram must be non-empty"));
    }
    let qasm = canonicalize_qasm(&qasm).map_err(|err| PyValueError::new_err(err.to_string()))?;
    let total: u64 = counts.values().copied().sum();
    if let Some(declared) = shots {
        if declared != total {
            return Err(PyValueError::new_err(format!(
                "shots={declared} does not match sum(counts)={total}"
            )));
        }
    }
    let mut request = ZneproJobRequest::single_with_observables(
        qasm,
        counts,
        observables,
        calibration.map(|card| card.inner.clone()),
    );
    request.clip_box = clip_box;
    request.backend_name = backend_name;
    let value = request.to_json_value();
    serde_json::to_string(&value).map_err(|err| PyValueError::new_err(err.to_string()))
}

#[pyfunction]
#[pyo3(
    name = "build_histogram_job_json",
    signature = (qasm, counts, *, calibration=None, clip_box=None, backend_name=None, observables=None, shots=None)
)]
fn py_build_histogram_job_json(
    qasm: String,
    counts: BTreeMap<String, u64>,
    calibration: Option<&PyHardwareCalibration>,
    clip_box: Option<bool>,
    backend_name: Option<String>,
    observables: Option<Vec<String>>,
    shots: Option<u64>,
) -> PyResult<String> {
    // Alias of the primary single-run builder.
    py_build_job_request_json(
        qasm,
        counts,
        observables,
        calibration,
        clip_box,
        backend_name,
        shots,
    )
}

#[pyfunction]
#[pyo3(
    name = "build_multi_scale_job_json",
    signature = (
        qasm,
        noise_scales,
        shots,
        *,
        expectations=None,
        pauli_expectations=None,
        counts=None,
        calibration=None
    )
)]
fn py_build_multi_scale_job_json(
    qasm: String,
    noise_scales: Vec<f64>,
    shots: usize,
    expectations: Option<Vec<f64>>,
    pauli_expectations: Option<BTreeMap<String, Vec<f64>>>,
    counts: Option<BTreeMap<String, u64>>,
    calibration: Option<&PyHardwareCalibration>,
) -> PyResult<String> {
    // Optional offline / harness helper — not the primary client path.
    let qasm = canonicalize_qasm(&qasm).map_err(|err| PyValueError::new_err(err.to_string()))?;
    let calib = calibration.map(|card| card.inner.clone());
    let request = if let Some(pauli) = pauli_expectations {
        let mut req = ZneproJobRequest::multi_term(qasm, noise_scales, pauli, shots, calib);
        if let Some(hist) = counts {
            req.shots = hist;
        }
        req
    } else {
        let exp = expectations.unwrap_or_default();
        ZneproJobRequest::multi_scale(&qasm, &noise_scales, &exp, shots as u64, counts, calib)
    };
    let value = request.to_json_value();
    serde_json::to_string(&value).map_err(|err| PyValueError::new_err(err.to_string()))
}

/// Python extension module `znepro._core`.
#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyHardwareCalibration>()?;
    m.add_function(wrap_pyfunction!(py_extract_qiskit, m)?)?;
    m.add_function(wrap_pyfunction!(py_extract_braket, m)?)?;
    m.add_function(wrap_pyfunction!(py_extract_cirq, m)?)?;
    m.add_function(wrap_pyfunction!(py_extract_pytket, m)?)?;
    m.add_function(wrap_pyfunction!(py_build_neutral_atom, m)?)?;
    m.add_function(wrap_pyfunction!(py_auto_extract, m)?)?;
    m.add_function(wrap_pyfunction!(py_build_job_request_json, m)?)?;
    m.add_function(wrap_pyfunction!(py_build_histogram_job_json, m)?)?;
    m.add_function(wrap_pyfunction!(py_build_multi_scale_job_json, m)?)?;
    m.add_function(wrap_pyfunction!(py_canonicalize_qasm, m)?)?;
    m.add_function(wrap_pyfunction!(py_qasm_gates, m)?)?;
    Ok(())
}

#[pyfunction]
#[pyo3(name = "canonicalize_qasm")]
fn py_canonicalize_qasm(qasm: &str) -> PyResult<String> {
    canonicalize_qasm(qasm).map_err(|err| PyValueError::new_err(err.to_string()))
}

#[pyfunction]
#[pyo3(name = "qasm_gates")]
fn py_qasm_gates(qasm: &str) -> PyResult<Vec<(String, Vec<u32>, Vec<f64>)>> {
    let gates = crate::qasm::qasm_gates(qasm).map_err(|err| PyValueError::new_err(err.to_string()))?;
    Ok(gates
        .into_iter()
        .map(|gate| {
            (
                gate.name,
                gate.qubits.into_iter().map(|qubit| qubit.index).collect(),
                gate.parameters,
            )
        })
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::Python;

    #[test]
    fn uncalibrated_single_run_job_json_omits_calibration_and_scales() {
        pyo3::prepare_freethreaded_python();
        Python::with_gil(|_py| {
            let mut counts = BTreeMap::new();
            counts.insert("0".to_owned(), 3900);
            counts.insert("1".to_owned(), 100);
            let text = py_build_job_request_json(
                "OPENQASM 2.0;\nqreg q[1];\n".to_string(),
                counts,
                None,
                None,
                None,
                None,
                Some(4000),
            )
            .expect("json");
            assert!(!text.contains("hardware_calibration"));
            assert!(!text.contains("hardware_scales"));
            assert!(text.contains("shots"));
            let hidden = format!("{}{}{}", "enable_", "light_", "cone");
            assert!(!text.contains(&hidden));
        });
    }

    #[test]
    fn calibrated_single_run_job_json_embeds_sanitized_card() {
        pyo3::prepare_freethreaded_python();
        Python::with_gil(|_py| {
            let card = py_build_neutral_atom(
                2, 0.995, 0.9992, 4.0, 15.0, 400.0, 1000.0, 0.008, 0.004,
            )
            .expect("card");
            assert_eq!(card.qubit_count(), 2);
            let mut counts = BTreeMap::new();
            counts.insert("00".to_owned(), 3500);
            counts.insert("11".to_owned(), 500);
            let text = py_build_job_request_json(
                "OPENQASM 2.0;\nqreg q[2];\n".to_string(),
                counts,
                Some(vec!["ZZ".to_owned(), "XX".to_owned()]),
                Some(&card),
                None,
                None,
                Some(4000),
            )
            .expect("json");
            assert!(text.contains("hardware_calibration"));
            assert!(text.contains("clique_observables"));
            assert!(!text.contains("hardware_scales"));
            let hidden = format!("{}{}{}", "enable_", "light_", "cone");
            assert!(!text.contains(&hidden));
        });
    }

    #[test]
    fn multi_scale_helper_emits_scales_when_requested() {
        pyo3::prepare_freethreaded_python();
        Python::with_gil(|_py| {
            let text = py_build_multi_scale_job_json(
                "OPENQASM 2.0;\nqreg q[1];\n".to_string(),
                vec![1.0, 1.5],
                1000,
                Some(vec![0.9, 0.8]),
                None,
                None,
                None,
            )
            .expect("json");
            assert!(text.contains("hardware_scales"));
            assert!(!text.contains("hardware_calibration"));
        });
    }
}
