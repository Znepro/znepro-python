"""Run the three customer wrappers and write the case-study overview."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CASES = (
    "01_lanl_qaoa_ankaa_aria",
    "02_quera_aquila_rydberg_256q",
    "03_braket_pennylane_vqe_lih",
)


def run_all() -> list[dict]:
    rows = []
    for name in CASES:
        script = ROOT / name / "2_customer_added_code" / "add_znepro_mitigation.py"
        subprocess.run([sys.executable, str(script)], check=True)
        final = json.loads((ROOT / name / "4_downloaded_from_r2" / "final_unblinded_result.json").read_text(encoding="utf-8"))
        meta = json.loads((ROOT / name / "3_uploaded_to_r2" / "r2_upload_metadata.json").read_text(encoding="utf-8"))
        rows.append({"case": name, "final": final, "meta": meta})
    (ROOT / "README.md").write_text(render_readme(rows), encoding="utf-8")
    return rows


def render_readme(rows: list[dict]) -> str:
    lines = [
        "# Braket case studies on ZNEPro",
        "",
        "Three published Braket workloads. Each folder keeps the original project, the customer wrapper, the exact bytes PUT to Cloudflare R2, and the exact bytes GET back.",
        "",
        "Presigned query strings are not stored. `r2_upload_metadata.json` keeps the host, object URL path, byte count, and SHA-256.",
        "",
        "| Case | Task | R2 key | input.zk | output.zk | Raw QPU | Server (blinded) | Unblinded | Ideal | Error reduction |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        final = row["final"]
        meta = row["meta"]
        lines.append(
            "| {case} | `{task}` | `{key}` | {inp} B | {out} B | {raw:.6f} | {server:.6f} | {restored:.6f} | {ideal:.6f} | {factor:.2f}x |".format(
                case=row["case"],
                task=meta["task_id"],
                key=meta["r2_key"],
                inp=meta["input_bytes"],
                out=meta["output_bytes"],
                raw=final["raw_qpu_lambda_1"],
                server=final["server_mitigated_expectation"],
                restored=final["unblinded_mitigated_expectation"],
                ideal=final["ideal"],
                factor=final["error_reduction_factor"],
            )
        )
    lines.extend(
        [
            "",
            "## Layout",
            "",
            "- `shared_sdk/znepro_braket_plugin.py` — init, blind, R2 PUT of the job JSON, commit, R2 GET, unblind.",
            "- `01_lanl_qaoa_ankaa_aria` — OpenQASM 3 verbatim QAOA, Ankaa scales `-0.340 / -0.255 / -0.191`, Aria-1 raw `-0.510`, ideal `-0.612`. The R2 job uses the Ankaa series. `s_k = -1`.",
            "- `02_quera_aquila_rydberg_256q` — 256-site Aquila program, Z2 order `0.760 / 0.695 / 0.635`, ideal `0.960`. Site stretch `lambda^(1/6)` stays local. `s_k = -1`.",
            "- `03_braket_pennylane_vqe_lih` — 4-qubit LiH at 1.6 A, energies `-6.820 / -6.295 / -5.810` Ha, target `-8.01642` Ha. The classical identity offset `-4.15` Ha stays on the client; only the remainder is masked and uploaded. `s_k = -1`.",
            "",
            "In every blinded payload the lambda = 1 sample has the opposite sign from the original QPU file, and the OpenQASM wire labels are the permuted ones.",
            "",
            "## Reproduce",
            "",
            "```bash",
            "python3 -m unittest braket_case_studies.test_braket_case_studies",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    rows = run_all()
    for row in rows:
        final = row["final"]
        print(
            f"{row['case']}: raw {final['raw_qpu_lambda_1']:.6f} -> "
            f"server {final['server_mitigated_expectation']:.6f} -> "
            f"unblinded {final['unblinded_mitigated_expectation']:.6f} "
            f"({final['error_reduction_factor']:.2f}x)"
        )


if __name__ == "__main__":
    main()
