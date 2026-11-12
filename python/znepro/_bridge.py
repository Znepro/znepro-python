"""Live-object to JSON serializers for the Rust vendor extractors.

This module performs no calibration math. It only reshapes Python SDK objects,
dicts, or JSON strings into the exact JSON documents expected by the Rust
`extract_from_*_json` parsers.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any


def _as_mapping(source: Any) -> Mapping[str, Any] | None:
    if isinstance(source, Mapping):
        return source
    for attr in ("model_dump", "dict"):
        fn = getattr(source, attr, None)
        if callable(fn):
            try:
                dumped = fn()
            except TypeError:
                dumped = fn(exclude_none=False) if attr == "model_dump" else fn()
            if isinstance(dumped, Mapping):
                return dumped
    raw = getattr(source, "json", None)
    if callable(raw):
        try:
            parsed = json.loads(raw())
        except Exception:
            parsed = None
        if isinstance(parsed, Mapping):
            return parsed
    return None


def _loads_if_str(source: Any) -> Any:
    if isinstance(source, str):
        return json.loads(source)
    return source


def _json_dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), allow_nan=False)


_NON_GATE_OPS = {"measure", "reset", "delay", "barrier"}


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or abs(number) == float("inf"):
        return None
    return number


def _qubit_indexes(qargs: Any) -> list[int] | None:
    try:
        indexes: list[int] = []
        for qubit in qargs or ():
            if isinstance(qubit, bool):
                return None
            if isinstance(qubit, int):
                indexes.append(qubit)
                continue
            index = getattr(qubit, "index", None)
            indexes.append(int(index if isinstance(index, int) else qubit))
        return indexes
    except (TypeError, ValueError):
        return None


def _props_error_duration(props: Any) -> tuple[float | None, float | None]:
    if props is None:
        return None, None
    error = getattr(props, "error", None)
    duration = getattr(props, "duration", None)
    if isinstance(props, Mapping):
        error = props.get("error", error)
        duration = props.get("duration", duration)
    return _finite_float(error), _finite_float(duration)


def _iter_target_instructions(target: Any):
    """Yield ``(op_name, qargs_map)`` for a real Target or a 3-tuple stand-in."""
    items = getattr(target, "items", None)
    if callable(items):
        try:
            entries = list(items())
        except Exception:
            entries = []
        for entry in entries:
            if not isinstance(entry, tuple) or len(entry) < 2:
                continue
            name = str(entry[0])
            if len(entry) == 2 and isinstance(entry[1], Mapping):
                yield name, entry[1]
                continue
            if len(entry) >= 3:
                qargs = entry[1]
                key = qargs if isinstance(qargs, tuple) else tuple(qargs or ())
                yield name, {key: entry[2]}
        return
    names = getattr(target, "operation_names", None)
    if names is None:
        return
    for name in list(names):
        try:
            qargs_map = target[name]
        except Exception:
            continue
        if isinstance(qargs_map, Mapping):
            yield str(name), qargs_map


def _read_named_float(row: Any, key: str) -> float | None:
    if isinstance(row, Mapping):
        return _finite_float(row.get(key))
    return _finite_float(getattr(row, key, None))


def _qubit_property_row(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    item: dict[str, Any] = {}
    for key in ("t1", "t2", "prob_meas1_prep0", "prob_meas0_prep1", "readout_error"):
        value = _read_named_float(row, key)
        if value is not None:
            item[key] = value
    return item


def _qubit_property_rows(source: Any, target: Any) -> list[Any]:
    num = getattr(target, "num_qubits", None) if target is not None else None
    accessor = getattr(source, "qubit_properties", None)
    if callable(accessor) and isinstance(num, int) and num > 0:
        try:
            sample = accessor(0)
        except TypeError:
            sample = None
        except Exception:
            sample = None
        if sample is not None and not isinstance(sample, (list, tuple, Mapping)):
            rows: list[Any] = []
            for index in range(num):
                try:
                    rows.append(accessor(index))
                except Exception:
                    rows.append(None)
            return rows
    props = getattr(target, "qubit_properties", None) if target is not None else None
    if props is None and not callable(accessor):
        props = accessor
    if callable(props):
        try:
            props = props()
        except Exception:
            props = None
    if props is None:
        return []
    try:
        return list(props)
    except TypeError:
        return []


def qiskit_object_to_json(source: Any) -> str:
    """Serialize Qiskit BackendV2 / Target / BackendProperties-like objects."""
    source = _loads_if_str(source)
    if isinstance(source, str):
        return source
    as_map = _as_mapping(source)
    if as_map is not None and (
        "backend_name" in as_map
        or "gates" in as_map
        or "qubits" in as_map
        or "operations" in as_map
        or "qubit_properties" in as_map
    ):
        return _json_dumps(dict(as_map))

    payload: dict[str, Any] = {}
    backend_name = getattr(source, "name", None) or getattr(source, "backend_name", None)
    if callable(backend_name):
        try:
            backend_name = backend_name()
        except Exception:
            backend_name = None
    if isinstance(backend_name, str) and backend_name:
        payload["backend_name"] = backend_name

    target = getattr(source, "target", None)
    if target is None and callable(getattr(source, "items", None)):
        # A live Target is a mapping of instruction names. Other mappings are
        # calibration documents and were returned above when they matched.
        if source.__class__.__name__ == "Target" or not isinstance(source, Mapping):
            target = source

    rows = [_qubit_property_row(row) for row in _qubit_property_rows(source, target)]
    operations: dict[str, list[dict[str, Any]]] = {}
    if target is not None:
        for name, qargs_map in _iter_target_instructions(target):
            gate = name.lower()
            for qargs, props in qargs_map.items():
                qubits = _qubit_indexes(qargs)
                if not qubits:
                    continue
                error, duration = _props_error_duration(props)
                if gate == "measure" and len(qubits) == 1 and error is not None:
                    while len(rows) <= qubits[0]:
                        rows.append({})
                    row = rows[qubits[0]]
                    if "prob_meas1_prep0" not in row and "prob_meas0_prep1" not in row:
                        row["readout_error"] = error
                    continue
                if gate in _NON_GATE_OPS:
                    continue
                rec: dict[str, Any] = {"qubits": qubits}
                if error is not None:
                    rec["error"] = error
                # Durations stay in seconds. The Rust extractor converts them to ns.
                if duration is not None:
                    rec["duration"] = duration
                operations.setdefault(gate, []).append(rec)
    if any(rows):
        payload["qubit_properties"] = rows
    if operations:
        payload["operations"] = operations

    # Optional legacy BackendProperties
    props_fn = getattr(source, "properties", None)
    if callable(props_fn):
        try:
            props_obj = props_fn()
        except Exception:
            props_obj = None
        if props_obj is not None:
            try:
                raw_props = props_obj.to_dict()
            except Exception:
                raw_props = _as_mapping(props_obj)
            if isinstance(raw_props, Mapping):
                if "qubits" in raw_props and "qubits" not in payload:
                    payload["qubits"] = raw_props["qubits"]
                if "gates" in raw_props and "gates" not in payload:
                    payload["gates"] = raw_props["gates"]
                if "backend_name" in raw_props and "backend_name" not in payload:
                    payload["backend_name"] = raw_props["backend_name"]

    if not payload:
        raise TypeError("unsupported Qiskit calibration source")
    return _json_dumps(payload)


def braket_object_to_json(source: Any) -> str:
    """Serialize AWS Braket device property documents."""
    source = _loads_if_str(source)
    if isinstance(source, str):
        return source
    as_map = _as_mapping(source)
    if as_map is not None and (
        "standardized" in as_map or "provider" in as_map or "paradigm" in as_map
    ):
        return _json_dumps(dict(as_map))

    props = getattr(source, "properties", None)
    if props is not None:
        mapped = _as_mapping(props)
        if mapped is not None:
            return _json_dumps(dict(mapped))
        # Braket often nests under .dict() / model_dump on properties
        for attr in ("model_dump", "dict"):
            fn = getattr(props, attr, None)
            if callable(fn):
                try:
                    dumped = fn()
                except TypeError:
                    dumped = fn(by_alias=True) if attr == "model_dump" else fn()
                if isinstance(dumped, Mapping):
                    return _json_dumps(dict(dumped))
    raise TypeError("unsupported Braket calibration source")


def _normalize_cirq_key(key: Any) -> str:
    if isinstance(key, tuple) and len(key) == 2:
        return f"({key[0]}, {key[1]})"
    text = str(key).strip()
    # GridQubit-like "q(0, 1)" / "(0, 1)"
    if text.startswith("q(") and text.endswith(")"):
        text = text[1:]
    return text


def _normalize_cirq_mapping(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, Any] = {}
    for key, value in raw.items():
        out[_normalize_cirq_key(key)] = value
    return out


def cirq_object_to_json(source: Any, qubit_order: Sequence[str] | None = None) -> str:
    """Serialize Cirq calibration dicts with tuple / GridQubit keys."""
    source = _loads_if_str(source)
    if isinstance(source, str):
        return source
    as_map = _as_mapping(source)
    if as_map is None:
        raise TypeError("unsupported Cirq calibration source")
    # qubit_order is passed separately to the Rust extractor; keep JSON clean.
    _ = qubit_order
    payload: dict[str, Any] = {}
    for key, value in as_map.items():
        if isinstance(value, Mapping):
            payload[str(key)] = _normalize_cirq_mapping(value)
        else:
            payload[str(key)] = value
    return _json_dumps(payload)


def pytket_object_to_json(source: Any) -> str:
    """Serialize Pytket Backend / BackendInfo objects."""
    source = _loads_if_str(source)
    if isinstance(source, str):
        return source
    as_map = _as_mapping(source)
    if as_map is not None and "nodes" in as_map:
        return _json_dumps(dict(as_map))

    info = getattr(source, "backend_info", None)
    if info is None and (
        source.__class__.__name__ == "BackendInfo" or hasattr(source, "nodes")
    ):
        info = source
    if info is None:
        raise TypeError("unsupported Pytket calibration source")

    nodes_raw = getattr(info, "nodes", None) or []
    nodes: list[Any] = []
    for node in nodes_raw:
        if hasattr(node, "index"):
            nodes.append(str(getattr(node, "index")))
        else:
            nodes.append(str(node))

    def _map_errors(raw: Any) -> dict[str, float]:
        if not isinstance(raw, Mapping):
            return {}
        out: dict[str, float] = {}
        for key, value in raw.items():
            try:
                out[str(key).replace(" ", "").replace(",", "_")] = float(value)
            except (TypeError, ValueError):
                continue
        return out

    payload: dict[str, Any] = {
        "nodes": nodes,
        "averaged_node_gate_errors": _map_errors(
            getattr(info, "averaged_node_gate_errors", None) or {}
        ),
        "averaged_edge_gate_errors": _map_errors(
            getattr(info, "averaged_edge_gate_errors", None) or {}
        ),
    }
    readout = getattr(info, "all_readout_errors", None)
    if readout:
        payload["all_readout_errors"] = list(readout)
    misc = getattr(info, "misc", None)
    if isinstance(misc, Mapping) and misc:
        payload["misc"] = dict(misc)
    return _json_dumps(payload)


def extract_layout_args(layout: Any) -> dict[str, Any]:
    """Normalize layout objects into kwargs for the Rust remap helpers."""
    if layout is None:
        return {}
    # Qiskit transpiled circuit
    circ_layout = getattr(layout, "layout", None)
    if circ_layout is not None and not isinstance(layout, (list, tuple, Mapping)):
        layout = circ_layout
    # TranspileLayout
    final_index = getattr(layout, "final_index_layout", None)
    if callable(final_index):
        try:
            idx = final_index(filter_ancillas=True)
        except TypeError:
            idx = final_index()
        return {"logical_to_physical": [int(x) for x in idx]}
    if isinstance(layout, Mapping):
        return {"physical_to_logical": {int(k): int(v) for k, v in layout.items()}}
    if isinstance(layout, Sequence) and not isinstance(layout, (str, bytes)):
        return {"logical_to_physical": [int(x) for x in layout]}
    raise TypeError("unsupported layout object")
