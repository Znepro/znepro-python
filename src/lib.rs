//! Public ZNEPro client helpers: hardware telemetry DTOs, vendor extractors,
//! and black-box job payload builders.
//!
//! The primary wire shape is a **single hardware execution** (OpenQASM +
//! bitstring histogram in `shots`, optional `hardware_calibration`). Omitting
//! `hardware_scales` selects the service's single-run mitigation path. This
//! crate has no solver dependencies.

#![cfg_attr(not(feature = "python"), forbid(unsafe_code))]

pub mod adapters;
pub mod client;
pub mod layout;
pub mod schema;

#[cfg(feature = "python")]
pub mod python;

pub use adapters::{
    auto_extract_calibration_json, build_neutral_atom_calibration, extract_from_braket_json,
    extract_from_cirq_json, extract_from_cirq_json_with_order, extract_from_pytket_json,
    extract_from_qiskit_json, NeutralAtomConfig,
};
pub use client::{
    HardwareScalePoint, R2JobStatusResponse, R2TicketCommitRequest, R2TicketCommitResponse,
    R2TicketInitRequest, R2TicketInitResponse, ZneproJobRequest, DEFAULT_API_BASE_URL,
    PATH_CLIENT_TASK_COMMIT, PATH_CLIENT_TASK_INIT, PATH_TASKS, PATH_TASK_RESULT_PREFIX,
};
pub use layout::QubitLayout;
pub use schema::{ClientError, EdgeCalibration, HardwareCalibration, QubitCalibration};
