//! Neutral-atom / Rydberg device calibration builder.

use std::collections::BTreeMap;

use crate::adapters::apply_layout;
use crate::layout::QubitLayout;
use crate::schema::{
    sanitize_error, sanitize_positive, sanitize_readout, EdgeCalibration, HardwareCalibration,
    QubitCalibration, ClientError,
};

/// Strongly-typed builder for neutral-atom device telemetry.
#[derive(Debug, Clone, PartialEq)]
pub struct NeutralAtomConfig {
    pub num_qubits: u32,
    pub coupling_edges: Vec<(u32, u32)>,
    pub cz_fidelity: f64,
    pub single_qubit_fidelity: f64,
    pub t1_s: f64,
    pub t2_ms: f64,
    pub cz_duration_ns: f64,
    pub single_qubit_duration_ns: f64,
    pub readout_error: f64,
    pub atom_loss_prob: f64,
}

impl Default for NeutralAtomConfig {
    fn default() -> Self {
        Self {
            num_qubits: 0,
            coupling_edges: Vec::new(),
            cz_fidelity: 0.995,
            single_qubit_fidelity: 0.9992,
            t1_s: 4.0,
            t2_ms: 15.0,
            cz_duration_ns: 400.0,
            single_qubit_duration_ns: 1000.0,
            readout_error: 0.008,
            atom_loss_prob: 0.004,
        }
    }
}

/// Build a sanitized [`HardwareCalibration`] from a neutral-atom config.
pub fn build_neutral_atom_calibration(
    config: &NeutralAtomConfig,
    layout: Option<&QubitLayout>,
) -> Result<HardwareCalibration, ClientError> {
    if config.num_qubits == 0 {
        return Err(ClientError::msg("neutral-atom config requires num_qubits > 0"));
    }
    let err_1q = sanitize_error(Some((1.0 - config.single_qubit_fidelity).max(0.0)));
    let err_2q = sanitize_error(Some((1.0 - config.cz_fidelity).max(0.0))).unwrap_or(0.0);
    let t1_us = sanitize_positive(Some(config.t1_s * 1.0e6));
    let t2_us = sanitize_positive(Some(config.t2_ms * 1.0e3));
    let g1 = sanitize_positive(Some(config.single_qubit_duration_ns));
    let g2 = sanitize_positive(Some(config.cz_duration_ns));
    let p10 = sanitize_readout(Some(config.readout_error));
    let p01 = sanitize_readout(Some(
        (config.readout_error + config.atom_loss_prob).clamp(0.0, 0.5),
    ));

    let mut qubits = BTreeMap::new();
    for q in 0..config.num_qubits {
        qubits.insert(
            q,
            QubitCalibration {
                t1_us,
                t2_us,
                error_1q: err_1q,
                gate_time_1q_ns: g1,
                prob_meas1_prep0: p10,
                prob_meas0_prep1: p01,
            },
        );
    }
    let mut edges = Vec::new();
    for &(a, b) in &config.coupling_edges {
        if a == b || a >= config.num_qubits || b >= config.num_qubits {
            continue;
        }
        edges.push(EdgeCalibration {
            q0: a,
            q1: b,
            error_2q: err_2q,
            gate_time_2q_ns: g2,
        });
    }
    let calib = HardwareCalibration {
        default_error_1q: err_1q,
        default_error_2q: Some(err_2q),
        default_gate_time_1q_ns: g1,
        default_gate_time_2q_ns: g2,
        qubits,
        edges,
    };
    Ok(apply_layout(calib, layout))
}
