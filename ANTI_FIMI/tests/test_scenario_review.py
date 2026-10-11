"""Conservative scenario routing with source actions, not propaganda verdicts."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from playbooks import DEFAULT_WORKBOOK, parse_workbook
import scenario_review
from scenario_review import evaluate_review, load_rules

NOW = datetime(2026, 10, 11, 4, tzinfo=timezone.utc)


def post(pid, text, offset=0, **raw):
    return {"id": pid, "account_id": "account:" + pid, "text": text,
            "created_at": (NOW + timedelta(seconds=offset)).isoformat(), **raw}


class ScenarioReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = parse_workbook(DEFAULT_WORKBOOK.read_bytes())

    def evaluate(self, posts, signals=()):
        return evaluate_review(self.book, posts, signals, NOW.isoformat(), "workbook-test")

    def test_catalog_preserves_all_40_workbook_titles_and_actions(self):
        data = self.evaluate([])
        self.assertEqual(len(data["catalog"]), 40)
        self.assertFalse(data["candidates"])
        catalog = {x["scenario_id"]: x for x in data["catalog"]}
        self.assertEqual(catalog["17"]["match_mode"], "behavior")
        self.assertEqual(catalog["30"]["match_mode"], "text_review")
        self.assertEqual(catalog["13"]["match_mode"], "manual")
        for sid, source in self.book["scenarios"].items():
            item = catalog[sid]
            self.assertEqual(item["title"], source["유형"])
            self.assertEqual(item["actions"], source["actions"])
            self.assertTrue(item["missing_inputs"])
            self.assertTrue(item["required_evidence"])
            self.assertFalse(item["automatic_execution"])

    def test_assertion_question_and_denial_aggregate_without_stance_verdict(self):
        posts = [post("a", "군 통수권자가 전군 항복이랑 전면 철수를 발표했다."),
                 post("b", "군 통수권자가 전군 항복이랑 전면 철수를 발표했다고?"),
                 post("c", "공식 확인: 전군 항복이나 철수 발표는 없다.")]
        data = self.evaluate(posts)
        self.assertEqual(len(data["candidates"]), 1)
        candidate = data["candidates"][0]
        self.assertEqual(candidate["scenario_id"], "33")
        self.assertEqual(candidate["evidence_post_ids"], ["a", "b", "c"])
        self.assertEqual(candidate["propaganda_status"], "unverified")
        self.assertEqual(candidate["risk"], "UNASSESSED")
        self.assertFalse(candidate["automatic_execution"])
        markers = {o["post_id"]: o["context_markers"] for o in candidate["observations"]["term_hits"]}
        self.assertIn("question", markers["b"])
        self.assertIn("denial", markers["c"])
        self.assertIn("공식 확인", posts[2]["text"])
        self.assertEqual(candidate["actions"], self.book["scenarios"]["33"]["actions"])

    def test_normal_sports_finance_and_keyword_alone_do_not_route(self):
        texts = ["Our team surrendered the lead. The coach ordered a substitution.",
                 "Stock investors withdraw savings after today's economic report.",
                 "은행에서 예금을 인출했다. 경제 위협이 크다.", "군사 소식입니다.",
                 "언론에 대한 위협을 조사합니다.", "kill that rumor", "attack that problem"]
        self.assertFalse(self.evaluate([post(str(i), t) for i, t in enumerate(texts)])["candidates"])

    def test_conditions_must_be_within_same_post(self):
        self.assertFalse(self.evaluate([post("a", "전군 상황을 확인 중입니다."),
                                        post("b", "철수하라는 얘기를 들었다.")])["candidates"])

    def test_24_hour_boundary_and_future_exclusion(self):
        text = "군 통수권자가 전군 항복이랑 전면 철수를 발표했다."
        candidate = self.evaluate([post("old", text, -86401), post("boundary", text, -86400),
                                   post("now", text), post("future", text, 1)])["candidates"][0]
        self.assertEqual(candidate["evidence_post_ids"], ["boundary", "now"])

    def test_no_hidden_label_or_role_classification(self):
        self.assertFalse(self.evaluate([post("x", "오늘 점심은 맛있다.", scenario_id="33",
            role="propagandist", raw_json=json.dumps({"ground_truth": "fake", "scenario_id": "33"}))])["candidates"])

    def test_literals_route_korean_english_japanese_and_chinese(self):
        texts = ["전군에 항복 명령을 내렸다고 합니다.", "The commander ordered troops to surrender.",
                 "司令官は全軍に降伏を命じた。", "总司令命令军队投降。"]
        candidate = self.evaluate([post(str(i), text) for i, text in enumerate(texts)])["candidates"][0]
        self.assertEqual(candidate["evidence_post_ids"], ["0", "1", "2", "3"])
        self.assertEqual(candidate["scenario_id"], "33")

    def test_behavior_is_separate_observed_corroboration_not_invented(self):
        posts = [post("a", "전군 항복을 발표했다.")]
        unrelated = {"id": "B1", "kind": "behavior_coordination", "evidence_post_ids": ["other"]}
        attention = {"id": "RB1", "kind": "resource_burst", "evidence_post_ids": ["a"]}
        candidate = self.evaluate(posts, [unrelated, attention])["candidates"][0]
        self.assertEqual(candidate["evidence_level"], "content_review")
        self.assertFalse(candidate["alert_ids"])
        matching = {"id": "B2", "kind": "behavior_coordination", "evidence_post_ids": ["a", "other"],
                    "reason_codes": ["REPEATED_TEMPORAL_COACTION"]}
        candidate = self.evaluate(posts, [matching])["candidates"][0]
        self.assertEqual(candidate["evidence_level"], "combined")
        self.assertEqual(candidate["alert_ids"], ["B2"])
        self.assertEqual(candidate["observations"]["behavior_overlap"][0]["overlap_post_ids"], ["a"])
        self.assertEqual(candidate["propaganda_status"], "unverified")

    def test_ids_evidence_and_order_are_restart_deterministic(self):
        posts = [post("z", "동맹의 충돌과 지원 중단이 보도됐다."), post("a", "전군 항복을 발표했다.")]
        first, second = self.evaluate(posts), self.evaluate(list(reversed(posts)))
        self.assertEqual(first, second)
        self.assertEqual([x["id"] for x in first["candidates"]], ["SR_33", "SR_36"])

    def test_all_8_rules_route_with_actual_term_evidence(self):
        texts = {"24": "해당 기자님 이 내용을 보도해 주세요.", "27": "그 기자를 찾아가 응징하자.",
                 "31": "대피소가 폐쇄됐으니 다른 곳으로 이동하세요.", "32": "투표소가 변경되었습니다.",
                 "33": "전군 항복 명령을 발표했다.", "34": "오염된 수돗물은 마시지 마세요.",
                 "36": "동맹 연합군 사이에 충돌이 발생했다.", "37": "팩트체크: 이 사건의 영상은 배우가 연기한 조작이다."}
        data = self.evaluate([post(sid, text) for sid, text in texts.items()])
        self.assertEqual({c["scenario_id"] for c in data["candidates"]}, set(texts))
        for candidate in data["candidates"]:
            for obs in candidate["observations"]["term_hits"]:
                for alternatives in obs["matched_terms"]:
                    self.assertTrue(alternatives)
                    self.assertTrue(all(term.casefold() in texts[obs["post_id"]].casefold() for term in alternatives))
            self.assertTrue(candidate["missing_checks"])

    def test_invalid_config_fails_closed_without_invented_catalog(self):
        valid = load_rules()
        bad_values = [{}, {"version": 1, "rules": [None]}, {"version": 1, "rules": [{"scenario_id": []}]}]
        duplicate = deepcopy(valid)
        duplicate["rules"].append(deepcopy(duplicate["rules"][0]))
        bad_values.append(duplicate)
        empty_clause = deepcopy(valid)
        empty_clause["rules"][0]["clauses_all"] = [["word"]]
        bad_values.append(empty_clause)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"rules.json"
            for bad in bad_values:
                path.write_text(json.dumps(bad), encoding="utf-8")
                with self.subTest(config=bad), self.assertRaises(ValueError):
                    load_rules(path)
            path.write_text("not-json", encoding="utf-8")
            with patch.object(scenario_review, "RULES_PATH", path), self.assertRaises(ValueError):
                self.evaluate([post("x", "전군 항복 명령")])

    def test_partial_workbook_does_not_silently_create_missing_scenarios(self):
        partial = deepcopy(self.book)
        del partial["scenarios"]["40"]
        with self.assertRaises(ValueError):
            evaluate_review(partial, [], [], NOW.isoformat(), "hash")

    def test_exact_rule_bytes_hash_is_attached_without_changing_load_interface(self):
        content = scenario_review.RULES_PATH.read_bytes()
        expected = hashlib.sha256(content).hexdigest()
        first = self.evaluate([post("a", "전군 항복을 발표했다.")])
        self.assertEqual(first["rules_hash"], expected)
        self.assertEqual(first["candidates"][0]["review_rules_hash"], expected)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"rules.json"
            changed = content + b"\n  "
            path.write_bytes(changed)
            self.assertEqual(load_rules(path), load_rules())
            with patch.object(scenario_review, "RULES_PATH", path):
                result = self.evaluate([post("a", "전군 항복을 발표했다.")])
            self.assertEqual(result["rules_hash"], hashlib.sha256(changed).hexdigest())
            self.assertNotEqual(result["rules_hash"], first["rules_hash"])


if __name__ == "__main__":
    unittest.main()
