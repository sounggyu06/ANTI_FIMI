"""Analyst-declared public vocabulary folders, not inferred events or stance labels."""
from collections import defaultdict
from datetime import timedelta
import json
import re


# These are visible analyst topic rules, not scenario IDs, account labels or truth data.
TOPICS = [
    ('FRONTLINE', '전선', (
        r'전선(?:\s*(?:상황|패배|방어|붕괴|돌파|소식)|이|은|에서|의)',
        r'\b(?:front[ -]?lines?|battle\s*front|defen[sc]e\s+lines?|defensive\s+sectors?)\b',
        r'\bfront\b.{0,80}\b(?:defen[sc]e|defensive|battle|troops|military)\b', r'前線|戦線|防衛線|战线|戰線|前线|防线|防線')),
    ('RETREAT_ORDER', '후퇴 명령', (
        r'후퇴\s*명령|전군.{0,20}(?:항복|철수|명령)|전면\s*철수|철수\s*(?:명령|발표)|통수권자',
        r'\b(?:retreat|withdrawal|surrender)\s+orders?\b|\b(?:army[ -]wide|entire\s+army|all\s+forces)\b.{0,60}\b(?:surrender|withdrawal|retreat)\b',
        r'\b(?:commander.in.chief|military\s+command)\b.{0,100}\b(?:surrender|withdrawal)\b',
        r'撤退命令|退却命令|全軍降伏|撤退令|撤军命令|撤軍命令|全军投降|全軍投降')),
    ('ALLIANCE_CLASH', '동맹 충돌', (
        r'동맹\s*(?:충돌|갈등|관계|관련|협력)|서로\s*교전|보급\s*조율|지원\s*분담\s*이견',
        r'\btroops\b.{0,35}\bfighting\s+each\s+other\b|\barmed\s+clash\s+between\b',
        r'\b(?:alliance|allied)\b.{0,60}\b(?:clash|tension|disagreement|cooperation|conflict)\b|\bsupply\s+coordination\b',
        r'同盟.{0,20}(?:衝突|対立|不和)|互いに交戦|盟友.{0,20}(?:冲突|衝突|交战|交戰)|联盟冲突|聯盟衝突')),
    ('DEPLOYED_FORCES', '파병군', (
        r'파병(?:군|부대|인력)|파견\s*(?:군|부대|병력)',
        r'\bdeployed\s+(?:units?|forces?|troops?|personnel)\b|\btroop\s+deployment\b',
        r'派遣軍|派遣部隊|派兵|駐留軍|派遣部队|驻军|駐軍')),
    ('MILITARY_FACILITIES', '군 시설', (
        r'(?<![가-힣])군\s*시설|군사\s*(?:시설|기지)|군\s*기지|군[·ㆍ]민간\s*시설',
        r'\bmilitary\s+(?:facilit(?:y|ies)|bases?|installations?)\b|\barmy\s+bases?\b',
        r'軍事施設|軍施設|軍事基地|军事设施|軍事設施|军事基地')),
    ('CIVILIAN_FACILITIES', '민간 시설', (
        r'민간\s*(?:기반\s*)?시설|병원|전력\s*(?:시설|망)|통신\s*(?:시설|망)',
        r'\bcivilian\s+(?:infrastructure|facilit(?:y|ies))\b|\bhospitals?\b',
        r'民間施設|民間インフラ|病院|民用设施|民用設施|民用基础设施|民用基礎設施|医院|醫院')),
    ('CIVILIAN_HARM', '민간 피해', (
        r'민간(?:인)?\s*(?:피해|사상자|희생|사망|부상)',
        r'\bcivilian\s+(?:harm|losses|casualties|deaths|injur(?:y|ies))\b',
        r'民間人.{0,8}(?:被害|死傷|死亡)|平民.{0,8}(?:伤亡|傷亡|死亡|损失|損失)|民間被害')),
    ('DISPLACEMENT', '피란', (
        r'피란(?:민)?|피난(?:민)?|대피소|난민',
        r'\b(?:displaced\s+(?:people|persons|civilians)|displacement|refugees?|shelters?|evacuation)\b',
        r'避難民|避難所|避難|難民|避难民|避难所|难民|流离失所|流離失所')),
    ('ECONOMY', '경제', (
        r'경제|금융기관|은행.{0,20}지급|물가',
        r'\beconom(?:y|ic)\b|\bbanks?\b.{0,40}\b(?:payments?|shutdown|closed|stop)', r'経済|金融機関|银行|銀行|经济|經濟')),
    ('INDUSTRY', '산업', (
        r'산업\s*(?:시설|생산|위기)|전체\s*산업|생산.{0,12}(?:중단|상태|영구)|공장\s*(?:가동|피해|파괴)',
        r'\bindustr(?:y|ial)\b|\bproduction\b.{0,40}\b(?:ended|stopp|halt|suspend)',
        r'産業施設|工業施設|生産停止|工业设施|工業設施|工业生产|工業生產|生产中断|生產中斷')),
]
RULES = [(code, title, [re.compile(pattern, re.IGNORECASE) for pattern in patterns]) for code, title, patterns in TOPICS]


def issue_groups(posts, material_groups):
    """Organize public posts under matching topic folders; preserve overlap.

    Only text, post IDs, timestamps and provided reference IDs are read. A
    multi-topic post does not join the topics or lend all of them to a reply.
    Unclassified posts remain available to the caller outside these folders.
    """
    from engine import parse_time, stamp

    indexed = {post['id']: post for post in posts}
    times = {pid: parse_time(post['created_at']) for pid, post in indexed.items()}
    order = lambda pid: (times[pid], pid)
    ordered = sorted(indexed, key=order)
    direct, parents = defaultdict(dict), defaultdict(set)
    for pid, post in indexed.items():
        for code, _, patterns in RULES:
            terms = sorted({match.group(0) for pattern in patterns for match in pattern.finditer(post['text'])})
            if terms:
                direct[pid][code] = {'post_id': pid, 'source': 'direct', 'rule_id': 'PUBLIC_TOPIC_VOCAB_V1:' + code,
                                     'matched_terms': terms}
        raw = json.loads(post['raw_json'])
        relations = raw.get('relations', []) if isinstance(raw, dict) else []
        if not isinstance(relations, list):
            continue
        for relation in relations:
            if not isinstance(relation, dict) or relation.get('type') not in ('quotes', 'reposts', 'replies_to'):
                continue
            target = relation.get('target_post_id')
            if isinstance(target, str) and target in indexed and target != pid and timedelta(0) <= times[pid] - times[target] <= timedelta(hours=24):
                parents[pid].add(target)

    # Monotone propagation discovers all competing parent topics before selecting
    # a single inherited topic; order cannot hide an ambiguous second parent.
    topics = {pid: set(direct[pid]) for pid in indexed}
    changed = True
    while changed:
        changed = False
        for pid in ordered:
            if direct[pid]:
                continue
            inherited = set().union(*(topics[target] for target in parents[pid])) if parents[pid] else set()
            if inherited != topics[pid]:
                topics[pid] = inherited
                changed = True
    matches = defaultdict(dict)
    for pid in ordered:
        if direct[pid]:
            matches[pid].update(direct[pid])
        elif len(topics[pid]) == 1:
            code = next(iter(topics[pid]))
            sources = sorted((target for target in parents[pid] if topics[target] == {code}), key=order)
            if sources:
                matches[pid][code] = {'post_id': pid, 'source': 'reference', 'rule_id': 'EXPLICIT_REFERENCE_TOPIC_V1',
                                      'matched_terms': [], 'target_post_id': sources[0], 'via_post_ids': sources}

    result = []
    for code, title, _ in RULES:
        ids = {pid for pid in indexed if code in matches[pid]}
        if not ids:
            continue
        children = []
        for material in material_groups:
            evidence = set(material['evidence_post_ids']) & ids
            if not evidence:
                continue
            child = {field: material[field] for field in ('id', 'kind', 'title', 'resource') if field in material}
            child['evidence_post_ids'] = sorted(evidence)
            related = set(material['evidence_post_ids']) - evidence
            if related:
                child['related_post_ids'] = sorted(related)
            children.append(child)
        first, last = min(times[pid] for pid in ids), max(times[pid] for pid in ids)
        result.append({'id': 'ISSUE_' + code, 'kind': 'ISSUE_TOPIC', 'resource': code, 'title': title,
                       'evidence_post_ids': sorted(ids), 'root_post_ids': [],
                       'first_seen': stamp(first), 'last_seen': stamp(last), 'utc_day': first.date().isoformat(),
                       'child_groups': sorted(children, key=lambda child: child['id']),
                       'issue_matches': [matches[pid][code] for pid in sorted(ids, key=order)],
                       'basis': ['분석가 지정 공개 어휘 규칙', '복수 쟁점 소속 허용·입장/진위 판정 없음'],
                       'rules_version': 'PUBLIC_TOPIC_VOCAB_V1'})
    return result
