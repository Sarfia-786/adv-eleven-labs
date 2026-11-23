"""Hermetic model-parameter inventory tests; CPU-only, no model downloads."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import model_parameter_inventory as inventory  # noqa: E402


class InventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.catalog_path = self.root / "backend/config/models.yaml"
        self.license_path = self.root / "backend/config/model_licenses.json"
        self.mobile_path = self.root / "mobile/contract/models.source.json"
        for path in (self.catalog_path, self.license_path, self.mobile_path):
            path.parent.mkdir(parents=True, exist_ok=True)
        self.previous_counts = inventory.COUNTS
        inventory.COUNTS = {"example/main": (12, "model-card", "https://example.test/card")}
        self.write_fixture()

    def tearDown(self) -> None:
        inventory.COUNTS = self.previous_counts
        self.temp.cleanup()

    def write_fixture(self, *, missing=(), duplicate=False) -> None:
        self.catalog_path.write_text(yaml.safe_dump({
            "models": [{"repo_id": "example/main", "role": "TTS", "size_gb": 0.2,
                        "dependencies": [{"repo_id": "example/dep"}]}]
        }), encoding="utf-8")
        records = [{"id": i, "review_status": "unreviewed"} for i in
                   ("example/main", "example/dep", "example/mobile") if i not in missing]
        if duplicate:
            records.append({"id": "example/main", "review_status": "unreviewed"})
        self.license_path.write_text(json.dumps({
            "models": records, "dynamic_assets": [{"id": "unknown-plugin"}]
        }), encoding="utf-8")
        self.mobile_path.write_text(json.dumps({
            "models": [{"id": "mobile1", "repo": "example/mobile", "capability": "asr"}]
        }), encoding="utf-8")

    def test_known_and_unknown_are_not_confused_with_download_size(self) -> None:
        rows, summary = inventory.build(self.root)
        self.assertEqual(summary["desktop_packages"], 1)
        self.assertEqual(summary["licensed_model_sources"], 3)
        self.assertEqual(summary["mobile_packages"], 1)
        self.assertEqual(summary["additional_dynamic_assets"], 1)
        self.assertEqual(summary["known_parameter_reports"], 1)
        self.assertEqual(summary["unverified_parameter_reports"], 2)
        by_id = {m["model_id"]: m for m in rows}
        self.assertEqual(by_id["example/main"]["parameter_millions_reported"], 12)
        self.assertEqual(by_id["example/main"]["approx_download_gib"], 0.2)
        self.assertIsNone(by_id["example/dep"]["parameter_millions_reported"])
        self.assertEqual(by_id["example/mobile"]["role"], "asr")
        self.assertIn("Unverified", inventory.markdown(rows, summary))
        report = inventory.markdown(rows, summary)
        self.assertIn("12M", report)
        self.assertIn("unknown-plugin", report)
        self.assertIn("`example/main`", report)
        self.assertEqual(summary["dynamic_assets"][0]["published_components"], [])

    def test_catalog_dependency_must_be_in_license_inventory(self) -> None:
        self.write_fixture(missing=("example/dep",))
        with self.assertRaisesRegex(ValueError, "example/dep"):
            inventory.build(self.root)

    def test_nested_package_uses_its_full_catalog_id(self) -> None:
        catalog = yaml.safe_load(self.catalog_path.read_text(encoding="utf-8"))
        catalog["models"][0]["dependencies"][0]["id"] = "example/dep:selected"
        self.catalog_path.write_text(yaml.safe_dump(catalog), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "example/dep:selected"):
            inventory.build(self.root)

    def test_duplicate_desktop_packages_are_rejected(self) -> None:
        catalog = yaml.safe_load(self.catalog_path.read_text(encoding="utf-8"))
        catalog["models"].append(catalog["models"][0].copy())
        self.catalog_path.write_text(yaml.safe_dump(catalog), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Duplicate desktop"):
            inventory.build(self.root)

    def test_mobile_source_must_be_in_license_inventory(self) -> None:
        self.write_fixture(missing=("example/mobile",))
        with self.assertRaisesRegex(ValueError, "example/mobile"):
            inventory.build(self.root)

    def test_duplicate_license_sources_are_rejected(self) -> None:
        self.write_fixture(duplicate=True)
        with self.assertRaisesRegex(ValueError, "Duplicate model-license IDs"):
            inventory.build(self.root)

    def test_unreviewed_commerciality_is_not_inferred_from_parameters(self) -> None:
        rows, _ = inventory.build(self.root)
        self.assertFalse(rows[0]["commercial_use_reviewed"])

    def test_full_repository_license_inventory_has_complete_desktop_and_mobile_coverage(self) -> None:
        inventory.COUNTS = self.previous_counts
        rows, summary = inventory.build(inventory.ROOT)
        self.assertEqual(summary["licensed_model_sources"], len(rows))
        self.assertGreaterEqual(summary["desktop_packages"], 40)
        self.assertGreaterEqual(summary["mobile_packages"], 10)
        self.assertGreater(summary["unverified_parameter_reports"], 0)
        by_id = {row["model_id"]: row for row in rows}
        self.assertEqual(by_id["IndexTeam/IndexTTS-2.5"]["parameter_evidence"], "GPT backbone only")
        self.assertIsNone(by_id["pyannote/speaker-diarization-3.1"]["parameter_millions_reported"])
        self.assertIn("segmentation-3.0", by_id["pyannote/speaker-diarization-3.1"]["parameter_note"])
        self.assertTrue(all(r["parameter_source"] for r in rows if r["parameter_millions_reported"] is not None))


if __name__ == "__main__":
    unittest.main()
