//! IBM Qiskit BackendV2 / BackendProperties calibration extractor.

use std::collections::BTreeMap;

use serde_json::Value;

use crate::adapters::{apply_layout, to_ns, to_us};
use crate::layout::QubitLayout;
use crate::schema::{
    sanitize_error, sanitize_positive, sanitize_readout, EdgeCalibration, HardwareCalibration,
    QubitCalibration, ClientError,
};

const SKIP_GATES: &[&str] = &["rz", "p", "u1", "measure", "reset", "delay", "barrier", "id"];
const GATES_1Q: &[&str] = &["sx", "x", "rx", "r", "u", "ry", "h"];
const GATES_2Q: &[&str] = &["cz", "ecr", "cx", "iswap", "rzz"];

fn gate_name(raw: &str) -> String {
    raw.trim().to_ascii_lowercase()
}

fn is_skipped(name: &str) -> bool {
    SKIP_GATES.iter().any(|g| *g == name)
}

fn is_1q(name: &str) -> bool {
    GATES_1Q.iter().any(|g| *g == name) || name.starts_with('u')
}

fn is_2q(name: &str) -> bool {
    GATES_2Q.iter().any(|g| *g == name)
}

fn upsert_qubit(map: &mut BTreeMap<u32, QubitCalibration>, q: u32) -> &mut QubitCalibration {
    map.entry(q).or_default()
}

fn parse_named_param<'a>(entries: &'a [Value], names: &[&str]) -> Option<(f64, Option<&'a str>)> {
    for entry in entries {
        let Some(obj) = entry.as_object() else {
            continue;
        };
        let name = obj
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_ascii_lowercase();
        if !names.iter().any(|n| name == *n) {
            continue;
        }
        let value = obj.get("value").and_then(|v| v.as_f64())?;
        let unit = obj.get("unit").and_then(|v| v.as_str());
        return Some((value, unit));
    }
    None
}

/// Extract normalized calibration from a Qiskit backend dump.
pub fn extract_from_qiskit_json(
    raw: &Value,
    layout: Option<&QubitLayout>,
) -> Result<HardwareCalibration, ClientError> {
    let mut qubits: BTreeMap<u32, QubitCalibration> = BTreeMap::new();
    let mut edges: Vec<EdgeCalibration> = Vec::new();

    // BackendProperties-style: qubits = [[{name,unit,value}, ...], ...]
    if let Some(arr) = raw.get("qubits").and_then(|v| v.as_array()) {
        for (idx, row) in arr.iter().enumerate() {
            let Some(entries) = row.as_array() else {
                continue;
            };
            let q = idx as u32;
            let slot = upsert_qubit(&mut qubits, q);
            if let Some((v, u)) = parse_named_param(entries, &["t1"]) {
                slot.t1_us = sanitize_positive(to_us(v, u));
            }
            if let Some((v, u)) = parse_named_param(entries, &["t2"]) {
                slot.t2_us = sanitize_positive(to_us(v, u));
            }
            if let Some((v, _)) = parse_named_param(entries, &["readout_error", "prob_meas"]) {
                let e = sanitize_readout(Some(v));
                slot.prob_meas1_prep0 = e;
                slot.prob_meas0_prep1 = e;
            }
            if let Some((v, _)) = parse_named_param(entries, &["prob_meas1_prep0", "p(1|0)"]) {
                slot.prob_meas1_prep0 = sanitize_readout(Some(v));
            }
            if let Some((v, _)) = parse_named_param(entries, &["prob_meas0_prep1", "p(0|1)"]) {
                slot.prob_meas0_prep1 = sanitize_readout(Some(v));
            }
        }
    }

    // BackendV2 qubit_properties
    if let Some(props) = raw.get("qubit_properties").and_then(|v| v.as_array()) {
        for (idx, row) in props.iter().enumerate() {
            let q = idx as u32;
            let slot = upsert_qubit(&mut qubits, q);
            if let Some(t1) = row.get("t1").and_then(|v| v.as_f64()) {
                // BackendV2 Target typically stores seconds.
                slot.t1_us = sanitize_positive(to_us(t1, Some("s")));
            }
            if let Some(t2) = row.get("t2").and_then(|v| v.as_f64()) {
                slot.t2_us = sanitize_positive(to_us(t2, Some("s")));
            }
            if let Some(v) = row.get("prob_meas1_prep0").and_then(|v| v.as_f64()) {
                slot.prob_meas1_prep0 = sanitize_readout(Some(v));
            }
            if let Some(v) = row.get("prob_meas0_prep1").and_then(|v| v.as_f64()) {
                slot.prob_meas0_prep1 = sanitize_readout(Some(v));
            }
            if slot.prob_meas1_prep0.is_none() && slot.prob_meas0_prep1.is_none() {
                if let Some(v) = row.get("readout_error").and_then(|v| v.as_f64()) {
                    let readout = sanitize_readout(Some(v));
                    slot.prob_meas1_prep0 = readout;
                    slot.prob_meas0_prep1 = readout;
                }
            }
        }
    }

    // BackendProperties gates array
    if let Some(gates) = raw.get("gates").and_then(|v| v.as_array()) {
        for gate in gates {
            let Some(obj) = gate.as_object() else {
                continue;
            };
            let name = gate_name(obj.get("gate").and_then(|v| v.as_str()).unwrap_or(""));
            if name.is_empty() || is_skipped(&name) {
                continue;
            }
            let qubits_idx: Vec<u32> = obj
                .get("qubits")
                .and_then(|v| v.as_array())
                .map(|a| {
                    a.iter()
                        .filter_map(|x| x.as_u64().map(|n| n as u32))
                        .collect()
                })
                .unwrap_or_default();
            let params = obj
                .get("parameters")
                .and_then(|v| v.as_array())
                .cloned()
                .unwrap_or_default();
            let err = parse_named_param(&params, &["gate_error", "error"])
                .and_then(|(v, _)| sanitize_error(Some(v)));
            let dur = parse_named_param(&params, &["gate_length", "length", "duration"])
                .and_then(|(v, u)| to_ns(v, u.or(Some("ns"))));

            if is_1q(&name) && qubits_idx.len() == 1 {
                let slot = upsert_qubit(&mut qubits, qubits_idx[0]);
                if slot.error_1q.is_none() {
                    slot.error_1q = err;
                }
                if slot.gate_time_1q_ns.is_none() {
                    slot.gate_time_1q_ns = sanitize_positive(dur);
                }
            } else if is_2q(&name) && qubits_idx.len() == 2 {
                edges.push(EdgeCalibration {
                    q0: qubits_idx[0],
                    q1: qubits_idx[1],
                    error_2q: err.unwrap_or(0.0),
                    gate_time_2q_ns: sanitize_positive(dur),
                });
            }
        }
    }

    // BackendV2 operations / instruction map
    if let Some(ops) = raw.get("operations").and_then(|v| v.as_object()) {
        for (name_raw, node) in ops {
            let name = gate_name(name_raw);
            if is_skipped(&name) {
                continue;
            }
            let Some(entries) = node.as_array() else {
                continue;
            };
            for entry in entries {
                let qargs: Vec<u32> = entry
                    .get("qubits")
                    .or_else(|| entry.get("qargs"))
                    .and_then(|v| v.as_array())
                    .map(|a| {
                        a.iter()
                            .filter_map(|x| x.as_u64().map(|n| n as u32))
                            .collect()
                    })
                    .unwrap_or_default();
                let err = entry
                    .get("error")
                    .or_else(|| entry.get("gate_error"))
                    .and_then(|v| v.as_f64())
                    .and_then(|v| sanitize_error(Some(v)));
                let dur = entry
                    .get("duration")
                    .or_else(|| entry.get("gate_length"))
                    .and_then(|v| v.as_f64())
                    .and_then(|v| {
                        // Target durations are usually seconds.
                        to_ns(v, Some("s"))
                    });
                if is_1q(&name) && qargs.len() == 1 {
                    let slot = upsert_qubit(&mut qubits, qargs[0]);
                    if slot.error_1q.is_none() {
                        slot.error_1q = err;
                    }
                    if slot.gate_time_1q_ns.is_none() {
                        slot.gate_time_1q_ns = sanitize_positive(dur);
                    }
                } else if is_2q(&name) && qargs.len() == 2 {
                    edges.push(EdgeCalibration {
                        q0: qargs[0],
                        q1: qargs[1],
                        error_2q: err.unwrap_or(0.0),
                        gate_time_2q_ns: sanitize_positive(dur),
                    });
                }
            }
        }
    }

    // Measure / readout channel on BackendV2
    if let Some(readout) = raw.get("readout_error").or_else(|| raw.get("meas_error")) {
        if let Some(arr) = readout.as_array() {
            for (idx, v) in arr.iter().enumerate() {
                if let Some(e) = v.as_f64().and_then(|x| sanitize_readout(Some(x))) {
                    let slot = upsert_qubit(&mut qubits, idx as u32);
                    if slot.prob_meas1_prep0.is_none() {
                        slot.prob_meas1_prep0 = Some(e);
                    }
                    if slot.prob_meas0_prep1.is_none() {
                        slot.prob_meas0_prep1 = Some(e);
                    }
                }
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
