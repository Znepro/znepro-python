#!/usr/bin/env python3
"""Rebuild the Cepheus engine 0.1.3 tables from counts and receipts in this directory.

The prepared tables under reproduced/ are outputs. This script does not read them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXAMINED = (
    "diag_asymmetric_3q",
    "h2_sto3g_trial_00",
    "maxcut_cycle8_angles_a",
    "ising_4_end_step3",
    "param_hea_6",
)
FAMILIES = (
    "control_diagnostics",
    "vqe_molecular",
    "qaoa_maxcut",
    "ising_dynamics",
    "parametric_circuits",
)
PARTIAL = {
    "diag_near_zero_2q": (1, 2, 3),
    "diag_product_6q": (1, 2, 3),
    "diag_asymmetric_3q": (2, 3),
    "h2_sto3g_trial_00": (2, 3),
}
TWO_QUBIT = {"CZ", "XY", "CPHASE", "CNOT", "CCNOT", "ISWAP", "PSWAP", "CP"}


def fail(message: str) -> None:
    raise SystemExit(message)


def read_json(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        fail(f"expected an object in {path.name}")
    return document


def guard() -> None:
    if os.environ.get("ZNEPRO_API_KEY") or os.environ.get("ZNEPRO_API_URL"):
        fail("unset ZNEPRO_API_KEY and ZNEPRO_API_URL before this offline command")
    if (HERE / ".env").exists():
        fail("remove .env from the study directory before this offline command")
    blocked = re.compile(
        "|".join(
            (
                "http" + "s?://",
                "arn:" + "aws",
                "Bear" + "er ",
                "znepro_" + "live_",
                "aws_" + "access_key",
                "/Us" + "ers/",
                "task-" + "[0-9a-fA-F]{8}-",
            )
        )
    )
    for path in HERE.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".md", ".json", ".quil"}:
            continue
        if "reproduced" in path.relative_to(HERE).parts:
            continue
        if blocked.search(path.read_text(encoding="utf-8")):
            fail(f"blocked token in {path.relative_to(HERE)}")


def support(label: str) -> tuple[int, ...]:
    return tuple(index for index, letter in enumerate(label) if letter != "I")


def expectation(counts: dict[str, int], label: str) -> float:
    total = sum(counts.values())
    if total <= 0:
        fail("empty counts")
    signed = 0
    for bitstring, count in counts.items():
        if len(bitstring) < len(label):
            fail("bitstring is shorter than the observable")
        sign = 1
        for qubit in support(label):
            if bitstring[qubit] == "1":
                sign = -sign
        signed += sign * int(count)
    return signed / total


def combine(case: dict, values: dict[str, float]) -> float | dict[str, float]:
    if case["formula"] == "components":
        return {str(term["pauli"]): float(values[str(term["pauli"])]) for term in case["terms"]}
    total = float(case["constant"])
    for term in case["terms"]:
        total += float(term["coefficient"]) * float(values[str(term["pauli"])])
    return total


def h2_energy(case: dict, values: dict[str, float]) -> float:
    terms = case["terms"]
    if len(terms) != 14 or any(set(str(term["pauli"])) <= {"I"} for term in terms):
        fail("H2 energy requires 14 non-identity terms")
    total = float(case["constant"])
    for term in terms:
        total += float(term["coefficient"]) * float(values[str(term["pauli"])])
    return total


def absolute_error(value: float | dict[str, float], reference: object) -> float:
    if isinstance(value, dict):
        if not isinstance(reference, dict):
            fail("component reference is not an object")
        return sum(abs(float(value[key]) - float(reference[key])) for key in value) / len(value)
    return abs(float(value) - float(reference))


def counts_for(case_id: str, group_id: str, round_number: int) -> dict:
    path = HERE / "counts" / f"r{round_number}" / f"{case_id}__{group_id}.json"
    document = read_json(path)
    local_id = f"r{round_number}/{case_id}/{group_id}"
    counts = {str(key): int(value) for key, value in document["counts"].items()}
    if document.get("local_id") != local_id or document.get("case_id") != case_id:
        fail(f"counts identity mismatch for {local_id}")
    if document.get("group_id") != group_id or document.get("round") != round_number:
        fail(f"counts round mismatch for {local_id}")
    if document.get("status") != "COMPLETED" or document.get("data_type") != "real_qpu":
        fail(f"counts are not a completed real-QPU record for {local_id}")
    if document.get("bit_order") != "q0_left" or sum(counts.values()) != 1000 or int(document.get("shots")) != 1000:
        fail(f"shot record mismatch for {local_id}")
    document["counts"] = counts
    return document


def receipt_for(root: Path, case_id: str, group_id: str, round_number: int, label: str, arm: str, shots: int) -> dict:
    document = read_json(root / f"r{round_number}" / f"{case_id}__{group_id}" / f"{label}.json")
    local_id = f"r{round_number}/{case_id}/{group_id}/{label}"
    if document.get("local_id") != local_id or document.get("observable") != label or document.get("target_observable") != label:
        fail(f"receipt identity mismatch for {local_id}")
    if document.get("status") != "COMPLETED" or document.get("engine_version") != "0.1.3":
        fail(f"receipt is not COMPLETED on engine 0.1.3 for {local_id}")
    if document.get("arm") != arm or int(document.get("total_shots")) != shots:
        fail(f"receipt arm or shots mismatch for {local_id}")
    if arm == "historical_partial_card":
        witness = str(document.get("calibration_sha256") or "")
        if document.get("calibration_applied") is not True or len(witness) != 64 or document.get("card_name") != "historical partial card":
            fail(f"partial-card witness mismatch for {local_id}")
    elif document.get("calibration_applied") is not False:
        fail(f"calibration flag mismatch for {local_id}")
    value = document.get("mitigated_expectation")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(f"mitigated expectation missing for {local_id}")
    return document


def values_for(case: dict, round_number: int, root: Path, arm: str) -> tuple[dict[str, float], dict[str, float]]:
    raw_values: dict[str, float] = {}
    mitigated_values: dict[str, float] = {}
    for group in case["measurement_groups"]:
        stored = counts_for(case["case_id"], group["group_id"], round_number)
        digest = hashlib.sha256(str(group["qasm"]).encode("utf-8")).hexdigest()
        if stored.get("qasm_sha256") != digest:
            fail(f"circuit hash mismatch for {stored['local_id']}")
        for label in group["observables"]:
            label = str(label)
            raw_values[label] = expectation(stored["counts"], label)
            receipt = receipt_for(root, case["case_id"], group["group_id"], round_number, label, arm, sum(stored["counts"].values()))
            mitigated_values[label] = float(receipt["mitigated_expectation"])
    return raw_values, mitigated_values


def primary(case: dict, values: dict[str, float]) -> float | dict[str, float]:
    if case["case_id"] == "h2_sto3g_trial_00":
        energy = h2_energy(case, values)
        if abs(energy - float(combine(case, values))) > 1e-12:
            fail("H2 term sum disagrees with the weighted sum")
        return energy
    return combine(case, values)


def score_case(case: dict, round_number: int, root: Path, arm: str) -> dict:
    raw_values, mitigated_values = values_for(case, round_number, root, arm)
    required = [str(term["pauli"]) for term in case["terms"]]
    if any(label not in raw_values or label not in mitigated_values for label in required):
        fail(f"missing observable for {case['case_id']} round {round_number}")
    raw = primary(case, raw_values)
    mitigated = primary(case, mitigated_values)
    raw_error = absolute_error(raw, case["recorded_primary"])
    mitigated_error = absolute_error(mitigated, case["recorded_primary"])
    return {
        "raw_absolute_error": raw_error,
        "reduction": raw_error - mitigated_error,
        "znepro_absolute_error": mitigated_error,
    }


def fmt(value: float) -> str:
    if value != 0 and abs(value) < 1e-3:
        return f"{value:.6e}"
    return f"{value:.8g}"


def opcodes(text: str) -> set[str]:
    found = set()
    for line in text.splitlines():
        token = line.split("#", 1)[0].strip().split(" ", 1)[0].upper()
        if token:
            found.add(token)
    return found


def check_wording() -> None:
    readme = (HERE / "README.md").read_text(encoding="utf-8")
    summary = (HERE / "SUMMARY.md").read_text(encoding="utf-8")
    for text in (readme, summary):
        for phrase in ("20 of 25", "21 of 25", "diag_near_zero_2q", "ising_6_mag_step1", "ZNEPro", "Fire Opal", "M3", "162 tasks", "162,000"):
            if phrase not in text:
                fail(f"missing required phrase: {phrase}")
    slides = (HERE / "DECK.md").read_text(encoding="utf-8").split("\n---\n")
    if len(slides) != 5:
        fail("DECK.md does not contain five slides")


def check_compiled(cases: list[dict]) -> None:
    h2 = next(case for case in cases if case["case_id"] == "h2_sto3g_trial_00")
    if any("cnot" not in str(group["qasm"]) for group in h2["measurement_groups"]):
        fail("an H2 measurement group does not contain cnot")
    compiled = list((HERE / "compiled").rglob("*.quil"))
    if len(compiled) != 18:
        fail("expected 18 compiled programs for the partial-card tasks")
    for path in compiled:
        if opcodes(path.read_text(encoding="utf-8")) & TWO_QUBIT:
            fail(f"compiled program contains a two-qubit opcode: {path.name}")
    for path in (HERE / "card_context").rglob("*.json"):
        document = read_json(path)
        if document.get("temporal_validity") is not None or document.get("card_name") != "historical partial card":
            fail(f"card context mismatch in {path.name}")


def h2_age_span(round_number: int) -> tuple[float, float]:
    ages: list[float] = []
    for path in sorted((HERE / "card_context" / f"r{round_number}").glob("h2_sto3g_trial_00__*.json")):
        for row in read_json(path)["field_ages"]:
            ages.append(float(row["age_at_task_start_hours"]))
    if not ages:
        fail(f"missing H2 field ages for round {round_number}")
    return min(ages), max(ages)


def write_tables(document: dict) -> None:
    lines = [
        "# Recomputed Cepheus tables",
        "",
        "These tables were rebuilt from `counts/` and `receipts/` in this directory.",
        "",
        f"Main result: {document['all_three_better']} of 25 cases are better in all three rounds, and {document['mean_smaller']} of 25 have a lower three-round mean.",
        "",
        "Cases worse than raw in all three rounds: `diag_near_zero_2q` and `ising_6_mag_step1`.",
        "",
        "## Main 25",
        "",
        "| case_id | unit | round 1 | round 2 | round 3 | three-round mean | rounds better |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in document["rows"]:
        if row["cohort"] != "main_25":
            continue
        values = row["reductions"]
        lines.append(
            f"| `{row['case_id']}` | {row['unit']} | {fmt(values[0])} | {fmt(values[1])} | {fmt(values[2])} | {fmt(row['mean'])} | {row['rounds_better']} |"
        )
    lines.extend(["", "## Examined 5", "", "| case_id | unit | round 1 | round 2 | round 3 | three-round mean | rounds better |", "| --- | --- | ---: | ---: | ---: | ---: | ---: |"])
    for row in document["rows"]:
        if row["cohort"] != "examined_5":
            continue
        values = row["reductions"]
        lines.append(
            f"| `{row['case_id']}` | {row['unit']} | {fmt(values[0])} | {fmt(values[1])} | {fmt(values[2])} | {fmt(row['mean'])} | {row['rounds_better']} |"
        )
    lines.extend(["", "## Families of the 25", "", "| family | better in 3, 2, 1, 0 rounds | mean lower | family mean | unit |", "| --- | --- | ---: | ---: | --- |"])
    for family in document["families"]:
        counts = ", ".join(str(value) for value in family["better_counts"])
        lines.append(f"| `{family['family_id']}` | {counts} | {family['mean_smaller']} | {format(family['family_mean'], '.16g')} | {family['unit']} |")
    lines.extend(["", "## Historical partial card", "", "| case_id | round | score | raw | no card | partial card | partial versus no card |", "| --- | ---: | --- | ---: | ---: | ---: | --- |"])
    for row in document["partial_rows"]:
        relation = "lower" if row["card_gain"] > 0 else "higher" if row["card_gain"] < 0 else "equal"
        lines.append(
            f"| `{row['case_id']}` | {row['round']} | {row['metric']} | {fmt(row['raw_absolute_error'])} | {fmt(row['no_card_absolute_error'])} | {fmt(row['partial_absolute_error'])} | {relation} |"
        )
    lines.append("")
    output = HERE / "reproduced"
    output.mkdir(exist_ok=True)
    (output / "TABLES.md").write_text("\n".join(lines), encoding="utf-8")
    (output / "results.json").write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    guard()
    check_wording()
    manifest = read_json(HERE / "manifest.json")
    cases = manifest["cases"]
    if len(cases) != 30:
        fail("the manifest does not contain 30 cases")
    check_compiled(cases)
    count_files = list((HERE / "counts").rglob("*.json"))
    zero_files = list((HERE / "receipts" / "zero_telemetry").rglob("*.json"))
    no_card_files = list((HERE / "receipts" / "partial_no_card").rglob("*.json"))
    card_files = list((HERE / "receipts" / "partial_card").rglob("*.json"))
    if len(count_files) != 162 or sum(int(read_json(path)["shots"]) for path in count_files) != 162000:
        fail("task or shot coverage is not 162 tasks and 162000 shots")
    if len(zero_files) != 444 or len(no_card_files) != 42 or len(card_files) != 42:
        fail("receipt coverage is not 444 no-card receipts and 84 partial-card receipts")
    per_round = []
    rows = []
    zero_root = HERE / "receipts" / "zero_telemetry"
    for case in cases:
        reductions = []
        for round_number in (1, 2, 3):
            scored = score_case(case, round_number, zero_root, "single_run_zero_telemetry")
            reductions.append(float(scored["reduction"]))
        mean = sum(reductions) / 3
        rows.append(
            {
                "case_id": case["case_id"],
                "cohort": "examined_5" if case["case_id"] in EXAMINED else "main_25",
                "family_id": case["family_id"],
                "mean": mean,
                "reductions": reductions,
                "rounds_better": sum(value > 0 for value in reductions),
                "unit": case["unit"],
            }
        )
    for round_number in (1, 2, 3):
        per_round.append(sum(1 for path in zero_files if path.parts[-3] == f"r{round_number}"))
    if per_round != [148, 148, 148]:
        fail("no-card receipts are not 148 in each round")
    main = [row for row in rows if row["cohort"] == "main_25"]
    if len(main) != 25:
        fail("the main denominator is not 25")
    all_three = sum(row["rounds_better"] == 3 for row in main)
    mean_smaller = sum(row["mean"] > 0 for row in main)
    worse_all = sorted(row["case_id"] for row in main if row["rounds_better"] == 0)
    if all_three != 20 or mean_smaller != 21 or worse_all != ["diag_near_zero_2q", "ising_6_mag_step1"]:
        fail("rebuilt 25-case counts do not match the published result")
    families = []
    for family in FAMILIES:
        selected = [row for row in main if row["family_id"] == family]
        families.append(
            {
                "better_counts": [sum(row["rounds_better"] == count for row in selected) for count in (3, 2, 1, 0)],
                "family_id": family,
                "family_mean": sum(row["mean"] for row in selected) / len(selected),
                "mean_smaller": sum(row["mean"] > 0 for row in selected),
                "unit": selected[0]["unit"],
            }
        )
    partial_rows = []
    no_root = HERE / "receipts" / "partial_no_card"
    card_root = HERE / "receipts" / "partial_card"
    by_id = {case["case_id"]: case for case in cases}
    for case_id, rounds in PARTIAL.items():
        case = by_id[case_id]
        for round_number in rounds:
            raw_values, no_values = values_for(case, round_number, no_root, "no_card")
            _raw_again, card_values = values_for(case, round_number, card_root, "historical_partial_card")
            raw = primary(case, raw_values)
            no_card = primary(case, no_values)
            partial = primary(case, card_values)
            raw_error = absolute_error(raw, case["recorded_primary"])
            no_error = absolute_error(no_card, case["recorded_primary"])
            card_error = absolute_error(partial, case["recorded_primary"])
            partial_rows.append(
                {
                    "card_gain": no_error - card_error,
                    "case_id": case_id,
                    "metric": "mae" if case["formula"] == "components" else "absolute_error",
                    "no_card_absolute_error": no_error,
                    "partial_absolute_error": card_error,
                    "raw_absolute_error": raw_error,
                    "round": round_number,
                }
            )
    better = sum(row["card_gain"] > 0 for row in partial_rows)
    worse = sum(row["card_gain"] < 0 for row in partial_rows)
    equal = sum(row["card_gain"] == 0 for row in partial_rows)
    if len(partial_rows) != 10 or better != 5 or worse != 5 or equal != 0 or len(PARTIAL) != 4:
        fail("partial-card comparison is not 5 lower and 5 higher")
    ages = {"round_2": h2_age_span(2), "round_3": h2_age_span(3)}
    document = {
        "all_three_better": all_three,
        "card_better": better,
        "card_case_rounds": 10,
        "card_circuits": 4,
        "card_equal": equal,
        "card_receipts": 84,
        "card_worse": worse,
        "denominator": 25,
        "families": families,
        "h2_field_age_hours": {"round_2": list(ages["round_2"]), "round_3": list(ages["round_3"])},
        "mean_smaller": mean_smaller,
        "partial_rows": partial_rows,
        "receipts_per_round": per_round,
        "receipts_total": 444,
        "rows": rows,
        "shots": 162000,
        "tasks": 162,
        "worse_all_three": worse_all,
    }
    write_tables(document)
    print(json.dumps({"all_three_better": 20, "card_better": 5, "card_worse": 5, "denominator": 25, "mean_smaller": 21}, sort_keys=True))


if __name__ == "__main__":
    main()
