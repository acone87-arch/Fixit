"""Regression cases for the observed v1 semantic failures; no provider calls."""
import unittest

from scripts.ai_cloud_check import validate_output
from scripts.ai_semantics import RAW_SCHEMAS, grounded_output


class AISemanticsTests(unittest.TestCase):
    def history(self):
        return {"sources": [
            {"id": "s1", "date": "2026-09-01", "text": "Жалоба на течь. Заменено уплотнение."},
            {"id": "s2", "date": "2026-10-01", "text": "Снова поступила жалоба на течь."}],
            "coverage": {"truncated": False}}

    def test_recurrence_is_two_dated_events_without_causal_conclusion(self):
        result = grounded_output(self.history(), {"selected_source_ids": ["s2", "s1"]})
        self.assertEqual(result["summary"],
                         "2026-09-01: Жалоба на течь. Заменено уплотнение. [s1] "
                         "2026-10-01: Снова поступила жалоба на течь. [s2]")
        self.assertNotIn("не устранена", result["summary"])

    def test_model_cannot_supply_v1_unsupported_summary(self):
        old = {"selected_source_ids": ["s1", "s2"], "summary": "Проблема не устранена"}
        with self.assertRaises(ValueError):
            validate_output(old, RAW_SCHEMAS["equipment_brief"])

    def test_summary_keeps_missing_verification_instead_of_equipment_name(self):
        payload = {"sources": [{"id": "s1", "date": "2026-09-01",
                               "text": "Заменён клапан. Проверка не проводилась."}]}
        result = grounded_output(payload, {"selected_source_ids": ["s1"]})
        self.assertIn("Проверка не проводилась", result["summary"])
        self.assertEqual(result["facts"][0]["source_ids"], ["s1"])

    def test_ordering_a_part_is_moved_out_of_completed_work(self):
        payload = {"note": "Нашёл люфт крыльчатки. Заказал втулку, жду деталь."}
        raw = {"diagnostic_quotes": ["Нашёл люфт крыльчатки."],
               "work_quotes": ["Заказал втулку, жду деталь."], "comment_quotes": [], "questions": []}
        result = grounded_output(payload, raw)
        self.assertEqual(result["work"], "")
        self.assertEqual(result["comment"], "Заказал втулку, жду деталь.")

    def test_real_repair_is_preserved_alongside_organizational_comment(self):
        payload = {"note": "Очистил фильтр. Заказал втулку."}
        raw = {"diagnostic_quotes": [], "work_quotes": ["Очистил фильтр.", "Заказал втулку."],
               "comment_quotes": [], "questions": []}
        result = grounded_output(payload, raw)
        self.assertEqual(result["work"], "Очистил фильтр.")
        self.assertEqual(result["comment"], "Заказал втулку.")

    def test_quote_cannot_drop_negation_or_invent_success(self):
        payload = {"note": "Не менял насос. Работу не проверял."}
        for quote in ["менял насос.", "Насос заменён.", "Работоспособность подтверждена."]:
            raw = {"diagnostic_quotes": [], "work_quotes": [quote],
                   "comment_quotes": ["Работу не проверял."], "questions": []}
            with self.subTest(quote=quote), self.assertRaisesRegex(ValueError, "complete source sentence"):
                grounded_output(payload, raw)

    def test_omissions_and_double_assignment_are_rejected(self):
        payload = {"note": "Осмотрел корпус. Проверку не проводил."}
        for raw in [
            {"diagnostic_quotes": ["Осмотрел корпус."], "work_quotes": [], "comment_quotes": [], "questions": []},
            {"diagnostic_quotes": ["Осмотрел корпус."], "work_quotes": ["Осмотрел корпус."],
             "comment_quotes": ["Проверку не проводил."], "questions": []},
        ]:
            with self.assertRaises(ValueError):
                grounded_output(payload, raw)

    def test_unknown_or_omitted_source_rejected(self):
        for ids in [["missing"], ["s1"], ["s1", "s1"], []]:
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                grounded_output(self.history(), {"selected_source_ids": ids})

    def test_empty_and_truncated_histories_keep_their_limits(self):
        result = grounded_output({"sources": []}, {"selected_source_ids": []})
        self.assertEqual(result["summary"], "Истории пока недостаточно.")
        payload = self.history()
        payload["coverage"]["truncated"] = True
        result = grounded_output(payload, {"selected_source_ids": ["s1", "s2"]})
        self.assertIn("переданной частью истории", result["warnings"][0])


if __name__ == "__main__":
    unittest.main()
