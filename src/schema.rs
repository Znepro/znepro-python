//! Normalized public hardware telemetry DTOs wire-compatible with the ZNEPro API.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use thiserror::Error;

/// Public SDK error type.
#[derive(Debug, Error, Clone, PartialEq, Eq)]
pub enum ClientError {
    #[error("{0}")]
    Message(String),
    #[error("unsupported calibration schema")]
    UnsupportedSchema,
    #[error("json parse error: {0}")]
    Json(String),
}

impl ClientError {
    pub fn msg(text: impl Into<String>) -> Self {
        Self::Message(text.into())
    }
}

/// Sanitize a positive duration / coherence time. Non-finite or `<= 0` → `None`.
pub fn sanitize_positive(value: Option<f64>) -> Option<f64> {
    value.and_then(|v| {
        if v.is_finite() && v > 0.0 {
            Some(v)
        } else {
            None
        }
    })
}

/// Sanitize a gate error into `[0, 0.999_999]`. Negative / non-finite → `None`.
pub fn sanitize_error(value: Option<f64>) -> Option<f64> {
    value.and_then(|v| {
        if !v.is_finite() || v < 0.0 {
            None
        } else {
            Some(v.min(0.999_999))
        }
    })
}

/// Sanitize a readout assignment error into `[0, 0.5]`.
pub fn sanitize_readout(value: Option<f64>) -> Option<f64> {
    value.and_then(|v| {
        if !v.is_finite() || v < 0.0 {
            None
        } else {
            Some(v.min(0.5))
        }
    })
}

fn median_f64(mut values: Vec<f64>) -> Option<f64> {
    values.retain(|v| v.is_finite());
    if values.is_empty() {
        return None;
    }
    values.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let mid = values.len() / 2;
    if values.len() % 2 == 1 {
        Some(values[mid])
    } else {
        Some(0.5 * (values[mid - 1] + values[mid]))
    }
}

/// Per-qubit calibration row.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct QubitCalibration {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub t1_us: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub t2_us: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error_1q: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub gate_time_1q_ns: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub prob_meas1_prep0: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub prob_meas0_prep1: Option<f64>,
}

impl QubitCalibration {
    /// Return a sanitized copy of this row.
    pub fn sanitize(&self) -> Self {
        Self {
            t1_us: sanitize_positive(self.t1_us),
            t2_us: sanitize_positive(self.t2_us),
            error_1q: sanitize_error(self.error_1q),
            gate_time_1q_ns: sanitize_positive(self.gate_time_1q_ns),
            prob_meas1_prep0: sanitize_readout(self.prob_meas1_prep0),
            prob_meas0_prep1: sanitize_readout(self.prob_meas0_prep1),
        }
    }

    pub fn is_empty(&self) -> bool {
        self.t1_us.is_none()
            && self.t2_us.is_none()
            && self.error_1q.is_none()
            && self.gate_time_1q_ns.is_none()
            && self.prob_meas1_prep0.is_none()
            && self.prob_meas0_prep1.is_none()
    }
}

/// Coupler / two-qubit edge calibration.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EdgeCalibration {
    pub q0: u32,
    pub q1: u32,
    pub error_2q: f64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub gate_time_2q_ns: Option<f64>,
}

impl EdgeCalibration {
    /// Normalize endpoint order (`q0 <= q1`) and sanitize numeric fields.
    pub fn sanitize(&self) -> Option<Self> {
        if self.q0 == self.q1 {
            return None;
        }
        let error = sanitize_error(Some(self.error_2q)).unwrap_or(0.0);
        let (q0, q1) = if self.q0 <= self.q1 {
            (self.q0, self.q1)
        } else {
            (self.q1, self.q0)
        };
        Some(Self {
            q0,
            q1,
            error_2q: error,
            gate_time_2q_ns: sanitize_positive(self.gate_time_2q_ns),
        })
    }
}

/// Rich optional hardware calibration card for the public API.
///
/// Defaults are optional so an omitted field stays omitted in JSON. Server-side
/// deserializers apply their own defaults for missing numeric keys.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct HardwareCalibration {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub default_error_1q: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub default_error_2q: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub default_gate_time_1q_ns: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub default_gate_time_2q_ns: Option<f64>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub qubits: BTreeMap<u32, QubitCalibration>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub edges: Vec<EdgeCalibration>,
}

impl HardwareCalibration {
    /// Sanitize all fields, drop self-loops, and sort edges by `(q0, q1)`.
    pub fn sanitize(&self) -> Self {
        let mut qubits = BTreeMap::new();
        for (q, row) in &self.qubits {
            let clean = row.sanitize();
            if !clean.is_empty() {
                qubits.insert(*q, clean);
            }
        }
        let mut edges: Vec<EdgeCalibration> = self
            .edges
            .iter()
            .filter_map(EdgeCalibration::sanitize)
            .collect();
        edges.sort_by_key(|e| (e.q0, e.q1));
        edges.dedup_by(|a, b| a.q0 == b.q0 && a.q1 == b.q1);
        Self {
            default_error_1q: sanitize_error(self.default_error_1q),
            default_error_2q: sanitize_error(self.default_error_2q),
            default_gate_time_1q_ns: sanitize_positive(self.default_gate_time_1q_ns),
            default_gate_time_2q_ns: sanitize_positive(self.default_gate_time_2q_ns),
            qubits,
            edges,
        }
    }

    /// Fill any missing default fields from the median of per-qubit / per-edge values.
    pub fn populate_defaults_from_medians(&mut self) {
        if self.default_error_1q.is_none() {
            let vals: Vec<f64> = self.qubits.values().filter_map(|q| q.error_1q).collect();
            self.default_error_1q = sanitize_error(median_f64(vals));
        }
        if self.default_gate_time_1q_ns.is_none() {
            let vals: Vec<f64> = self
                .qubits
                .values()
                .filter_map(|q| q.gate_time_1q_ns)
                .collect();
            self.default_gate_time_1q_ns = sanitize_positive(median_f64(vals));
        }
        if self.default_error_2q.is_none() {
            let vals: Vec<f64> = self.edges.iter().map(|e| e.error_2q).collect();
            self.default_error_2q = sanitize_error(median_f64(vals));
        }
        if self.default_gate_time_2q_ns.is_none() {
            let vals: Vec<f64> = self.edges.iter().filter_map(|e| e.gate_time_2q_ns).collect();
            self.default_gate_time_2q_ns = sanitize_positive(median_f64(vals));
        }
    }

    /// Re-index qubits and edges from physical device indices to logical indices.
    pub fn remap_qubits(&self, phys_to_logical: &BTreeMap<u32, u32>) -> Self {
        let mut qubits = BTreeMap::new();
        for (phys, row) in &self.qubits {
            if let Some(&logical) = phys_to_logical.get(phys) {
                qubits.insert(logical, row.clone());
            }
        }
        let mut edges = Vec::new();
        for edge in &self.edges {
            let Some(&l0) = phys_to_logical.get(&edge.q0) else {
                continue;
            };
            let Some(&l1) = phys_to_logical.get(&edge.q1) else {
                continue;
            };
            if l0 == l1 {
                continue;
            }
            edges.push(EdgeCalibration {
                q0: l0,
                q1: l1,
                error_2q: edge.error_2q,
                gate_time_2q_ns: edge.gate_time_2q_ns,
            });
        }
        Self {
            default_error_1q: self.default_error_1q,
            default_error_2q: self.default_error_2q,
            default_gate_time_1q_ns: self.default_gate_time_1q_ns,
            default_gate_time_2q_ns: self.default_gate_time_2q_ns,
            qubits,
            edges,
        }
        .sanitize()
    }

    /// Serialize to a JSON value (after sanitize).
    pub fn to_json_value(&self) -> serde_json::Value {
        serde_json::to_value(self.sanitize()).unwrap_or(serde_json::Value::Null)
    }
}
