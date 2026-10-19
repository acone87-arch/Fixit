"""Budget and output checks for the standalone synthetic cloud probe; no network."""
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from scripts.ai_cloud_check import SCHEMAS, amount, reserve, save_private, validate_output


class CloudCheckTests(unittest.TestCase):
    def setUp(self):
        self.policy = {"monthly_budget_rub": 300, "daily_limit_rub": 10, "evaluation_budget_rub": 30}
        self.at = "2026-10-19T20:00:00+05:00"

    def test_unknown_call_keeps_full_reserve(self):
        ledger = []
        record = reserve(ledger, "first", Decimal("8"), self.at, self.policy)
        record["status"] = "unknown"
        self.assertEqual(amount(record), Decimal("8"))
        with self.assertRaisesRegex(ValueError, "Budget limit"):
            reserve(ledger, "second", Decimal("3"), self.at, self.policy)
        self.assertEqual(len(ledger), 1)

    def test_known_usage_releases_unused_reserve(self):
        ledger = []
        record = reserve(ledger, "first", Decimal("8"), self.at, self.policy)
        record.update(status="succeeded", cost_rub="0.5")
        reserve(ledger, "second", Decimal("8"), self.at, self.policy)
        self.assertEqual(sum(map(amount, ledger)), Decimal("8.5"))

    def test_duplicate_key_does_not_reserve_again(self):
        ledger = []
        reserve(ledger, "first", Decimal("1"), self.at, self.policy)
        with self.assertRaisesRegex(ValueError, "Already attempted"):
            reserve(ledger, "first", Decimal("1"), self.at, self.policy)
        self.assertEqual(len(ledger), 1)

    def test_daily_monthly_and_eval_caps_independently_apply(self):
        for policy, ceiling in [
            (self.policy, "11"),
            ({**self.policy, "monthly_budget_rub": 2}, "3"),
            ({**self.policy, "evaluation_budget_rub": 2}, "3"),
        ]:
            with self.subTest(policy=policy):
                ledger = []
                with self.assertRaisesRegex(ValueError, "Budget limit"):
                    reserve(ledger, "first", Decimal(ceiling), self.at, policy)
                self.assertEqual(ledger, [])

    def test_previous_day_still_counts_toward_month_and_eval(self):
        ledger = [{"key": "old", "at": "2026-10-18T20:00:00+05:00",
                   "cost_rub": "29", "reserved_rub": "29", "status": "succeeded"}]
        with self.assertRaisesRegex(ValueError, "Budget limit"):
            reserve(ledger, "new", Decimal("2"), self.at, self.policy)

    def test_unknown_fields_and_wrong_types_are_rejected(self):
        valid = {"diagnostic": "", "work": "Очищен фильтр", "comment": "", "questions": [], "warnings": []}
        validate_output(valid, SCHEMAS["repair_draft"])
        for invalid in ({**valid, "signature": "invented"}, {**valid, "work": None}, {**valid, "questions": "text"}):
            with self.assertRaises(ValueError):
                validate_output(invalid, SCHEMAS["repair_draft"])

    def test_private_ledger_is_replaced_with_restricted_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            save_private(path, [{"state": "pending"}])
            save_private(path, [{"state": "succeeded"}])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("pending", path.read_text())
            self.assertFalse(path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
