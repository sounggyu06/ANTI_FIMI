"""Excel-backed review candidates. No truth, attribution or response execution."""
from collections import defaultdict
from functools import lru_cache
import hashlib
from io import BytesIO
import json
from pathlib import Path
import posixpath
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile, BadZipFile

DEFAULT_WORKBOOK = Path(__file__).resolve().parent.parent / "ANTI_FIMI_운용표_v1.0.xlsx"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
RULE_HEADERS = ["rule_id", "scenario_id", "enabled", "match_kind", "signal_codes_all", "min_episodes",
                "min_resources", "min_languages", "topic_terms_any", "change_terms_any", "interpretation"]
SCHEMA = """
CREATE TABLE IF NOT EXISTS playbook_versions (
 workbook_hash TEXT PRIMARY KEY, loaded_at TEXT NOT NULL, path TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS playbook_matches (
 id TEXT PRIMARY KEY, active INTEGER NOT NULL, entity_id TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS playbook_history (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT NOT NULL, evaluated_at TEXT NOT NULL,
 active INTEGER NOT NULL, payload_json TEXT NOT NULL);
"""


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def language(raw):
    """Use reported tags only; no language/stance inference from text."""
    for field in ("language_hint", "language", "lang"):
        value = raw.get(field)
        if isinstance(value, str):
            tag = value.strip().lower().replace("_", "-")
            if re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})*", tag) and tag not in {"und", "unk", "zxx", "mul"}:
                return tag.split("-")[0], field
    return None, None


def read_sheets(content):
    """Read ordinary XLSX cells using stdlib; formulas are never executed/cached."""
    with ZipFile(BytesIO(content)) as archive:
        if sum(x.file_size for x in archive.infolist()) > 20_000_000:
            raise ValueError("Workbook uncompressed size exceeds 20 MB")
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(t.text or "" for t in si.findall(".//s:t", NS)) for si in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        rels = {x.attrib["Id"]: x.attrib["Target"] for x in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        sheets = {}
        for sheet in ET.fromstring(archive.read("xl/workbook.xml")).findall("s:sheets/s:sheet", NS):
            rid = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
            target = rels[rid]
            name = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            cells = {}
            for cell in ET.fromstring(archive.read(name)).findall("s:sheetData/s:row/s:c", NS):
                ref = cell.attrib["r"]
                if cell.find("s:f", NS) is not None:
                    raise ValueError(f"{sheet.attrib['name']}!{ref}: formulas unsupported; enter a literal value")
                value = cell.findtext("s:v", default="", namespaces=NS)
                kind = cell.attrib.get("t")
                if kind == "s":
                    value = strings[int(value)]
                elif kind == "inlineStr":
                    value = "".join(t.text or "" for t in cell.findall("s:is//s:t", NS))
                elif kind == "b":
                    value = value == "1"
                elif kind == "e":
                    raise ValueError(f"{sheet.attrib['name']}!{ref}: Excel error {value}")
                cells[ref] = value
            sheets[sheet.attrib["name"]] = cells
        return sheets


def rows(sheets, name, headers):
    if name not in sheets:
        raise ValueError(f"Missing worksheet: {name}")
    cells = sheets[name]
    actual = [cells.get(f"{chr(65+i)}5", "") for i in range(len(headers))]
    def column_index(ref):
        index = 0
        for letter in ref[:-1]:
            index = index * 26 + ord(letter) - 64
        return index
    if actual != headers or any(re.fullmatch(r"[A-Z]+5", r) and column_index(r) > len(headers) and v for r, v in cells.items()):
        raise ValueError(f"{name}: row 5 headers must be {headers}")
    indexes = sorted({int(re.search(r"\d+$", r)[0]) for r, v in cells.items() if v != ""} - {1, 2, 3, 4, 5})
    return [dict(zip(headers, [cells.get(f"{chr(65+i)}{n}", "") for i in range(len(headers))])) for n in indexes]


def scenario_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{2}", value):
        raise ValueError(f"Scenario ID must be two text digits (e.g. 01): {value!r}")
    return value


def array(value, label):
    result = json.loads(value)
    if not isinstance(result, list) or not all(isinstance(x, str) and x.strip() for x in result):
        raise ValueError(f"{label}: JSON array of nonempty strings required")
    return result


@lru_cache(maxsize=4)
def parse_workbook(content):
    sheets = read_sheets(content)
    main = rows(sheets, "운용목록", ["ID", "유형", "잠재등급", "현재 활용 근거", "다음 검증", "대응 담당", "핵심 대응"])
    actions = rows(sheets, "대응절차", ["ID", "순서", "단계", "담당", "착수 조건", "수행할 일", "산출물", "완료 확인", "권한 경계"])
    rules = rows(sheets, "매칭규칙", RULE_HEADERS)
    catalog = {}
    for row in main:
        sid = scenario_id(row["ID"])
        if sid in catalog or any(not str(v).strip() for v in row.values()):
            raise ValueError(f"Duplicate/incomplete scenario: {sid}")
        if row["잠재등급"] not in {"LOW", "MEDIUM", "HIGH", "CRITICAL", "UNASSESSED"}:
            raise ValueError(f"Unknown potential risk: {sid}")
        catalog[sid] = {**row, "actions": []}
    if not catalog:
        raise ValueError("Empty scenario catalog")
    for row in actions:
        sid = scenario_id(row["ID"])
        if sid not in catalog or any(not str(v).strip() for v in row.values()):
            raise ValueError(f"Unknown/incomplete action: {sid}")
        order = int(row["순서"])
        if str(order) != str(row["순서"]):
            raise ValueError(f"Action order must be integer: {sid}")
        catalog[sid]["actions"].append({"order": order, "phase": row["단계"], "owner": row["담당"],
            "precondition": row["착수 조건"], "action": row["수행할 일"], "output": row["산출물"],
            "done_when": row["완료 확인"], "authority": row["권한 경계"]})
    for sid, item in catalog.items():
        item["actions"].sort(key=lambda x: x["order"])
        if [x["order"] for x in item["actions"]] != list(range(1, len(item["actions"])+1)) or not item["actions"]:
            raise ValueError(f"Duplicate/gapped/missing action order: {sid}")
    seen = set()
    known_codes = {"REPEATED_TEMPORAL_COACTION", "CROSS_RESOURCE_COORDINATION", "POPULARITY_ACTIVITY_ADJUSTED", "OBSERVED_RECIPROCAL_REFERENCES"}
    for rule in rules:
        sid = scenario_id(rule["scenario_id"])
        if sid not in catalog or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", rule["rule_id"]) or rule["rule_id"] in seen:
            raise ValueError(f"Unknown scenario or duplicate/invalid rule: {rule['rule_id']}")
        seen.add(rule["rule_id"])
        if rule["enabled"] not in (True, False, "true", "false", "TRUE", "FALSE", "1", "0"):
            raise ValueError(f"Invalid enabled value: {rule['rule_id']}")
        rule["enabled"] = rule["enabled"] in (True, "true", "TRUE", "1")
        kind = rule["match_kind"]
        if kind not in {"coordination", "multilingual", "topic_change"} or not isinstance(rule["interpretation"], str) or not rule["interpretation"].strip():
            raise ValueError(f"Unknown match_kind or empty interpretation: {rule['rule_id']}")
        for field in ("signal_codes_all", "topic_terms_any", "change_terms_any"):
            rule[field] = array(rule[field], field)
        if set(rule["signal_codes_all"]) - known_codes:
            raise ValueError(f"Unknown signal code: {rule['rule_id']}")
        required = {"coordination": ["min_episodes", "min_resources"], "multilingual": ["min_languages"], "topic_change": []}[kind]
        for field in ("min_episodes", "min_resources", "min_languages"):
            v = rule[field]
            if field in required:
                rule[field] = int(v)
                if str(rule[field]) != str(v) or rule[field] < 2:
                    raise ValueError(f"{field}: integer >=2 required")
            elif v != "":
                raise ValueError(f"Unused threshold {field}: {rule['rule_id']}")
        if kind == "coordination" and not rule["signal_codes_all"]:
            raise ValueError("coordination requires signal_codes_all")
        if kind == "topic_change" and (not rule["topic_terms_any"] or not rule["change_terms_any"]):
            raise ValueError("topic_change requires both term arrays")
        if kind != "coordination" and rule["signal_codes_all"] or kind != "topic_change" and (rule["topic_terms_any"] or rule["change_terms_any"]):
            raise ValueError(f"Unused matching conditions: {rule['rule_id']}")
    # Preserve all literal source cells, including passive risk and source mappings.
    return {"scenarios": catalog, "rules": rules, "sheets": sheets}


def contains(text, term):
    term = term.casefold()
    return bool(re.search(r"(?<![a-z])" + re.escape(term) + r"(?![a-z])", text)) if term.isascii() and term.isalpha() else term in text


def evaluate(book, posts, signals, parents, ai_clusters, as_of, workbook_hash):
    indexed = {p["id"]: {**dict(p), "raw": json.loads(p["raw_json"])} for p in posts}
    groups = defaultdict(set)
    for pid in indexed:
        for cluster in ai_clusters.get(pid, []):
            groups[cluster["cluster_id"]].add(pid)
    entities = [(cid, "ai", ids) for cid, ids in sorted(groups.items())]
    entities += [(p["id"], "behavior", set(p["evidence_post_ids"]) & indexed.keys()) for p in parents]
    covered = set().union(*(ids for _, _, ids in entities)) if entities else set()
    entities += [("raw:"+pid, "raw", {pid}) for pid in indexed if pid not in covered]
    matches = []
    for entity_id, entity_kind, ids in entities:
        for rule in book["rules"]:
            if not rule["enabled"]:
                continue
            evidence, observations, alert_ids = set(), {}, []
            kind = rule["match_kind"]
            if kind == "coordination":
                eligible = [s for s in signals if s["evidence_post_ids"] and set(s["evidence_post_ids"]) <= ids
                    and set(rule["signal_codes_all"]) <= set(s["reason_codes"])
                    and s["metrics"].get("independent_episodes", 0) >= rule["min_episodes"]
                    and s["metrics"].get("distinct_resources", 0) >= rule["min_resources"]]
                for s in eligible:
                    evidence.update(s["evidence_post_ids"])
                alert_ids = [s["id"] for s in eligible]
                observations = {"signals": [{"id": s["id"], "metrics": s["metrics"]} for s in eligible]}
            elif kind == "multilingual" and entity_kind == "ai":
                tags = [{"post_id": pid, "language": language(indexed[pid]["raw"])[0], "source_field": language(indexed[pid]["raw"])[1]} for pid in sorted(ids)]
                tags = [t for t in tags if t["language"]]
                if len({t["language"] for t in tags}) >= rule["min_languages"]:
                    evidence = {t["post_id"] for t in tags}
                    observations = {"language_tags": tags, "cluster_id": entity_id}
            elif kind == "topic_change":
                terms = []
                for pid in sorted(ids):
                    text = indexed[pid]["text"].casefold()
                    topics = [t for t in rule["topic_terms_any"] if contains(text, t)]
                    changes = [t for t in rule["change_terms_any"] if contains(text, t)]
                    if topics and changes:
                        evidence.add(pid)
                        terms.append({"post_id": pid, "topic_terms": topics, "change_terms": changes})
                observations = {"term_hits": terms}
            if not evidence:
                continue
            scenario = book["scenarios"][rule["scenario_id"]]
            identity = "PM_" + hashlib.sha256(encode([entity_id, rule["rule_id"]]).encode()).hexdigest()[:20]
            matches.append({"id": identity, "entity_id": entity_id, "entity_kind": entity_kind,
                "scenario_id": scenario["ID"], "title": scenario["유형"], "state": "candidate", "risk": "UNASSESSED",
                "potential_risk": scenario["잠재등급"], "rule_id": rule["rule_id"], "match_kind": kind,
                "reason": rule["interpretation"], "evidence_post_ids": sorted(evidence), "alert_ids": sorted(alert_ids),
                "observations": observations, "next_verification": scenario["다음 검증"], "actions": scenario["actions"],
                "workbook_hash": workbook_hash, "as_of": as_of, "automatic_execution": False})
    return matches


def update_playbook(connection, path, posts, signals, parents, ai_clusters, as_of, evaluated_at):
    """Called within the engine transaction. Invalid Excel disables only this layer."""
    previous = {r["id"]: dict(r) for r in connection.execute("SELECT * FROM playbook_matches WHERE active=1")}
    matches = []
    review_catalog = []
    status = {"path": str(path), "status": "error", "workbook_hash": None, "scenario_count": 0, "enabled_rule_count": 0}
    try:
        content = Path(path).read_bytes()
        if len(content) > 5_000_000:
            raise ValueError("Workbook exceeds 5 MB")
        digest = hashlib.sha256(content).hexdigest()
        book = parse_workbook(content)
        matches = evaluate(book, posts, signals, parents, ai_clusters, as_of, digest)
        connection.execute("INSERT OR IGNORE INTO playbook_versions VALUES(?,?,?,?)", (digest, evaluated_at, str(path), encode(book)))
        status.update(status="ready", workbook_hash=digest, scenario_count=len(book["scenarios"]),
            enabled_rule_count=sum(r["enabled"] for r in book["rules"]), error=None)
        mode = connection.execute("SELECT value FROM metadata WHERE key='pipeline_mode'").fetchone()
        if mode is not None and mode[0] == 'no-ai':
            status['disabled_rule_ids'] = [r['rule_id'] for r in book['rules'] if r['enabled'] and r['match_kind'] == 'multilingual']
            status['effective_enabled_rule_count'] = status['enabled_rule_count'] - len(status['disabled_rule_ids'])
            try:
                from scenario_review import evaluate_review
                review = evaluate_review(book, posts, signals, as_of, digest)
                review_catalog = review['catalog']
                matches.extend(review['candidates'])
                status.update(review_status='ready', review_rule_count=sum(c['match_mode'] == 'text_review' and c['scenario_id'] != '30' for c in review_catalog),
                              review_rules_hash=review['rules_hash'])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                status.update(review_status='error', review_error=f'내용 검토 규칙 적용 중지: {exc}')
    except (OSError, ValueError, KeyError, IndexError, TypeError, BadZipFile, ET.ParseError) as exc:
        status["error"] = f"운용표 적용 중지: {exc}"
    connection.execute("UPDATE playbook_matches SET active=0")
    active_ids = set()
    for match in matches:
        payload = encode(match)
        active_ids.add(match["id"])
        last = connection.execute("SELECT active,payload_json FROM playbook_history WHERE match_id=? ORDER BY seq DESC LIMIT 1", (match["id"],)).fetchone()
        if not last or not last["active"] or last["payload_json"] != payload:
            connection.execute("INSERT INTO playbook_history(match_id,evaluated_at,active,payload_json) VALUES(?,?,1,?)", (match["id"], evaluated_at, payload))
        connection.execute("INSERT OR REPLACE INTO playbook_matches VALUES(?,1,?,?)", (match["id"], match["entity_id"], payload))
    for mid in previous.keys() - active_ids:
        connection.execute("INSERT INTO playbook_history(match_id,evaluated_at,active,payload_json) VALUES(?,?,0,?)", (mid, evaluated_at, previous[mid]["payload_json"]))
    connection.execute("INSERT OR REPLACE INTO metadata VALUES('scenario_catalog',?)", (encode(review_catalog),))
    connection.execute("INSERT OR REPLACE INTO metadata VALUES('playbook_status',?)", (encode(status),))


def extend_snapshot(connection, metadata, data):
    data["playbook"] = json.loads(metadata.get("playbook_status", '{"status":"not_loaded"}'))
    matches = defaultdict(list)
    if "playbook_status" in metadata:
        for row in connection.execute("SELECT payload_json FROM playbook_matches WHERE active=1 ORDER BY id"):
            item = json.loads(row[0])
            matches[item["entity_id"]].append(item)
    for case in data["cases"] + data["investigations"]:
        case["response_plans"] = matches.get(case["id"], [])
        if case.get("source") in ('local_preview', 'resource'):
            case["response_plans"] += [m for post in case["posts"] for m in matches.get("raw:"+post["id"], [])]
    data['scenario_catalog'] = json.loads(metadata.get('scenario_catalog', '[]'))
    # Aggregate by review type, preserving full evidence across material/issue folders.
    grouped = defaultdict(list)
    for entries in matches.values():
        for item in entries:
            grouped[item['scenario_id']].append(item)
    candidates = []
    for sid, entries in sorted(grouped.items()):
        candidate = dict(entries[0])
        candidate.update(id='SC_' + sid, source_match_ids=sorted({e['id'] for e in entries}),
            evidence_post_ids=sorted({pid for e in entries for pid in e['evidence_post_ids']}),
            alert_ids=sorted({aid for e in entries for aid in e['alert_ids']}))
        candidate['observations'] = {'matches': [{'match_id': e['id'], 'rule_id': e['rule_id'],
            'evidence_post_ids': e['evidence_post_ids'], 'observations': e['observations']} for e in entries]}
        candidate.setdefault('observable_label', '반복·다중 자료 공동 확산 관측' if sid == '17' else '행사·일정 변경 관련 표현 검토' if sid == '30' else candidate['title'] + ' · 검토 후보')
        candidate.setdefault('missing_checks', [candidate['next_verification']])
        candidate.setdefault('evidence_level', 'behavior_observation' if sid == '17' else 'content_review')
        candidate.setdefault('propaganda_status', 'unverified')
        candidates.append(candidate)
    data['scenario_candidates'] = candidates
    # Expose raw-only candidates before any external AI result exists.
    data["playbook_raw_matches"] = [m for pid in [p["id"] for p in data["unlinked_posts"]] for m in matches.get("raw:"+pid, [])]
