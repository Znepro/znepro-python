"""Offline checks of the Braket baselines, then one live R2 pass of all three wrappers."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
for entry in (str(ROOT), str(REPO)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from run_all_braket_case_studies import CASES, run_all

FORBIDDEN = ("?", "encryption_key_hex")


class TestOriginalBraketProjects(unittest.TestCase):
    def test_qaoa_records_match_the_device_numbers(self) -> None:
        folder = ROOT / CASES[0] / "1_original_braket_project"
        sys.path.insert(0, str(folder))
        import braket_qaoa_maxcut as qaoa

        program = qaoa.openqasm3()
        self.assertIn("#pragma braket verbatim", program)
        self.assertIn("cz $0, $3;", program)
        record = qaoa.load_hardware_results()
        scales = [row["expectation"] for row in record["rigetti_ankaa"]["noise_scales"]]
        self.assertEqual(scales, [-0.340, -0.255, -0.191])
        self.assertEqual(record["ionq_aria_1"]["expectation"], -0.510)
        self.assertEqual(record["ideal_mean_edge_correlator"], -0.612)

    def test_aquila_register_is_256_sites(self) -> None:
        folder = ROOT / CASES[1] / "1_original_braket_project"
        sys.path.insert(0, str(folder))
        import aquila_ahs_mis_program as aquila

        program = aquila.analog_program()
        sites = program["setup"]["ahs_register"]["sites"]
        self.assertEqual(len(sites), 256)
        self.assertEqual(aquila.C6_RAD_M6_PER_S, 5.42e-24)
        self.assertEqual(aquila.LATTICE_SPACING_M, 6.7e-6)
        record = aquila.load_hardware_results()
        scales = [(row["lambda"], row["expectation"]) for row in record["aquila"]["noise_scales"]]
        self.assertEqual(scales, [(1.0, 0.760), (1.3, 0.695), (1.6, 0.635)])
        self.assertEqual(record["ideal_z2_order"], 0.960)
        drive = program["hamiltonian"]["drivingFields"][0]
        self.assertEqual(len(drive["amplitude"]["time_s"]), 4)
        self.assertEqual(len(drive["detuning"]["value_rad_per_s"]), 4)

    def test_lih_energies_match_the_case_study(self) -> None:
        folder = ROOT / CASES[2] / "1_original_braket_project"
        sys.path.insert(0, str(folder))
        import braket_vqe_lih_16A as lih

        program = lih.openqasm3()
        self.assertIn("#pragma braket verbatim", program)
        self.assertIn("qubit[4] q;", program)
        self.assertIn("cx $2, $3;", program)
        record = lih.load_hardware_results()
        self.assertEqual(record["exact_active_space_ha"], -8.01642)
        self.assertEqual(record["bond_angstrom"], 1.6)
        energies = [row["energy_ha"] for row in record["braket_qpu"]["noise_scales"]]
        self.assertEqual(energies, [-6.820, -6.295, -5.810])


@unittest.skipUnless(os.environ.get("ZNEPRO_RUN_LIVE") == "1", "recorded artifacts are checked offline")
class TestLiveBraketR2(unittest.TestCase):
    rows: list[dict]

    @classmethod
    def setUpClass(cls) -> None:
        from shared_sdk import r2_bridge
        r2_bridge.load_environment()
        cls.rows = run_all()

    def test_three_live_jobs_reduce_the_qpu_error(self) -> None:
        self.assertEqual([row["case"] for row in self.rows], list(CASES))
        negative = 0
        for row in self.rows:
            final = row["final"]
            meta = row["meta"]
            self.assertEqual(final["sign_mask"], -1)
            negative += 1
            self.assertEqual(meta["put_http_status"], 200)
            self.assertEqual(meta["get_http_status"], 200)
            self.assertTrue(str(meta["r2_host"]).endswith("r2.cloudflarestorage.com"))
            self.assertRegex(
                meta["r2_key"],
                r"^tasks/[0-9a-f]{16}/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/input\.zk$",
            )
            receipt = json.loads((ROOT / row["case"] / "4_downloaded_from_r2" / "server_blinded_output.json").read_text(encoding="utf-8"))
            self.assertIn("mitigated_expectation", receipt["metrics"])
            self.assertFalse(set(receipt) - {"status", "job_id", "task_id", "backend_name", "target_observable", "total_shots", "execution_time_ms", "error", "metrics"})
            self.assertLess(final["mitigated_absolute_error"], final["raw_absolute_error"])
            self.assertGreater(final["error_reduction_factor"], 1.0)
            offset = float(final.get("identity_offset", 0.0))
            self.assertAlmostEqual(
                offset + final["sign_mask"] * final["server_mitigated_expectation"],
                final["unblinded_mitigated_expectation"],
                delta=1e-9,
            )
            self.assertAlmostEqual(
                final["server_visible_scale_0"],
                final["sign_mask"] * (final["raw_qpu_lambda_1"] - offset),
                places=6,
            )
        self.assertGreaterEqual(negative, 2)

    def test_saved_objects_match_the_r2_hashes_and_are_json(self) -> None:
        for name in CASES:
            case = ROOT / name
            meta = json.loads((case / "3_uploaded_to_r2" / "r2_upload_metadata.json").read_text(encoding="utf-8"))
            uploaded = (case / "3_uploaded_to_r2" / "input.zk").read_bytes()
            downloaded = (case / "4_downloaded_from_r2" / "output.zk").read_bytes()
            preview = (case / "3_uploaded_to_r2" / "blinded_inner_payload.json").read_bytes()
            self.assertEqual(hashlib.sha256(uploaded).hexdigest(), meta["input_sha256"])
            self.assertEqual(hashlib.sha256(downloaded).hexdigest(), meta["output_sha256"])
            self.assertEqual(hashlib.sha256(preview).hexdigest(), meta["blinded_plaintext_sha256"])
            self.assertGreater(len(uploaded), 2)
            self.assertGreater(len(downloaded), 2)
            uploaded_doc = json.loads(uploaded)
            json.loads(downloaded)
            self.assertIn("qasm", uploaded_doc)
            self.assertNotIn("sign_mask", uploaded_doc)
            blinded = json.loads(preview)
            self.assertNotIn("sign_mask", blinded)
            self.assertNotIn("permutation", blinded)
            self.assertIn("hardware_scales", blinded)
            original = case / "1_original_braket_project"
            self.assertFalse((original / "input.zk").exists())

    def test_saved_json_has_no_presigned_query_or_api_key(self) -> None:
        key = os.environ.get("ZNEPRO_API_KEY", "")
        self.assertTrue(key)
        for path in ROOT.rglob("*"):
            if path.suffix not in {".json", ".md", ".py"}:
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(key, text, path.name)
            if path.suffix == ".py":
                continue
            for token in FORBIDDEN:
                self.assertNotIn(token, text, path.name)


if __name__ == "__main__":
    unittest.main()
