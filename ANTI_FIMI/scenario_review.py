"""Transparent content review routing; never confirms propaganda, truth or intent."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re

RULES_PATH = Path(__file__).with_name("scenario_review_rules.json")
EXPECTED_IDS = {f"{i:02}" for i in range(1, 41)}
DISCLAIMER = "문구가 관련 검증 절차에 해당합니다. 질문·반박·공식 확인도 포함될 수 있으며 선전·허위·공작 여부는 미검증입니다."


def _time(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timezone required")
    return result.astimezone(timezone.utc)


def load_rules(path=None):
    return _load_rules_with_hash(path)[0]


def _load_rules_with_hash(path=None):
    content = Path(path or RULES_PATH).read_bytes()
    config = json.loads(content.decode("utf-8"))
    if not isinstance(config, dict) or config.get("version") != 1 or not isinstance(config.get("rules"), list):
        raise ValueError("Invalid scenario review rule configuration")
    seen, rule_ids = set(), set()
    for rule in config["rules"]:
        if not isinstance(rule, dict):
            raise ValueError("Rule must be an object")
        sid = rule.get("scenario_id")
        if not isinstance(sid, str) or sid not in EXPECTED_IDS or sid in seen or sid in {"17", "30"}:
            raise ValueError("Invalid/duplicate scenario or existing workbook rule")
        seen.add(sid)
        if not re.fullmatch(r"SR_[A-Z0-9_]{1,60}", str(rule.get("rule_id", ""))) or rule["rule_id"] in rule_ids:
            raise ValueError("Invalid review rule ID")
        rule_ids.add(rule["rule_id"])
        for field in ("observable_label", "interpretation"):
            if not isinstance(rule.get(field), str) or not rule[field].strip():
                raise ValueError(f"Missing {field}")
        clauses = rule.get("clauses_all")
        if not isinstance(clauses, list) or len(clauses) < 2:
            raise ValueError("At least two required term groups must match within one post")
        for terms in [*clauses, rule.get("missing_checks")]:
            if not isinstance(terms, list) or not terms or any(not isinstance(t, str) or not t.strip() for t in terms):
                raise ValueError("Nonempty literal term/check arrays required")
    return config, hashlib.sha256(content).hexdigest()


def _hits(text, terms):
    folded = text.casefold()
    return [term for term in terms if term.casefold() in folded and
            (not term.isascii() or re.search(r"(?<![a-z])" + re.escape(term.casefold()) + r"(?![a-z])", folded))]


def _markers(text):
    result = []
    if "?" in text or "？" in text or _hits(text, ["의문", "맞아", "확인 중", "궁금", "is it true", "does this", "本当", "真的吗"]):
        result.append("question")
    if _hits(text, ["아닙", "아니", "반박", "거짓", "없다", "허위", "부인", "사실무근", "false", "not true", "denied", "no evidence", "否定", "不是", "不实"]):
        result.append("denial")
    if any(c in text for c in ('"', '“', '”', '「', '」')) or _hits(text, ["주장", "봤", "글 봤", "했다고", "돌던데", "according to", "claimed", "と報道", "声称"]):
        result.append("quoted")
    return result


def evaluate_review(book, posts, signals, as_of, workbook_hash):
    """Return catalog and stable per-scenario candidates from visible text only.

    All clauses must occur in the SAME post. Context flags are literal cues, not
    stance inference. Behavior may corroborate a shared post, never prove intent.
    Configuration failures raise ValueError for the caller to disable this module.
    """
    config, rules_hash = _load_rules_with_hash()
    if set(book.get("scenarios", {})) != EXPECTED_IDS:
        raise ValueError("Scenario review requires the workbook's complete 40-entry catalog")
    rules = {r["scenario_id"]: r for r in config["rules"]}
    cutoff = _time(as_of)
    lower = cutoff - timedelta(hours=24)
    visible = {}
    for record in posts:
        post = dict(record)
        if lower <= _time(post["created_at"]) <= cutoff:
            visible[post["id"]] = post
    candidates, catalog = [], []
    for sid, scenario in sorted(book["scenarios"].items()):
        rule = rules.get(sid)
        mode = "text_review" if rule or sid == "30" else "behavior" if sid == "17" else "manual"
        missing = rule["missing_checks"] if rule else [scenario["다음 검증"]]
        catalog.append({"scenario_id": sid, "title": scenario["유형"], "match_mode": mode,
            "observable_label": rule["observable_label"] if rule else scenario["유형"] + " · 검토 절차",
            "required_evidence": ["동일 게시물 안에서 각 조건군의 문구가 함께 관측됨"] if rule else
                ["반복 행동 엔진의 독립 에피소드·다중 자원 근거"] if sid == "17" else
                ["운용표의 행사·변경 문구 규칙"] if sid == "30" else ["분석가가 확인한 원본·외부 검증 자료"],
            "missing_inputs": list(missing), "potential_risk": scenario["잠재등급"],
            "next_verification": scenario["다음 검증"], "actions": scenario["actions"],
            "automatic_execution": False, "propaganda_status": "unverified"})
        if not rule:
            continue
        observations = []
        for pid, post in sorted(visible.items()):
            hits = [_hits(post["text"], terms) for terms in rule["clauses_all"]]
            if all(hits):
                observations.append({"post_id": pid, "rule_id": rule["rule_id"], "matched_terms": hits,
                    "context_markers": _markers(post["text"])})
        if not observations:
            continue
        evidence = {o["post_id"] for o in observations}
        overlapping = []
        for signal in signals:
            if signal.get("kind") != "behavior_coordination":
                continue
            signal_ids = set(signal.get("evidence_post_ids", []))
            if signal_ids & evidence:
                overlapping.append({"signal_id": signal["id"], "overlap_post_ids": sorted(signal_ids & evidence),
                    "reason_codes": signal.get("reason_codes", [])})
        candidates.append({"id": "SR_" + sid, "entity_id": "scenario:" + sid, "entity_kind": "content_review",
            "scenario_id": sid, "title": scenario["유형"], "observable_label": rule["observable_label"],
            "state": "candidate", "risk": "UNASSESSED", "potential_risk": scenario["잠재등급"],
            "match_kind": "text_review", "rule_id": rule["rule_id"],
            "reason": rule["interpretation"] + " " + DISCLAIMER,
            "evidence_post_ids": sorted(evidence),
            "account_ids": sorted({visible[pid]["account_id"] for pid in evidence}),
            "alert_ids": sorted(x["signal_id"] for x in overlapping),
            "evidence_level": "combined" if overlapping else "content_review",
            "observations": {"term_hits": observations, "behavior_overlap": overlapping},
            "missing_checks": list(rule["missing_checks"]),
            "next_verification": scenario["다음 검증"], "actions": scenario["actions"],
            "workbook_hash": workbook_hash, "as_of": as_of,
            "review_rules_hash": rules_hash,
            "propaganda_status": "unverified", "automatic_execution": False})
    return {"catalog": catalog, "candidates": candidates, "rules_hash": rules_hash}
