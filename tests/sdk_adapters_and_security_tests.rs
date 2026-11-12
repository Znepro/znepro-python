//! Open-source-safe adapter and security tests for `znepro-sdk`.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::json;
use znepro_sdk::{
    auto_extract_calibration_json, build_neutral_atom_calibration, extract_from_braket_json,
    extract_from_cirq_json, extract_from_pytket_json, extract_from_qiskit_json, NeutralAtomConfig,
    QubitLayout, ZneproJobRequest,
};

fn crate_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

#[test]
fn test_qiskit_skips_virtual_rz_scrubs_nan_and_remaps_layout() {
    let raw = json!({
        "backend_name": "fake_backend",
        "qubits": [[
            {"name": "T1", "unit": "us", "value": 80.0},
            {"name": "T2", "unit": "us", "value": 60.0},
            {"name": "readout_error", "value": 0.02},
            {"name": "T1", "unit": "us", "value": "nan"}
        ], [
            {"name": "T1", "unit": "s", "value": 1.0e-4},
            {"name": "prob_meas1_prep0", "value": 0.01},
            {"name": "prob_meas0_prep1", "value": 0.03}
        ], [
            {"name": "T1", "unit": "us", "value": null},
            {"name": "T2", "unit": "us", "value": -5.0}
        ]],
        "gates": [
            {"gate": "rz", "qubits": [0], "parameters": [{"name": "gate_error", "value": 0.5}]},
            {"gate": "sx", "qubits": [0], "parameters": [
                {"name": "gate_error", "value": 0.001},
                {"name": "gate_length", "unit": "ns", "value": 35.0}
            ]},
            {"gate": "cx", "qubits": [0, 1], "parameters": [
                {"name": "gate_error", "value": 0.01},
                {"name": "gate_length", "unit": "ns", "value": 300.0}
            ]},
            {"gate": "barrier", "qubits": [0, 1], "parameters": []}
        ]
    });
    let layout = QubitLayout::LogicalToPhysical(vec![0, 1]);
    let calib = extract_from_qiskit_json(&raw, Some(&layout)).expect("qiskit");
    assert!(calib.qubits.get(&0).unwrap().error_1q.unwrap() < 0.01);
    assert!((calib.qubits.get(&0).unwrap().t1_us.unwrap() - 80.0).abs() < 1e-12);
    assert!(calib.qubits.get(&1).unwrap().prob_meas0_prep1.unwrap() > 0.0);
    assert_eq!(calib.edges.len(), 1);
    assert_eq!(calib.edges[0].q0.min(calib.edges[0].q1), 0);
    // Virtual rz must not create a 0.5 error entry on qubit 0 alone beyond sx.
    assert!(calib.qubits.get(&0).unwrap().error_1q.unwrap() < 0.1);
    let v = calib.to_json_value();
    let hidden = format!("{}{}{}", "enable_", "light_", "cone");
    assert!(v.get(hidden.as_str()).is_none());
}

#[test]
fn test_qiskit_operations_map_converts_seconds_and_keeps_readout() {
    let raw = json!({
        "qubit_properties": [
            {"t1": 50e-6, "t2": 40e-6, "prob_meas1_prep0": 0.01, "prob_meas0_prep1": 0.03},
            {"t1": 60e-6, "t2": 45e-6}
        ],
        "operations": {
            "rz": [{"qubits": [0], "error": 0.5, "duration": 0.0}],
            "sx": [{"qubits": [0], "error": 0.0012, "duration": 35e-9}],
            "x": [{"qubits": [1], "error": 0.0011, "duration": 35e-9}],
            "cx": [{"qubits": [0, 1], "error": 0.008, "duration": 300e-9}],
            "ecr": [{"qubits": [1], "error": 0.2, "duration": 280e-9}]
        },
        "readout_error": [null, 0.02]
    });
    let calib = extract_from_qiskit_json(&raw, None).expect("operations");
    let q0 = calib.qubits.get(&0).unwrap();
    let q1 = calib.qubits.get(&1).unwrap();
    assert!((q0.t1_us.unwrap() - 50.0).abs() < 1e-6);
    assert!((q0.error_1q.unwrap() - 0.0012).abs() < 1e-12);
    assert!((q0.gate_time_1q_ns.unwrap() - 35.0).abs() < 1e-4);
    assert!((q0.prob_meas1_prep0.unwrap() - 0.01).abs() < 1e-12);
    assert!((q0.prob_meas0_prep1.unwrap() - 0.03).abs() < 1e-12);
    assert!((q1.error_1q.unwrap() - 0.0011).abs() < 1e-12);
    assert!((q1.prob_meas1_prep0.unwrap() - 0.02).abs() < 1e-12);
    assert_eq!(calib.edges.len(), 1);
    assert!((calib.edges[0].error_2q - 0.008).abs() < 1e-12);
    assert!((calib.edges[0].gate_time_2q_ns.unwrap() - 300.0).abs() < 1e-4);
}

#[test]
fn test_braket_standardized_ionq_and_iqm_1based_normalization() {
    let std = json!({
        "standardized": {
            "oneQubitProperties": {
                "0": {
                    "T1": {"value": 50.0, "unit": "us"},
                    "T2": {"value": 40.0, "unit": "us"},
                    "oneQubitFidelity": [
                        {"fidelityType": "RANDOMIZED_BENCHMARKING", "fidelity": 0.999},
                        {"fidelityType": "READOUT", "fidelity": 0.98}
                    ]
                }
            },
            "twoQubitProperties": {
                "0-1": {
                    "twoQubitGateFidelity": [{"fidelity": 0.99}],
                    "gateDuration": {"value": 200.0, "unit": "ns"}
                }
            }
        }
    });
    let calib = extract_from_braket_json(&std, None).expect("std");
    assert!((calib.qubits[&0].error_1q.unwrap() - 0.001).abs() < 1e-12);
    assert!((calib.edges[0].error_2q - 0.01).abs() < 1e-12);

    let ionq = json!({
        "paradigm": {"qubitCount": 2},
        "provider": {
            "fidelity": {"1Q": {"mean": 0.999}, "2Q": {"mean": 0.98}, "spam": {"mean": 0.995}},
            "timing": {"T1": 10.0, "T2": 1.0, "1Q": 1.0e-5, "2Q": 2.0e-4}
        }
    });
    let calib = extract_from_braket_json(&ionq, None).expect("ionq");
    assert_eq!(calib.qubits.len(), 2);
    assert!(calib.default_error_2q.unwrap() > 0.0);

    let iqm = json!({
        "provider": {
            "properties": {
                "one_qubit": {
                    "1": {"f_1Q": 0.999, "f_RO": 0.99, "T1": 5.0e-5, "T2": 4.0e-5},
                    "2": {"f_1Q_simultaneous_RB": 0.998, "f_RO": 0.985, "T1": 4.0e-5, "T2": 3.0e-5}
                },
                "two_qubit": {
                    "1-2": {"f_CZ": 0.99}
                }
            }
        }
    });
    let calib = extract_from_braket_json(&iqm, None).expect("iqm");
    assert!(calib.qubits.contains_key(&0));
    assert!(calib.qubits.contains_key(&1));
    assert!(!calib.qubits.contains_key(&2));
    assert_eq!(calib.edges[0].q0.min(calib.edges[0].q1), 0);
}

#[test]
fn test_cirq_grid_qubits_and_asymmetric_readout() {
    let raw = json!({
        "single_qubit_idle_t1_micros": {"(0, 0)": 40.0, "(0, 1)": 35.0},
        "single_qubit_idle_t2_micros": {"(0, 0)": 30.0, "(0, 1)": 25.0},
        "single_qubit_rb_pauli_error_per_gate": {"(0, 0)": 0.001, "(0, 1)": 0.002},
        "single_qubit_readout_p00_error": {"(0, 0)": 0.01, "(0, 1)": 0.02},
        "single_qubit_readout_p11_error": {"(0, 0)": 0.03, "(0, 1)": 0.04},
        "two_qubit_cz_pauli_error": {"0_1": 0.015}
    });
    let order = vec!["(0, 0)".to_string(), "(0, 1)".to_string()];
    let calib = znepro_sdk::extract_from_cirq_json_with_order(&raw, None, Some(&order))
        .unwrap_or_else(|_| extract_from_cirq_json(&raw, None).expect("cirq"));
    assert_eq!(calib.qubits.len(), 2);
    assert!((calib.qubits[&0].prob_meas1_prep0.unwrap() - 0.01).abs() < 1e-12);
    assert!((calib.qubits[&0].prob_meas0_prep1.unwrap() - 0.03).abs() < 1e-12);
    assert!(!calib.edges.is_empty());
}

#[test]
fn test_pytket_confusion_matrix_and_qccd_defaults() {
    let raw = json!({
        "nodes": ["q0", "q1"],
        "averaged_node_gate_errors": {"q0": 0.001, "q1": 0.002},
        "averaged_edge_gate_errors": {"q0_q1": 0.02},
        "all_readout_errors": [
            [[0.99, 0.01], [0.02, 0.98]],
            [[0.97, 0.03], [0.04, 0.96]]
        ],
        "misc": {
            "t1_s": 2.0,
            "t2_s": 0.5,
            "fidelity_2q_error": 0.01
        }
    });
    let calib = extract_from_pytket_json(&raw, None).expect("pytket");
    assert!((calib.qubits[&0].prob_meas1_prep0.unwrap() - 0.01).abs() < 1e-12);
    assert!((calib.qubits[&0].prob_meas0_prep1.unwrap() - 0.02).abs() < 1e-12);
    assert!((calib.qubits[&0].t1_us.unwrap() - 2.0e6).abs() < 1.0);
    assert!((calib.default_gate_time_1q_ns.unwrap() - 25_000.0).abs() < 1e-12);
    assert!((calib.default_gate_time_2q_ns.unwrap() - 250_000.0).abs() < 1e-12);
}

#[test]
fn test_neutral_atom_builder_folds_atom_loss() {
    let cfg = NeutralAtomConfig {
        num_qubits: 3,
        coupling_edges: vec![(0, 1), (1, 2)],
        ..NeutralAtomConfig::default()
    };
    let calib = build_neutral_atom_calibration(&cfg, None).expect("na");
    let expected = (0.008 + 0.004_f64).clamp(0.0, 0.5);
    assert!((calib.qubits[&0].prob_meas0_prep1.unwrap() - expected).abs() < 1e-15);
    assert!((calib.qubits[&0].prob_meas1_prep0.unwrap() - 0.008).abs() < 1e-15);
    assert_eq!(calib.edges.len(), 2);
}

#[test]
fn test_auto_detect_and_uncalibrated_payload_omits_calibration_key() {
    let qiskit = json!({
        "backend_name": "x",
        "qubits": [[{"name": "T1", "unit": "us", "value": 10.0}]],
        "gates": []
    });
    let _ = auto_extract_calibration_json(&qiskit, None).expect("auto-qiskit");

    let mut bare_counts = BTreeMap::new();
    bare_counts.insert("0".to_owned(), 3900);
    bare_counts.insert("1".to_owned(), 100);
    let req = ZneproJobRequest::single(
        "OPENQASM 2.0;\nqreg q[1];\n",
        bare_counts,
        None,
    );
    let value = req.to_json_value();
    assert!(
        value.get("hardware_calibration").is_none(),
        "uncalibrated payload must omit hardware_calibration"
    );
    assert!(
        value.get("hardware_scales").is_none(),
        "primary single-run builder must omit hardware_scales"
    );
    assert!(value.get("shots").is_some(), "worker schema requires shots");
    assert_eq!(req.total_shots(), 4000);

    let mut cal_counts = BTreeMap::new();
    cal_counts.insert("0".to_owned(), 1000);
    let with = ZneproJobRequest::single(
        "OPENQASM 2.0;\nqreg q[1];\n",
        cal_counts,
        Some(build_neutral_atom_calibration(
            &NeutralAtomConfig {
                num_qubits: 1,
                ..NeutralAtomConfig::default()
            },
            None,
        )
        .unwrap()),
    );
    let value = with.to_json_value();
    assert!(value.get("hardware_calibration").is_some());
    assert!(value.get("hardware_scales").is_none());
    let hidden = format!("{}{}{}", "enable_", "light_", "cone");
    let pointer = format!("/hardware_calibration/{hidden}");
    assert!(value.pointer(&pointer).is_none());

    // Optional offline multi-scale helper still emits hardware_scales.
    let multi = ZneproJobRequest::multi_scale(
        "OPENQASM 2.0;\nqreg q[1];\n",
        &[1.0, 1.5],
        &[0.9, 0.8],
        4000,
        None,
        None,
    );
    assert!(multi.to_json_value().get("hardware_scales").is_some());
}

#[test]
fn test_zero_proprietary_ip_leakage() {
    // Build each forbidden token from fragments so this test file itself stays clean.
    let forbidden = {
        let mut words = Vec::new();
        words.push(format!("{}{}", "t", "df"));
        words.push(format!("{}{}", "god_", "eye"));
        words.push(format!("{}{}", "gods_", "eye"));
        words.push(format!("{}{}", "ke", "rr"));
        words.push(format!("{}{}", "22", "4"));
        words.push(format!("{}{}", "14.", "93"));
        words.push(format!("{}{}", "ata", "nh"));
        words.push(format!("{}{}", "arcta", "nh"));
        words.push(format!("{}{}", "dyk", "stra"));
        words.push(format!("{}{}", "poly", "tope"));
        words.push(format!("{}{}", "heisen", "berg"));
        words.push(format!("{}{}", "light_", "cone"));
        words.push(format!("{}{}", "causal_", "cone"));
        words.push(format!("{}{}", "pi_", "gate"));
        words.push(format!("{}{}", "pi_", "decoherence"));
        words.push(format!("{}{}", "tape_", "tension"));
        words.push(format!("{}{}", "deco", "nv"));
        words.push(format!("{}{}", "break_", "point"));
        words.push(format!("{}{}", "rerun", "4"));
        words.push(format!("/v1/{}", "mitigate"));
        words
    };
    let core_pkg = format!("{}{}{}", "t", "df", "-gpt-core");
    let core_path_a = format!("path = \"../{}", format!("{}{}", "t", "df"));
    let core_path_b = format!("path=\"../{}", format!("{}{}", "t", "df"));
    let hidden_flag = format!("{}{}{}", "enable_", "light_", "cone");

    let root = crate_root();
    let cargo = fs::read_to_string(root.join("Cargo.toml")).expect("Cargo.toml");
    let cargo_l = cargo.to_ascii_lowercase();
    assert!(
        !cargo_l.contains(&core_pkg),
        "sdk Cargo.toml must not depend on the private core package"
    );
    assert!(
        !cargo.contains(&core_path_a) && !cargo.contains(&core_path_b),
        "sdk Cargo.toml must not path-depend on internal crates"
    );
    for line in cargo.lines() {
        let lower = line.to_ascii_lowercase();
        if lower.contains("path") {
            let bad = [
                format!("{}{}", "t", "df-gpt"),
                "znepro_orchestrator".to_string(),
                format!("{}{}", "t", "df_core"),
                format!("{}{}", "t", "df_spot"),
            ];
            assert!(
                bad.iter().all(|b| !lower.contains(b)),
                "forbidden path dependency: {line}"
            );
        }
    }

    // Scan repo-relative paths from git ls-files, then the bytes of text files.
    // The host directory prefix is not part of either search text.
    let tracked = tracked_repo_paths(&root);
    assert!(!tracked.is_empty(), "git ls-files returned no paths");
    for rel in &tracked {
        let rel_l = rel.to_ascii_lowercase();
        for word in &forbidden {
            assert!(
                !rel_l.contains(&word.to_ascii_lowercase()),
                "blocked token found in repo-relative path {rel}"
            );
        }
        assert!(
            !rel_l.contains(&hidden_flag.to_ascii_lowercase()),
            "public tree must omit hidden solver flags in path {rel}"
        );
        if !tracked_text_file(rel) {
            continue;
        }
        let text = fs::read_to_string(root.join(rel)).unwrap_or_default();
        let lower = text.to_ascii_lowercase();
        for word in &forbidden {
            assert!(
                !lower.contains(&word.to_ascii_lowercase()),
                "blocked token found in {rel}"
            );
        }
        assert!(
            !lower.contains(&hidden_flag.to_ascii_lowercase()),
            "public schema must omit hidden solver flags in {rel}"
        );
    }

    // Manifest isolation: no internal crates via pyproject either.
    if let Ok(pyproject_text) = fs::read_to_string(root.join("pyproject.toml")) {
        let lower = pyproject_text.to_ascii_lowercase();
        assert!(!lower.contains(&core_pkg));
        assert!(!lower.contains("znepro_orchestrator"));
        for word in &forbidden {
            assert!(
                !lower.contains(&word.to_ascii_lowercase()),
                "blocked token in pyproject.toml"
            );
        }
    }

    let sample = build_neutral_atom_calibration(
        &NeutralAtomConfig {
            num_qubits: 2,
            coupling_edges: vec![(0, 1)],
            ..NeutralAtomConfig::default()
        },
        None,
    )
    .unwrap()
    .to_json_value();
    assert!(sample.get(hidden_flag.as_str()).is_none());
}

fn tracked_repo_paths(root: &Path) -> Vec<String> {
    let output = std::process::Command::new("git")
        .args(["ls-files", "-z"])
        .current_dir(root)
        .output()
        .expect("git ls-files");
    assert!(
        output.status.success(),
        "git ls-files failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    output
        .stdout
        .split(|byte| *byte == 0)
        .filter(|raw| !raw.is_empty())
        .map(|raw| String::from_utf8_lossy(raw).into_owned())
        .collect()
}

fn tracked_text_file(rel: &str) -> bool {
    let name = rel.rsplit('/').next().unwrap_or(rel);
    if matches!(name, ".gitignore" | "LICENSE" | "py.typed") {
        return true;
    }
    let ext = match name.rsplit_once('.') {
        Some((_, ext)) => ext,
        None => return false,
    };
    matches!(
        ext,
        "py" | "pyi" | "rs" | "md" | "toml" | "yml" | "yaml" | "json" | "txt" | "example" | "zk"
            | "typed"
    )
}

#[test]
fn test_layout_remap_filters_unmapped_edges() {
    use znepro_sdk::{EdgeCalibration, HardwareCalibration, QubitCalibration};
    let mut qubits = BTreeMap::new();
    qubits.insert(
        14,
        QubitCalibration {
            error_1q: Some(0.001),
            ..Default::default()
        },
    );
    qubits.insert(
        15,
        QubitCalibration {
            error_1q: Some(0.002),
            ..Default::default()
        },
    );
    qubits.insert(
        99,
        QubitCalibration {
            error_1q: Some(0.9),
            ..Default::default()
        },
    );
    let calib = HardwareCalibration {
        qubits,
        edges: vec![
            EdgeCalibration {
                q0: 14,
                q1: 15,
                error_2q: 0.01,
                gate_time_2q_ns: Some(200.0),
            },
            EdgeCalibration {
                q0: 14,
                q1: 99,
                error_2q: 0.5,
                gate_time_2q_ns: None,
            },
        ],
        ..Default::default()
    };
    let remapped = calib.remap_qubits(&QubitLayout::LogicalToPhysical(vec![14, 15]).physical_to_logical());
    assert_eq!(remapped.qubits.len(), 2);
    assert!(remapped.qubits.contains_key(&0));
    assert!(remapped.qubits.contains_key(&1));
    assert_eq!(remapped.edges.len(), 1);
}
