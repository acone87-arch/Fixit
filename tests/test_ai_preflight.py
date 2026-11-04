"""AI-00 tooling tests: no application imports, credentials, network or DB."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.ai_preflight import (
    DATASET, FILES, TIMINGS, baseline_summary, dataset_summary,
    export_inputs, load_cases, review_template,
)


class AIPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def write_dataset(self, change):
        datasets = {name: [json.loads(line) for line in (DATASET / name).read_text().splitlines()]
                    for name in FILES}
        change(datasets)
        for name, rows in datasets.items():
            (self.directory / name).write_text("\n".join(json.dumps(row) for row in rows))
        return self.directory

    def test_committed_starter_is_valid_but_not_reviewed_or_evaluated(self):
        result = dataset_summary()
        self.assertEqual(result["cases"], 80)
        self.assertEqual(result["domain_review_pending"], 80)
        self.assertEqual(result["counts"], {"equipment_brief/tune": 20, "equipment_brief/holdout": 10,
                                            "repair_draft/tune": 35, "repair_draft/holdout": 15})
        self.assertEqual(len(result["sha256"]), 2)

    def test_same_family_cannot_cross_holdout_boundary(self):
        path = self.write_dataset(lambda data: data["repair_cases.jsonl"][0].update(split="holdout"))
        with self.assertRaisesRegex(ValueError, "family leaks"):
            load_cases(path)

    def test_duplicate_case_rejected(self):
        path = self.write_dataset(lambda data: data["repair_cases.jsonl"].append(data["repair_cases.jsonl"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate case ID"):
            load_cases(path)

    def test_gold_cannot_reference_an_invented_source(self):
        def corrupt(data):
            data["history_cases.jsonl"][0]["expected"]["source_ids"].append("NONEXISTENT")
        with self.assertRaisesRegex(ValueError, "unknown expected source"):
            load_cases(self.write_dataset(corrupt))

    def test_fewer_than_minimum_cases_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least 50"):
            load_cases(self.write_dataset(lambda data: data["repair_cases.jsonl"].pop()))

    def test_export_never_leaks_gold_to_model_input(self):
        exported = export_inputs(load_cases(), "tune")
        self.assertEqual(len(exported), 55)
        for row in exported:
            self.assertEqual(set(row), {"id", "scenario", "input"})
            self.assertNotIn("expected", row["input"])
        self.assertTrue(set(row["id"] for row in exported).isdisjoint(
            row["id"] for row in export_inputs(load_cases(), "holdout")))

    def test_review_template_does_not_invent_results(self):
        result = review_template(load_cases(), "holdout", "pro-51")
        self.assertEqual(result["status"], "not_run")
        self.assertEqual(len(result["reviews"]), 25)
        for row in result["reviews"]:
            self.assertIsNone(row["output"])
            self.assertIsNone(row["critical_fabrication"])
            self.assertIsNone(row["cost_rub"])

    def baseline_file(self, rows):
        path = self.directory / "baseline.json"
        path.write_text(json.dumps({"schema_version": 1, "sessions": rows}))
        return path

    def session(self, identifier="observation-1"):
        return {"sample_id": identifier, "mode": "manual", "complexity": "standard",
                **dict(zip(TIMINGS, [100, 20, 10, 5, 5]))}

    def test_empty_baseline_does_not_claim_measurement(self):
        result = baseline_summary(self.baseline_file([]))
        self.assertEqual(result["status"], "insufficient_baseline")
        self.assertEqual(result["groups"], [])

    def test_baseline_totals_include_review_corrections_and_network(self):
        manual = self.session()
        ai = {**self.session("observation-2"), "mode": "ai", "text_seconds": 10}
        result = baseline_summary(self.baseline_file([manual, ai]))
        self.assertEqual(result["manual_samples"], 1)
        self.assertEqual({row["mode"]: row["median_total_seconds"] for row in result["groups"]},
                         {"manual": 140, "ai": 50})
        self.assertEqual(result["status"], "insufficient_baseline")

    def test_invalid_times_and_duplicates_rejected(self):
        for invalid in (-1, float("nan"), float("inf"), True, None):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "finite and nonnegative"):
                    baseline_summary(self.baseline_file([{**self.session(), "text_seconds": invalid}]))
        with self.assertRaisesRegex(ValueError, "duplicate sample"):
            baseline_summary(self.baseline_file([self.session(), copy.deepcopy(self.session())]))

    def test_twenty_observations_are_a_sample_not_a_quality_claim(self):
        result = baseline_summary(self.baseline_file([self.session(f"observation-{i}") for i in range(20)]))
        self.assertEqual(result["status"], "minimum_sample_collected")
        self.assertNotIn("ai_ready", result)


if __name__ == "__main__":
    unittest.main()
