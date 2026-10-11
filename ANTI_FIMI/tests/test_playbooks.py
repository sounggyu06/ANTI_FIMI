"""Operational workbook integration, candidate boundaries and audit regression tests."""
from contextlib import closing
from datetime import timedelta
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from engine import LexicalDemoEmbedder, stamp
from playbooks import DEFAULT_WORKBOOK, NS, language, parse_workbook
from server import Runtime, RawOnlyEmbedder
from test_fusion import BASE, rows


def edited(content, edits):
    """Mutate temporary test cells only, never the user's workbook."""
    output = BytesIO()
    with ZipFile(BytesIO(content)) as source, ZipFile(output, "w") as dest:
        for info in source.infolist():
            value = source.read(info.filename)
            if info.filename in edits:
                root = ET.fromstring(value)
                for ref, text in edits[info.filename].items():
                    cell = root.find(f".//s:c[@r='{ref}']", NS)
                    if cell is None:
                        raise AssertionError(f"Missing fixture cell {ref}")
                    for child in list(cell):
                        cell.remove(child)
                    cell.attrib["t"] = "inlineStr"
                    node = ET.SubElement(ET.SubElement(cell, "{"+NS["s"]+"}is"), "{"+NS["s"]+"}t")
                    node.text = text
                value = ET.tostring(root, encoding="utf-8")
            dest.writestr(info, value)
    return output.getvalue()


class PlaybookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.content = DEFAULT_WORKBOOK.read_bytes()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.book = self.folder / "rules.xlsx"
        self.book.write_bytes(self.content)
        self.db = self.folder / "state.db"
        self.now = BASE + timedelta(hours=1)
        self.runtime = Runtime(self.db, RawOnlyEmbedder(self.db), clock=lambda: self.now, playbook_path=self.book)

    def tearDown(self):
        self.temp.cleanup()

    def ingest(self, posts):
        self.runtime.ingest(posts, stamp(self.now))
        return self.runtime.dashboard()

    def cluster(self, choices):
        items = self.runtime.ai_pending()["items"]
        self.runtime.receive_ai([{"post_id": p["post_id"], "raw_sha256": p["raw_sha256"], "model_version": "fixture",
            "scope_id": "test", "revision": 1, "cluster_id": choices[i]} for i, p in enumerate(items)])
        return self.runtime.dashboard()

    def matches(self, data):
        return data["playbook_raw_matches"] + [p for c in data["cases"]+data["investigations"] for p in c["response_plans"]]

    def query(self, sql):
        with closing(sqlite3.connect(self.db)) as conn:
            return conn.execute(sql).fetchall()

    def test_actual_workbook_and_ordered_actions(self):
        book = parse_workbook(self.content)
        self.assertEqual(len(book["scenarios"]), 40)
        self.assertEqual(len(book["rules"]), 3)
        for card in book["scenarios"].values():
            self.assertEqual([x["order"] for x in card["actions"]], [1, 2, 3, 4, 5])

    def test_raw_refutation_question_and_assertion_are_only_candidates(self):
        texts = ["공동훈련 취소는 사실이 아닙니다.", "Was the joint exercise cancelled?", "The exercise was cancelled."]
        posts = [{**rows()[i], "id": str(i), "text": text} for i, text in enumerate(texts)]
        data = self.ingest(posts)
        self.assertEqual(len(data["playbook_raw_matches"]), 3)
        self.assertFalse(data["cases"])
        for item in self.matches(data):
            self.assertEqual(item["scenario_id"], "30")
            self.assertEqual(item["risk"], "UNASSESSED")
            self.assertEqual(item["state"], "candidate")
            self.assertFalse(item["automatic_execution"])
            self.assertTrue(all(s["authority"] and s["precondition"] for s in item["actions"]))

    def test_topic_and_change_must_be_in_same_post_and_word(self):
        posts = [{**rows()[i], "id": str(i), "text": text} for i, text in enumerate(["exercise is scheduled", "payment cancelled", "eventual cancellation"])]
        self.assertFalse(self.matches(self.ingest(posts)))

    def test_repeat_network_and_single_breaking_news_boundary(self):
        data = self.ingest(rows())
        self.assertEqual([p["scenario_id"] for p in self.matches(data)], ["17"])
        self.assertEqual(len(self.matches(data)[0]["evidence_post_ids"]), 6)
        fresh = Runtime(self.folder/"fresh.db", RawOnlyEmbedder(self.folder/"fresh.db"), clock=lambda: self.now, playbook_path=self.book)
        fresh.ingest(rows(rounds=1), stamp(self.now))
        self.assertFalse(self.matches(fresh.dashboard()))

    def test_multilingual_requires_same_cluster_and_valid_reported_tags(self):
        posts = [{**rows()[0], "id": "ko", "language_hint": "KO"}, {**rows()[1], "id": "en", "lang": "en-US"}]
        self.ingest(posts)
        data = self.cluster(["same", "same"])
        plans = data["cases"][0]["response_plans"]
        self.assertEqual([p["scenario_id"] for p in plans], ["22"])
        self.assertEqual(data["cases"][0]["languages"], ["en", "ko"])
        self.assertEqual({t["source_field"] for t in plans[0]["observations"]["language_tags"]}, {"language_hint", "lang"})

    def test_different_clusters_do_not_become_multilingual_claim(self):
        self.ingest([{**rows()[0], "language_hint": "ko"}, {**rows()[1], "language_hint": "en"}])
        data = self.cluster(["one", "two"])
        self.assertFalse(self.matches(data))

    def test_unknown_or_same_language_variants_are_not_two_languages(self):
        for tag in ("unknown", "und", "", "mul", "zxx", "KO-kr"):
            with self.subTest(tag=tag):
                self.assertIsNone(language({"language_hint": tag})[0]) if tag != "KO-kr" else self.assertEqual(language({"language_hint": tag})[0], "ko")
        self.ingest([{**rows()[0], "language_hint": "ko"}, {**rows()[1], "language_hint": "KO-kr"}])
        self.assertFalse(self.matches(self.cluster(["same", "same"])))

    def test_workbook_reload_changes_actions_and_preserves_version_history(self):
        data = self.ingest([{**rows()[0], "text": "공동훈련 취소설"}])
        old = self.matches(data)[0]
        count = self.query("SELECT COUNT(*) FROM playbook_history")[0][0]
        restarted = Runtime(self.db, RawOnlyEmbedder(self.db), clock=lambda: self.now, playbook_path=self.book)
        self.assertEqual(self.matches(restarted.dashboard()), self.matches(data))
        self.assertEqual(self.query("SELECT COUNT(*) FROM playbook_history")[0][0], count)
        self.book.write_bytes(edited(self.content, {"xl/worksheets/sheet2.xml": {"F151": "수정된 첫 확인 절차"}}))
        # Scenario 30 starts at row 151: 6 + 29*5.
        self.runtime.reload_playbook()
        current = self.matches(self.runtime.dashboard())[0]
        self.assertEqual(current["actions"][0]["action"], "수정된 첫 확인 절차")
        self.assertNotEqual(current["workbook_hash"], old["workbook_hash"])
        self.assertEqual(len(self.query("SELECT * FROM playbook_versions")), 2)
        history = [json.loads(r[0]) for r in self.query("SELECT payload_json FROM playbook_history ORDER BY seq")]
        self.assertEqual(history[0]["actions"], old["actions"])
        self.assertNotEqual(data["snapshot_id"], self.runtime.dashboard()["snapshot_id"])

    def test_disabled_rule_and_threshold_edit_re_evaluate_same_cutoff(self):
        data = self.ingest(rows())
        self.book.write_bytes(edited(self.content, {"xl/worksheets/sheet7.xml": {"F6": "4"}}))
        self.runtime.reload_playbook()
        self.assertFalse(self.matches(self.runtime.dashboard()))
        self.assertEqual(data["analysis_as_of"], self.runtime.dashboard()["analysis_as_of"])
        self.book.write_bytes(edited(self.content, {"xl/worksheets/sheet7.xml": {"C6": "false"}}))
        self.runtime.reload_playbook()
        self.assertFalse(self.matches(self.runtime.dashboard()))
        self.assertEqual(self.runtime.dashboard()["playbook"]["enabled_rule_count"], 2)
        self.assertEqual(self.query("SELECT active FROM playbook_history ORDER BY seq DESC LIMIT 1")[0][0], 0)

    def test_invalid_workbook_disables_candidates_without_disabling_behavior(self):
        self.ingest(rows())
        self.book.write_bytes(b"corrupt")
        self.runtime.reload_playbook()
        data = self.runtime.dashboard()
        self.assertEqual(data["playbook"]["status"], "error")
        self.assertFalse(self.matches(data))
        self.assertEqual(len(data["investigations"]), 1)
        self.book.unlink()
        self.runtime.reload_playbook()
        self.assertEqual(self.runtime.dashboard()["playbook"]["status"], "error")

    def test_invalid_conditions_ids_and_duplicate_steps_rejected(self):
        edits = [
            {"xl/worksheets/sheet7.xml": {"D6": "arbitrary_python"}},
            {"xl/worksheets/sheet7.xml": {"B6": "99"}},
            {"xl/worksheets/sheet7.xml": {"E6": '["MADE_UP_CODE"]'}},
            {"xl/worksheets/sheet7.xml": {"A7": "REPEAT_NETWORK"}},
            {"xl/worksheets/sheet2.xml": {"B7": "1"}},
            {"xl/worksheets/sheet1.xml": {"A6": "1"}},
        ]
        for changes in edits:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_workbook(edited(self.content, changes))

    def test_formula_never_uses_cached_value(self):
        buffer = BytesIO()
        with ZipFile(BytesIO(self.content)) as source, ZipFile(buffer, "w") as dest:
            for info in source.infolist():
                data = source.read(info.filename)
                if info.filename == "xl/worksheets/sheet7.xml":
                    root = ET.fromstring(data)
                    node = root.find(".//s:c[@r='F6']", NS)
                    ET.SubElement(node, "{"+NS["s"]+"}f").text = "1+2"
                    data = ET.tostring(root)
                dest.writestr(info, data)
        with self.assertRaisesRegex(ValueError, "formulas unsupported"):
            parse_workbook(buffer.getvalue())

    def test_future_posts_not_matched_before_cutoff(self):
        post = {**rows()[0], "created_at": stamp(self.now+timedelta(minutes=2)), "text": "The exercise was cancelled"}
        data = self.ingest([post])
        self.assertFalse(self.matches(data))
        self.now += timedelta(hours=2)
        self.runtime.ingest([post], stamp(self.now))
        self.assertEqual(len(self.matches(self.runtime.dashboard())), 1)

    def test_local_preview_case_retains_raw_candidate(self):
        db = self.folder / "preview.db"
        runtime = Runtime(db, LexicalDemoEmbedder(), clock=lambda: self.now, local_preview=True, playbook_path=self.book)
        runtime.ingest([{**rows()[0], "text": "공동훈련 취소설"}], stamp(self.now))
        data = runtime.dashboard()
        self.assertEqual(len(data["cases"]), 1)
        self.assertFalse(data["unlinked_posts"])
        self.assertEqual([p["scenario_id"] for p in data["cases"][0]["response_plans"]], ["30"])


if __name__ == "__main__":
    unittest.main()
