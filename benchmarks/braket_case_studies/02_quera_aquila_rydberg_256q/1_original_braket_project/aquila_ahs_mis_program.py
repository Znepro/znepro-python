"""QuEra Aquila analog program in the form a Braket user already stores.

256 rubidium-87 sites on a square lattice, a global Rabi drive, and a
detuning sweep. The numbers match the case-study constants: C6, lattice
spacing, and the saved Z2-order measurements. This file does not call ZNEPro.
"""

from __future__ import annotations

import json
from pathlib import Path

C6_RAD_M6_PER_S = 5.42e-24
LATTICE_SPACING_M = 6.7e-6
ROWS = 16
COLS = 16
N_ATOMS = ROWS * COLS
DURATION_S = 4.0e-6
OMEGA_MAX_RAD_PER_S = 1.57e7
DELTA_FINAL_RAD_PER_S = 2.0e7
IDEAL_Z2_ORDER = 0.960
RESULTS_PATH = Path(__file__).with_name("raw_aquila_qpu_results.json")


def atom_sites() -> list[list[float]]:
    spacing = LATTICE_SPACING_M
    return [
        [column * spacing, row * spacing]
        for row in range(ROWS)
        for column in range(COLS)
    ]


def analog_program() -> dict:
    """Fields a user would put on ``AnalogHamiltonianSimulation``."""
    times = [0.0, 0.25 * DURATION_S, 0.75 * DURATION_S, DURATION_S]
    omega = [0.0, OMEGA_MAX_RAD_PER_S, OMEGA_MAX_RAD_PER_S, 0.0]
    delta = [-DELTA_FINAL_RAD_PER_S, -DELTA_FINAL_RAD_PER_S, DELTA_FINAL_RAD_PER_S, DELTA_FINAL_RAD_PER_S]
    phase = [0.0, 0.0, 0.0, 0.0]
    return {
        "setup": {
            "ahs_register": {
                "sites": atom_sites(),
                "filling": [1] * N_ATOMS,
            }
        },
        "hamiltonian": {
            "drivingFields": [
                {
                    "amplitude": {"pattern": "uniform", "time_s": times, "value_rad_per_s": omega},
                    "detuning": {"pattern": "uniform", "time_s": times, "value_rad_per_s": delta},
                    "phase": {"pattern": "uniform", "time_s": times, "value_rad": phase},
                }
            ],
            "shiftingFields": [],
        },
    }


def load_hardware_results() -> dict:
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
