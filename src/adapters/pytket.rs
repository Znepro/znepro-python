//! Quantinuum / Pytket BackendInfo calibration extractor.

use std::collections::BTreeMap;

use serde_json::Value;

use crate::adapters::{apply_layout, to_ns, to_us};
use crate::layout::QubitLayout;
use crate::schema::{
    sanitize_error, sanitize_positive, sanitize_readout, EdgeCalibration, HardwareCalibration,
    QubitCalibration, ClientError,
};

const DEFAULT_1Q_NS: f64 = 25_000.0;
const DEFAULT_2Q_NS: f64 = 250_000.0;

fn node_index(nodes: &[Value], key: &str) -> Option<u32> {
    if let Ok(i) = key.parse::<u32>() {
        return Some(i);
    }
    for (idx, node) in nodes.iter().enumerate() {
        if node.as_str() == Some(key) {
            return Some(idx as u32);
        }
        if let Some(obj) = node.as_object() {
            if obj.get("id").and_then(|v| v.as_str()) == Some(key)
                || obj.get("name").and_then(|v| v.as_str()) == Some(key)
            {
                return Some(idx as u32);
            }
        }
    }
    None
}

fn parse_edge_key(key: &str, nodes: &[Value]) -> Option<(u32, u32)> {
    let cleaned = key
        .trim()
        .trim_matches(|c| c == '(' || c == ')' || c == '[' || c == ']')
        .replace(' ', "");
    let parts: Vec<&str> = if cleaned.contains(',') {
        cleaned.split(',').collect()
    } else if cleaned.contains('_') {
        cleaned.split('_').collect()
    } else if cleaned.contains('-') {
        cleaned.split('-').collect()
    } else {
        return None;
    };
    if parts.len() != 2 {
        return None;
    }
    Some((node_index(nodes, parts[0])?, node_index(nodes, parts[1])?))
}

/// Extract normalized calibration from a serialized Pytket `BackendInfo` dump.
pub fn extract_from_pytket_json(
    raw: &Value,
    layout: Option<&QubitLayout>,
) -> Result<HardwareCalibration, ClientError> {
    let nodes = raw
        .get("nodes")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let n = if nodes.is_empty() {
        raw.get("n_nodes")
            .and_then(|v| v.as_u64())
            .unwrap_or(0) as usize
    } else {
        nodes.len()
    };

    let mut qubits: BTreeMap<u32, QubitCalibration> = BTreeMap::new();
    for q in 0..n as u32 {
        qubits.insert(q, QubitCalibration::default());
    }

    if let Some(obj) = raw
        .get("averaged_node_gate_errors")
        .and_then(|v| v.as_object())
    {
        for (key, val) in obj {
            let Some(q) = node_index(&nodes, key).or_else(|| key.parse::<u32>().ok()) else {
                continue;
            };
            let err = val.as_f64().and_then(|v| sanitize_error(Some(v)));
            qubits.entry(q).or_default().error_1q = err;
        }
    }

    let mut edges = Vec::new();
    if let Some(obj) = raw
        .get("averaged_edge_gate_errors")
        .and_then(|v| v.as_object())
    {
        for (key, val) in obj {
            let Some((q0, q1)) = parse_edge_key(key, &nodes) else {
                continue;
            };
            let err = val.as_f64().and_then(|v| sanitize_error(Some(v))).unwrap_or(0.0);
            edges.push(EdgeCalibration {
                q0,
                q1,
                error_2q: err,
                gate_time_2q_ns: Some(DEFAULT_2Q_NS),
            });
        }
    }

    if let Some(arr) = raw.get("all_readout_errors").and_then(|v| v.as_array()) {
        for (idx, entry) in arr.iter().enumerate() {
            let q = idx as u32;
            let slot = qubits.entry(q).or_default();
            if let Some(mat) = entry.as_array() {
                // [[p00, p10], [p01, p11]]
                if mat.len() >= 2 {
                    let row0 = mat[0].as_array();
                    let row1 = mat[1].as_array();
                    if let (Some(r0), Some(r1)) = (row0, row1) {
                        if r0.len() >= 2 {
                            slot.prob_meas1_prep0 = sanitize_readout(r0[1].as_f64());
                        }
                        if r1.len() >= 1 {
                            slot.prob_meas0_prep1 = sanitize_readout(r1[0].as_f64());
                        }
                        continue;
                    }
                }
            }
            if let Some(e) = entry.as_f64().and_then(|v| sanitize_readout(Some(v))) {
                slot.prob_meas1_prep0 = Some(e);
                slot.prob_meas0_prep1 = Some(e);
            }
        }
    } else if let Some(obj) = raw.get("all_readout_errors").and_then(|v| v.as_object()) {
        for (key, entry) in obj {
            let Some(q) = node_index(&nodes, key).or_else(|| key.parse::<u32>().ok()) else {
                continue;
            };
            let slot = qubits.entry(q).or_default();
            if let Some(mat) = entry.as_array() {
                if mat.len() >= 2 {
                    if let (Some(r0), Some(r1)) = (mat[0].as_array(), mat[1].as_array()) {
                        if r0.len() >= 2 {
                            slot.prob_meas1_prep0 = sanitize_readout(r0[1].as_f64());
                        }
                        if !r1.is_empty() {
                            slot.prob_meas0_prep1 = sanitize_readout(r1[0].as_f64());
                        }
                    }
                }
            }
        }
    }

    let mut default_error_2q = None;
    let mut t1 = None;
    let mut t2 = None;
    if let Some(misc) = raw.get("misc").and_then(|v| v.as_object()) {
        if let Some(v) = misc.get("t1_us").and_then(|x| x.as_f64()) {
            t1 = sanitize_positive(Some(v));
        } else if let Some(v) = misc.get("t1_s").and_then(|x| x.as_f64()) {
            t1 = sanitize_positive(to_us(v, Some("s")));
        }
        if let Some(v) = misc.get("t2_us").and_then(|x| x.as_f64()) {
            t2 = sanitize_positive(Some(v));
        } else if let Some(v) = misc.get("t2_s").and_then(|x| x.as_f64()) {
            t2 = sanitize_positive(to_us(v, Some("s")));
        }
        if let Some(v) = misc.get("fidelity_2q_error").and_then(|x| x.as_f64()) {
            default_error_2q = sanitize_error(Some(v));
        }
        let g1 = misc
            .get("gate_time_1q_ns")
            .and_then(|x| x.as_f64())
            .or_else(|| {
                misc.get("gate_time_1q_s")
                    .and_then(|x| x.as_f64())
                    .and_then(|v| to_ns(v, Some("s")))
            });
        let g2 = misc
            .get("gate_time_2q_ns")
            .and_then(|x| x.as_f64())
            .or_else(|| {
                misc.get("gate_time_2q_s")
                    .and_then(|x| x.as_f64())
                    .and_then(|v| to_ns(v, Some("s")))
            });
        for slot in qubits.values_mut() {
            if slot.t1_us.is_none() {
                slot.t1_us = t1;
            }
            if slot.t2_us.is_none() {
                slot.t2_us = t2;
            }
            if slot.gate_time_1q_ns.is_none() {
                slot.gate_time_1q_ns = sanitize_positive(g1).or(Some(DEFAULT_1Q_NS));
            }
        }
        if let Some(d) = sanitize_positive(g2) {
            for edge in &mut edges {
                if edge.gate_time_2q_ns.is_none() {
                    edge.gate_time_2q_ns = Some(d);
                }
            }
        }
    } else {
        for slot in qubits.values_mut() {
            if slot.gate_time_1q_ns.is_none() {
                slot.gate_time_1q_ns = Some(DEFAULT_1Q_NS);
            }
        }
    }

    let calib = HardwareCalibration {
        default_error_1q: None,
        default_error_2q,
        default_gate_time_1q_ns: Some(DEFAULT_1Q_NS),
        default_gate_time_2q_ns: Some(DEFAULT_2Q_NS),
        qubits,
        edges,
    };
    Ok(apply_layout(calib, layout))
}
