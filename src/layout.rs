//! Physical ↔ logical qubit layout helpers for remapping device telemetry.

use std::collections::BTreeMap;

/// Mapping between physical device qubit indices and contiguous logical indices.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum QubitLayout {
    /// Transpiled layout list: `layout[logical] = physical`.
    /// Example: `[14, 15, 22]` ⇒ `14→0, 15→1, 22→2`.
    LogicalToPhysical(Vec<u32>),
    /// Explicit physical → logical map.
    PhysicalToLogical(BTreeMap<u32, u32>),
}

impl QubitLayout {
    /// Build the physical → logical map used by [`crate::HardwareCalibration::remap_qubits`].
    pub fn physical_to_logical(&self) -> BTreeMap<u32, u32> {
        match self {
            Self::LogicalToPhysical(layout) => layout
                .iter()
                .enumerate()
                .map(|(logical, &physical)| (physical, logical as u32))
                .collect(),
            Self::PhysicalToLogical(map) => map.clone(),
        }
    }
}
