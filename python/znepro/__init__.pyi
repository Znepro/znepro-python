from collections.abc import Callable, Mapping, Sequence
from typing import Any

__version__: str
DEFAULT_BASE_URL: str
USER_AGENT: str

def seal_envelope(
    plaintext_bytes: bytes,
    key_hex_or_b64: str | bytes,
    nonce: bytes | None = None,
) -> bytes: ...
def open_envelope(blob: bytes, key_hex_or_b64: str | bytes) -> bytes: ...
def canonical_job_bytes(payload_json: str) -> bytes: ...
PATH_CLIENT_TASK_INIT: str
PATH_CLIENT_TASK_COMMIT: str
PATH_TASKS: str

class HardwareCalibration:
    def to_json(self, pretty: bool = False) -> str: ...
    def remap(
        self,
        *,
        logical_to_physical: Sequence[int] | None = None,
        physical_to_logical: Mapping[int, int] | None = None,
    ) -> HardwareCalibration: ...
    def qubit_count(self) -> int: ...
    def edge_count(self) -> int: ...
    def __repr__(self) -> str: ...

def extract_from_qiskit(source: Any, layout: Any = None) -> HardwareCalibration: ...
def extract_from_braket(source: Any, layout: Any = None) -> HardwareCalibration: ...
def extract_from_cirq(
    source: Any,
    qubit_order: Sequence[str] | None = None,
    layout: Any = None,
) -> HardwareCalibration: ...
def extract_from_pytket(source: Any, layout: Any = None) -> HardwareCalibration: ...
def build_neutral_atom_calibration(
    num_qubits: int,
    *,
    cz_fidelity: float = 0.995,
    single_qubit_fidelity: float = 0.9992,
    t1_s: float = 4.0,
    t2_ms: float = 15.0,
    cz_duration_ns: float = 400.0,
    single_qubit_duration_ns: float = 1000.0,
    readout_error: float = 0.008,
    atom_loss_prob: float = 0.004,
) -> HardwareCalibration: ...
def auto_extract_calibration(source: Any, layout: Any = None) -> HardwareCalibration: ...

Transport = Callable[[str, str, bytes | None, dict[str, str], float], tuple[int, bytes]]

class ZNEProClient:
    base_url: str
    api_key: str | None
    timeout_s: float
    transport: Transport
    def __init__(
        self,
        base_url: str = ...,
        api_key: str | None = None,
        timeout_s: float = 120.0,
        transport: Transport | None = None,
    ) -> None: ...
    @staticmethod
    def build_job_json(
        qasm: str,
        counts: Mapping[str, int],
        *,
        observable: str | None = None,
        observables: Sequence[str] | None = None,
        shots: int | None = None,
        calibration: HardwareCalibration | None = None,
        layout: Any = None,
        clip_box: bool | None = None,
        backend_name: str | None = None,
    ) -> str: ...
    @staticmethod
    def build_histogram_job_json(
        qasm: str,
        counts: Mapping[str, int],
        *,
        calibration: HardwareCalibration | None = None,
        layout: Any = None,
        clip_box: bool | None = None,
        backend_name: str | None = None,
        observable: str | None = None,
        observables: Sequence[str] | None = None,
        shots: int | None = None,
    ) -> str: ...
    @staticmethod
    def build_multi_scale_job_json(
        qasm: str,
        noise_scales: Sequence[float],
        shots: int,
        *,
        expectations: Sequence[float] | None = None,
        pauli_expectations: Mapping[str, Sequence[float]] | None = None,
        counts: Mapping[str, int] | None = None,
        calibration: HardwareCalibration | None = None,
        layout: Any = None,
    ) -> str: ...
    def create_ticket(
        self,
        target_observable: str,
        *,
        hardware_backend: str | None = None,
    ) -> dict[str, Any]: ...
    def upload_payload(
        self,
        upload_presigned_url: str,
        payload_json: str,
        encryption_key_hex: str | None = None,
    ) -> int: ...
    def commit_ticket(self, task_id: str) -> dict[str, Any]: ...
    def poll_ticket(
        self,
        *,
        task_id: str,
        output_presigned_url: str | None,
        encryption_key_hex: str | None = None,
        poll_interval_s: float = 1.0,
        max_wait_s: float = 120.0,
    ) -> dict[str, Any]: ...
    def submit_and_wait(
        self,
        payload_json: str,
        *,
        observable: str,
        hardware_backend: str | None = None,
        timeout_s: float | None = None,
        poll_interval_s: float = 1.0,
    ) -> dict[str, Any]: ...
    def submit_job(
        self,
        qasm: str,
        counts: Mapping[str, int],
        *,
        observable: str,
        observables: Sequence[str] | None = None,
        shots: int | None = None,
        calibration: HardwareCalibration | None = None,
        layout: Any = None,
        hardware_backend: str | None = None,
        timeout_s: float | None = None,
        poll_interval_s: float = 1.0,
        clip_box: bool | None = None,
        backend_name: str | None = None,
    ) -> dict[str, Any]: ...
    def mitigate_json(
        self,
        payload: str,
        *,
        observable: str = "Z",
        hardware_backend: str | None = None,
        timeout_s: float | None = None,
        poll_interval_s: float = 1.0,
    ) -> str: ...
    def mitigate(
        self,
        qasm: str,
        counts: Mapping[str, int],
        *,
        observable: str = "Z",
        observables: Sequence[str] | None = None,
        shots: int | None = None,
        calibration: HardwareCalibration | None = None,
        layout: Any = None,
        hardware_backend: str | None = None,
        timeout_s: float | None = None,
        poll_interval_s: float = 1.0,
    ) -> Any: ...
