//! AWS Braket standardized / IonQ / IQM / Rigetti calibration extractors.

use std::collections::BTreeMap;

use serde_json::Value;

use crate::adapters::{apply_layout, parse_valued, to_ns, to_us};
use crate::layout::QubitLayout;
use crate::schema::{
    sanitize_error, sanitize_positive, sanitize_readout, EdgeCalibration, HardwareCalibration,
    QubitCalibration, ClientError,
};

fn upsert(map: &mut BTreeMap<u32, QubitCalibration>, q: u32) -> &mut QubitCalibration {
    map.entry(q).or_default()
}

fn parse_edge_key(key: &str) -> Option<(u32, u32)> {
    let cleaned = key.replace('_', "-");
    let mut parts = cleaned.split('-');
    let a = parts.next()?.parse::<u32>().ok()?;
    let b = parts.next()?.parse::<u32>().ok()?;
    Some((a, b))
}

fn fidelity_to_error(f: f64) -> Option<f64> {
    if !f.is_finite() {
        return None;
    }
    sanitize_error(Some((1.0 - f).max(0.0)))
}

fn extract_standardized(raw: &Value, qubits: &mut BTreeMap<u32, QubitCalibration>, edges: &mut Vec<EdgeCalibration>) {
    let Some(std) = raw.get("standardized") else {
        return;
    };
    if let Some(one) = std.get("oneQubitProperties").and_then(|v| v.as_object()) {
        for (key, node) in one {
            let Ok(q) = key.parse::<u32>() else {
                continue;
            };
            let slot = upsert(qubits, q);
            if let Some(t1) = node.get("T1").or_else(|| node.get("t1")) {
                if let Some((v, u)) = parse_valued(t1) {
                    slot.t1_us = sanitize_positive(to_us(v, u));
                }
            }
            if let Some(t2) = node.get("T2").or_else(|| node.get("t2")) {
                if let Some((v, u)) = parse_valued(t2) {
                    slot.t2_us = sanitize_positive(to_us(v, u));
                }
            }
            if let Some(rb) = node
                .pointer("/oneQubitFidelity/0/fidelity")
                .or_else(|| node.pointer("/RANDOMIZED_BENCHMARKING/fidelity"))
                .or_else(|| node.get("fidelity"))
            {
                if let Some((v, _)) = parse_valued(rb) {
                    slot.error_1q = fidelity_to_error(v);
                }
            }
            if let Some(ro) = node
                .pointer("/oneQubitFidelity")
                .and_then(|arr| arr.as_array())
                .and_then(|arr| {
                    arr.iter().find(|e| {
                        e.get("fidelityType")
                            .and_then(|t| t.as_str())
                            .map(|s| s.eq_ignore_ascii_case("READOUT"))
                            .unwrap_or(false)
                    })
                })
                .and_then(|e| e.get("fidelity"))
                .or_else(|| node.get("readoutFidelity"))
            {
                if let Some((v, _)) = parse_valued(ro) {
                    let e = fidelity_to_error(v).and_then(|x| sanitize_readout(Some(x)));
                    slot.prob_meas1_prep0 = e;
                    slot.prob_meas0_prep1 = e;
                }
            }
        }
    }
    if let Some(two) = std.get("twoQubitProperties").and_then(|v| v.as_object()) {
        for (key, node) in two {
            let (q0, q1) = if let Some(pair) = parse_edge_key(key) {
                pair
            } else if let (Some(c), Some(t)) = (
                node.pointer("/direction/control").and_then(|v| v.as_u64()),
                node.pointer("/direction/target").and_then(|v| v.as_u64()),
            ) {
                (c as u32, t as u32)
            } else {
                continue;
            };
            let err = node
                .pointer("/twoQubitGateFidelity/0/fidelity")
                .or_else(|| node.get("fidelity"))
                .and_then(parse_valued)
                .and_then(|(v, _)| fidelity_to_error(v))
                .unwrap_or(0.0);
            let dur = node
                .get("gateDuration")
                .or_else(|| node.get("duration"))
                .and_then(parse_valued)
                .and_then(|(v, u)| to_ns(v, u));
            edges.push(EdgeCalibration {
                q0,
                q1,
                error_2q: err,
                gate_time_2q_ns: sanitize_positive(dur),
            });
        }
    }
}

fn extract_ionq(raw: &Value, calib: &mut HardwareCalibration, qubits: &mut BTreeMap<u32, QubitCalibration>) {
    let Some(provider) = raw.get("provider") else {
        return;
    };
    let fid = provider.get("fidelity");
    let timing = provider.get("timing");
    let n = raw
        .pointer("/paradigm/qubitCount")
        .and_then(|v| v.as_u64())
        .unwrap_or(0) as u32;

    let e1 = fid
        .and_then(|f| f.pointer("/1Q/mean").or_else(|| f.get("1Q")))
        .and_then(|v| v.as_f64())
        .and_then(fidelity_to_error);
    let e2 = fid
        .and_then(|f| f.pointer("/2Q/mean").or_else(|| f.get("2Q")))
        .and_then(|v| v.as_f64())
        .and_then(fidelity_to_error);
    let spam = fid
        .and_then(|f| f.pointer("/spam/mean").or_else(|| f.get("spam")))
        .and_then(|v| v.as_f64())
        .and_then(|v| fidelity_to_error(v).and_then(|e| sanitize_readout(Some(e))));

    let t1 = timing
        .and_then(|t| t.get("T1"))
        .and_then(|v| v.as_f64())
        .and_then(|v| to_us(v, Some("s")));
    let t2 = timing
        .and_then(|t| t.get("T2"))
        .and_then(|v| v.as_f64())
        .and_then(|v| to_us(v, Some("s")));
    let g1 = timing
        .and_then(|t| t.get("1Q"))
        .and_then(|v| v.as_f64())
        .and_then(|v| to_ns(v, Some("s")));
    let g2 = timing
        .and_then(|t| t.get("2Q"))
        .and_then(|v| v.as_f64())
        .and_then(|v| to_ns(v, Some("s")));

    calib.default_error_1q = e1;
    calib.default_error_2q = e2;
    calib.default_gate_time_1q_ns = sanitize_positive(g1);
    calib.default_gate_time_2q_ns = sanitize_positive(g2);

    if n > 0 {
        for q in 0..n {
            let slot = upsert(qubits, q);
            slot.t1_us = sanitize_positive(t1);
            slot.t2_us = sanitize_positive(t2);
            slot.error_1q = e1;
            slot.gate_time_1q_ns = sanitize_positive(g1);
            slot.prob_meas1_prep0 = spam;
            slot.prob_meas0_prep1 = spam;
        }
    }
}

fn extract_iqm(raw: &Value, qubits: &mut BTreeMap<u32, QubitCalibration>, edges: &mut Vec<EdgeCalibration>) {
    let Some(one) = raw.pointer("/provider/properties/one_qubit").and_then(|v| v.as_object()) else {
        return;
    };
    // IQM often uses 1-based keys "1".."N".
    let keys: Vec<u32> = one.keys().filter_map(|k| k.parse::<u32>().ok()).collect();
    let one_based = !keys.is_empty() && keys.iter().all(|&k| k >= 1);
    for (key, node) in one {
        let Ok(raw_q) = key.parse::<u32>() else {
            continue;
        };
        let q = if one_based { raw_q.saturating_sub(1) } else { raw_q };
        let slot = upsert(qubits, q);
        if let Some(f) = node
            .get("f_1Q_simultaneous_RB")
            .or_else(|| node.get("f_1Q"))
            .and_then(|v| v.as_f64())
        {
            slot.error_1q = fidelity_to_error(f);
        }
        if let Some(f) = node.get("f_RO").and_then(|v| v.as_f64()) {
            let e = fidelity_to_error(f).and_then(|x| sanitize_readout(Some(x)));
            slot.prob_meas1_prep0 = e;
            slot.prob_meas0_prep1 = e;
        }
        if let Some(t1) = node.get("T1").and_then(|v| v.as_f64()) {
            slot.t1_us = sanitize_positive(to_us(t1, Some("s")));
        }
        if let Some(t2) = node.get("T2").and_then(|v| v.as_f64()) {
            slot.t2_us = sanitize_positive(to_us(t2, Some("s")));
        }
    }
    if let Some(two) = raw.pointer("/provider/properties/two_qubit").and_then(|v| v.as_object()) {
        for (key, node) in two {
            let Some((a, b)) = parse_edge_key(key) else {
                continue;
            };
            let (q0, q1) = if one_based {
                (a.saturating_sub(1), b.saturating_sub(1))
            } else {
                (a, b)
            };
            let err = node
                .get("f_CZ")
                .or_else(|| node.get("f_2Q"))
                .and_then(|v| v.as_f64())
                .and_then(fidelity_to_error)
                .unwrap_or(0.0);
            edges.push(EdgeCalibration {
                q0,
                q1,
                error_2q: err,
                gate_time_2q_ns: None,
            });
        }
    }
}

fn extract_rigetti(raw: &Value, qubits: &mut BTreeMap<u32, QubitCalibration>) {
    let Some(one) = raw.pointer("/provider/specs/1Q").and_then(|v| v.as_object()) else {
        return;
    };
    for (key, node) in one {
        let Ok(q) = key.parse::<u32>() else {
            continue;
        };
        let slot = upsert(qubits, q);
        if slot.gate_time_1q_ns.is_none() {
            if let Some(dur) = node
                .get("gate_time")
                .or_else(|| node.get("duration"))
                .and_then(|v| v.as_f64())
            {
                // Rigetti often reports seconds.
                slot.gate_time_1q_ns = sanitize_positive(to_ns(dur, Some("s")));
            }
        }
    }
}

/// Extract normalized calibration from a Braket device properties dump.
pub fn extract_from_braket_json(
    raw: &Value,
    layout: Option<&QubitLayout>,
) -> Result<HardwareCalibration, ClientError> {
    let mut qubits = BTreeMap::new();
    let mut edges = Vec::new();
    let mut calib = HardwareCalibration::default();

    extract_standardized(raw, &mut qubits, &mut edges);
    extract_ionq(raw, &mut calib, &mut qubits);
    extract_iqm(raw, &mut qubits, &mut edges);
    extract_rigetti(raw, &mut qubits);

    calib.qubits = qubits;
    calib.edges = edges;
    Ok(apply_layout(calib, layout))
}
