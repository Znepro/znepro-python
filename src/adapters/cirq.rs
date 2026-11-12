//! Google Cirq processor calibration extractor.

use std::collections::BTreeMap;

use serde_json::Value;

use crate::adapters::apply_layout;
use crate::layout::QubitLayout;
use crate::schema::{
    sanitize_error, sanitize_positive, sanitize_readout, EdgeCalibration, HardwareCalibration,
    QubitCalibration, ClientError,
};

fn parse_qubit_key(key: &str) -> Option<String> {
    let trimmed = key.trim();
    if trimmed.is_empty() {
        return None;
    }
    Some(trimmed.to_string())
}

fn normalize_grid_key(key: &str) -> String {
    key.trim()
        .trim_matches(|c| c == '(' || c == ')')
        .replace(' ', "")
        .replace(',', "_")
}

fn build_key_order(raw: &Value, qubit_order: Option<&[String]>) -> BTreeMap<String, u32> {
    if let Some(order) = qubit_order {
        return order
            .iter()
            .enumerate()
            .flat_map(|(i, k)| {
                let idx = i as u32;
                let mut aliases = vec![(k.clone(), idx)];
                aliases.push((normalize_grid_key(k), idx));
                aliases
            })
            .collect();
    }
    let mut keys = Vec::new();
    for field in [
        "single_qubit_idle_t1_micros",
        "t1_us",
        "single_qubit_idle_t2_micros",
        "t2_us",
        "single_qubit_rb_pauli_error_per_gate",
        "single_qubit_readout_p00_error",
        "single_qubit_readout_p11_error",
    ] {
        if let Some(obj) = raw.get(field).and_then(|v| v.as_object()) {
            for k in obj.keys() {
                if let Some(pk) = parse_qubit_key(k) {
                    if !keys.contains(&pk) {
                        keys.push(pk);
                    }
                }
            }
        }
    }
    if keys.iter().all(|k| k.parse::<u32>().is_ok()) {
        keys.sort_by_key(|k| k.parse::<u32>().unwrap_or(0));
    } else {
        keys.sort();
    }
    let mut map = BTreeMap::new();
    for (i, k) in keys.into_iter().enumerate() {
        let idx = i as u32;
        map.insert(normalize_grid_key(&k), idx);
        map.insert(k, idx);
    }
    map
}

fn parse_pair_key(key: &str, order: &BTreeMap<String, u32>) -> Option<(u32, u32)> {
    let norm = normalize_grid_key(key);
    let parts: Vec<&str> = if norm.contains('_') {
        norm.split('_').collect()
    } else if norm.contains('-') {
        norm.split('-').collect()
    } else {
        return None;
    };
    if parts.len() != 2 {
        return None;
    }
    let left = order
        .get(parts[0])
        .copied()
        .or_else(|| parts[0].parse::<u32>().ok())?;
    let right = order
        .get(parts[1])
        .copied()
        .or_else(|| parts[1].parse::<u32>().ok())?;
    Some((left, right))
}

fn read_qubit_map(raw: &Value, field: &str, order: &BTreeMap<String, u32>) -> BTreeMap<u32, f64> {
    let mut out = BTreeMap::new();
    let Some(obj) = raw.get(field).and_then(|v| v.as_object()) else {
        return out;
    };
    for (key, val) in obj {
        let Some(pk) = parse_qubit_key(key) else {
            continue;
        };
        let idx = order
            .get(&pk)
            .copied()
            .or_else(|| order.get(&normalize_grid_key(&pk)).copied());
        let Some(idx) = idx else {
            continue;
        };
        if let Some(n) = val.as_f64() {
            out.insert(idx, n);
        }
    }
    out
}

/// Extract normalized calibration from a Cirq processor calibration dump.
pub fn extract_from_cirq_json(
    raw: &Value,
    layout: Option<&QubitLayout>,
) -> Result<HardwareCalibration, ClientError> {
    extract_from_cirq_json_with_order(raw, layout, None)
}

/// Same as [`extract_from_cirq_json`] with an optional explicit qubit key order.
pub fn extract_from_cirq_json_with_order(
    raw: &Value,
    layout: Option<&QubitLayout>,
    qubit_order: Option<&[String]>,
) -> Result<HardwareCalibration, ClientError> {
    let order = build_key_order(raw, qubit_order);
    let mut qubits: BTreeMap<u32, QubitCalibration> = BTreeMap::new();

    let t1 = read_qubit_map(raw, "single_qubit_idle_t1_micros", &order);
    let t1b = read_qubit_map(raw, "t1_us", &order);
    let t2 = read_qubit_map(raw, "single_qubit_idle_t2_micros", &order);
    let t2b = read_qubit_map(raw, "t2_us", &order);
    let e1 = read_qubit_map(raw, "single_qubit_rb_pauli_error_per_gate", &order);
    let p00 = read_qubit_map(raw, "single_qubit_readout_p00_error", &order);
    let p11 = read_qubit_map(raw, "single_qubit_readout_p11_error", &order);

    let mut indices: Vec<u32> = order.values().copied().collect();
    indices.sort_unstable();
    indices.dedup();
    for q in indices {
        let mut row = QubitCalibration::default();
        row.t1_us = sanitize_positive(t1.get(&q).copied().or_else(|| t1b.get(&q).copied()));
        row.t2_us = sanitize_positive(t2.get(&q).copied().or_else(|| t2b.get(&q).copied()));
        row.error_1q = sanitize_error(e1.get(&q).copied());
        // Cirq p00_error → prep0 measure1; p11_error → prep1 measure0.
        row.prob_meas1_prep0 = sanitize_readout(p00.get(&q).copied());
        row.prob_meas0_prep1 = sanitize_readout(p11.get(&q).copied());
        if !row.is_empty() {
            qubits.insert(q, row);
        }
    }

    let mut edges = Vec::new();
    for field in [
        "two_qubit_cz_pauli_error",
        "two_qubit_parallel_sycamore_gate_xeb_pauli_error_per_cycle",
    ] {
        if let Some(obj) = raw.get(field).and_then(|v| v.as_object()) {
            for (key, val) in obj {
                let Some((q0, q1)) = parse_pair_key(key, &order) else {
                    continue;
                };
                let err = val.as_f64().and_then(|v| sanitize_error(Some(v))).unwrap_or(0.0);
                edges.push(EdgeCalibration {
                    q0,
                    q1,
                    error_2q: err,
                    gate_time_2q_ns: None,
                });
            }
        }
    }

    let calib = HardwareCalibration {
        default_error_1q: None,
        default_error_2q: None,
        default_gate_time_1q_ns: None,
        default_gate_time_2q_ns: None,
        qubits,
        edges,
    };
    Ok(apply_layout(calib, layout))
}
