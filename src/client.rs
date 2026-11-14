//! Black-box job payload builders and public R2 ticket protocol types.
//!
//! Wire shapes match the live orchestrator ticket flow:
//! `POST /api/v1/client/tasks/init` → presigned PUT → `POST /api/v1/client/tasks/commit`
//! → poll the sealed result object (or `GET /v1/tasks/{task_id}`).

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use crate::schema::HardwareCalibration;

/// Public API origin used by the Python client when `base_url` is omitted.
pub const DEFAULT_API_BASE_URL: &str = "https://api.znepro.com";

/// Blind ticket mint.
pub const PATH_CLIENT_TASK_INIT: &str = "/api/v1/client/tasks/init";
/// Queue the task after the sealed object is uploaded.
pub const PATH_CLIENT_TASK_COMMIT: &str = "/api/v1/client/tasks/commit";
/// Direct task intake (lab / mock deployments).
pub const PATH_TASKS: &str = "/v1/tasks";
/// JSON status / result for a task id.
pub const PATH_TASK_RESULT_PREFIX: &str = "/v1/tasks/";

/// One multi-scale hardware sample on the wire (`JobInputPayload.hardware_scales`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HardwareScalePoint {
    #[serde(alias = "noise_scale", alias = "lambda_")]
    pub lambda: f64,
    #[serde(alias = "noisy_expectation")]
    pub expectation: f64,
}

impl HardwareScalePoint {
    pub fn new(lambda: f64, expectation: f64) -> Self {
        Self { lambda, expectation }
    }
}

/// Wire-exact sealed job object uploaded to the presigned R2 PUT URL.
///
/// Field names match the worker `JobInputPayload`. Optional keys are omitted
/// when `None` so uncalibrated tickets stay byte-compatible with existing clients.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ZneproJobRequest {
    pub qasm: String,
    /// Bitstring histogram (qubit 0 = rightmost character), matching the worker.
    pub shots: BTreeMap<String, u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub backend_name: Option<String>,
    /// Multi-scale ZNE samples. Absent ⇒ single-histogram mitigation path.
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        alias = "scales",
        alias = "noise_scales",
        alias = "hardware_measurements"
    )]
    pub hardware_scales: Option<Vec<HardwareScalePoint>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub observable_unit: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub clip_box: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub clique_observables: Option<Vec<String>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub hardware_calibration: Option<HardwareCalibration>,
}

impl ZneproJobRequest {
    /// Primary entrypoint: one hardware execution (bitstring histogram).
    ///
    /// Omits `hardware_scales` so the service applies its single-run mitigation
    /// path. Callers never need to fold circuits or submit multiple tickets.
    ///
    /// `observables` (when provided) maps to wire `clique_observables` for joint
    /// multi-Pauli jobs; the ticket's target observable is chosen at submit time.
    pub fn single(
        qasm: impl Into<String>,
        counts: BTreeMap<String, u64>,
        hardware_calibration: Option<HardwareCalibration>,
    ) -> Self {
        Self::single_with_observables(qasm, counts, None, hardware_calibration)
    }

    /// Primary entrypoint with an optional multi-Pauli clique label list.
    pub fn single_with_observables(
        qasm: impl Into<String>,
        counts: BTreeMap<String, u64>,
        observables: Option<Vec<String>>,
        hardware_calibration: Option<HardwareCalibration>,
    ) -> Self {
        let clique = observables.and_then(|labels| {
            let cleaned: Vec<String> = labels
                .into_iter()
                .map(|s| s.trim().to_owned())
                .filter(|s| !s.is_empty())
                .collect();
            if cleaned.is_empty() {
                None
            } else {
                Some(cleaned)
            }
        });
        Self {
            qasm: qasm.into(),
            shots: counts,
            backend_name: None,
            hardware_scales: None,
            observable_unit: None,
            clip_box: None,
            clique_observables: clique,
            hardware_calibration,
        }
    }

    /// Alias for [`Self::single`] (histogram ↔ single-run wire shape).
    pub fn histogram(
        qasm: impl Into<String>,
        counts: BTreeMap<String, u64>,
        hardware_calibration: Option<HardwareCalibration>,
    ) -> Self {
        Self::single(qasm, counts, hardware_calibration)
    }

    /// Optional offline / benchmark helper: attach pre-measured multi-scale samples.
    ///
    /// When `counts` is `None`, a placeholder single-bit histogram carrying the
    /// total `shots` budget is inserted so the worker schema stays non-empty.
    /// Production clients should prefer [`Self::single`].
    pub fn multi_scale(
        qasm: impl Into<String>,
        noise_scales: &[f64],
        expectations: &[f64],
        shots: u64,
        counts: Option<BTreeMap<String, u64>>,
        hardware_calibration: Option<HardwareCalibration>,
    ) -> Self {
        let scales: Vec<HardwareScalePoint> = noise_scales
            .iter()
            .zip(expectations.iter())
            .map(|(&lambda, &expectation)| HardwareScalePoint::new(lambda, expectation))
            .collect();
        let shots_map = counts.unwrap_or_else(|| {
            let mut map = BTreeMap::new();
            map.insert("0".to_owned(), shots.max(1));
            map
        });
        Self {
            qasm: qasm.into(),
            shots: shots_map,
            backend_name: None,
            hardware_scales: if scales.len() >= 2 { Some(scales) } else { None },
            observable_unit: None,
            clip_box: None,
            clique_observables: None,
            hardware_calibration,
        }
    }

    /// Optional offline helper: multi-term Pauli expectation series.
    /// Keeps the first term's series as `hardware_scales` and lists all labels
    /// under `clique_observables` when more than one term is present.
    pub fn multi_term(
        qasm: impl Into<String>,
        noise_scales: Vec<f64>,
        pauli_expectations: BTreeMap<String, Vec<f64>>,
        shots: usize,
        hardware_calibration: Option<HardwareCalibration>,
    ) -> Self {
        let expectations = pauli_expectations
            .values()
            .next()
            .cloned()
            .unwrap_or_default();
        let clique: Vec<String> = pauli_expectations.keys().cloned().collect();
        let mut req = Self::multi_scale(
            qasm,
            &noise_scales,
            &expectations,
            shots as u64,
            None,
            hardware_calibration,
        );
        if clique.len() >= 2 {
            req.clique_observables = Some(clique);
        }
        req
    }

    /// Serialize to a JSON value suitable for the sealed R2 object.
    pub fn to_json_value(&self) -> serde_json::Value {
        let mut req = self.clone();
        if let Some(calib) = req.hardware_calibration.take() {
            req.hardware_calibration = Some(calib.sanitize());
        }
        serde_json::to_value(&req).unwrap_or(serde_json::Value::Null)
    }

    /// Total shots implied by the bitstring histogram.
    pub fn total_shots(&self) -> u64 {
        self.shots.values().copied().sum()
    }
}

/// `POST /api/v1/client/tasks/init` body.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct R2TicketInitRequest {
    pub target_observable: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub hardware_backend: Option<String>,
}

/// `POST /api/v1/client/tasks/init` response.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct R2TicketInitResponse {
    pub task_id: String,
    pub job_id: String,
    pub r2_key: String,
    pub upload_presigned_url: String,
    pub encryption_key_hex: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub report_presigned_url: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub output_presigned_url: Option<String>,
}

/// `POST /api/v1/client/tasks/commit` body.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct R2TicketCommitRequest {
    pub task_id: String,
}

/// `POST /api/v1/client/tasks/commit` response.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct R2TicketCommitResponse {
    pub status: String,
}

/// Client-visible task status / result document (`GET /v1/tasks/{id}`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct R2JobStatusResponse {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub kind: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub status: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub task_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub get_url: Option<String>,
    #[serde(default)]
    pub metrics: Option<serde_json::Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub mitigated_expectation: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub unmitigated_expectation: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    /// Worker build identifier, when the receipt includes one.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub engine_version: Option<String>,
    /// True on the calibrated arm and false on the zero-telemetry arm.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub server_calibration_used: Option<bool>,
    /// Canonical hash of the calibration card the service applied.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub server_calibration_sha256: Option<String>,
    /// Client-facing alias of `server_calibration_used`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub calibration_applied: Option<bool>,
    /// Client-facing alias of `server_calibration_sha256`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub calibration_sha256: Option<String>,
    /// Additional receipt keys, preserved without a nested wrapper.
    #[serde(flatten)]
    pub extra: BTreeMap<String, serde_json::Value>,
}

#[cfg(test)]
mod receipt_tests {
    use super::R2JobStatusResponse;

    #[test]
    fn status_keeps_calibration_attestation_and_unknown_fields() {
        let raw = r#"{
            "status": "COMPLETED",
            "task_id": "task-1",
            "server_calibration_used": true,
            "server_calibration_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "calibration_applied": false,
            "calibration_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "server_version": "1.0.0",
            "engine_version": "2026.11.13",
            "metrics": {"mitigated_expectation": 0.9}
        }"#;
        let parsed: R2JobStatusResponse = serde_json::from_str(raw).expect("receipt");
        assert_eq!(parsed.status.as_deref(), Some("COMPLETED"));
        assert_eq!(parsed.task_id.as_deref(), Some("task-1"));
        assert_eq!(parsed.server_calibration_used, Some(true));
        assert_eq!(
            parsed.server_calibration_sha256.as_deref(),
            Some("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        );
        assert_eq!(parsed.calibration_applied, Some(false));
        assert_eq!(
            parsed.calibration_sha256.as_deref(),
            Some("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
        );
        assert_eq!(
            parsed.extra.get("server_version").and_then(|value| value.as_str()),
            Some("1.0.0")
        );
        let back = serde_json::to_value(&parsed).expect("serialize");
        assert_eq!(back["server_calibration_used"], true);
        assert_eq!(back["calibration_applied"], false);
        assert_eq!(back["calibration_sha256"], "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb");
        assert_eq!(back["server_version"], "1.0.0");
        assert_eq!(parsed.engine_version.as_deref(), Some("2026.11.13"));
        assert_eq!(back["engine_version"], "2026.11.13");
        assert!(back.get("extra").is_none());
    }
}
