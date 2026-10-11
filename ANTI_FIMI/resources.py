"""Deterministic evidence organization without models or inferred meaning."""
from collections import defaultdict
from datetime import timedelta
import json
import re
import unicodedata


def group_resources(posts, url_rows):
    from engine import canonical_url, key, parse_time, stamp, URL_RE

    indexed = {p['id']: p for p in posts}
    times = {pid: parse_time(p['created_at']) for pid, p in indexed.items()}
    order = lambda pid: (times[pid], pid)
    # Full equality only: retain negation, punctuation, case and article queries.
    texts = {pid: ' '.join(unicodedata.normalize('NFC', p['text']).split()) for pid, p in indexed.items()}
    resources = defaultdict(set)
    urls_by_post = defaultdict(set)
    labels, known_targets, declared_parents = {}, defaultdict(set), defaultdict(set)
    window = timedelta(hours=24)
    for row in url_rows:
        post = indexed.get(row['post_id'])
        url = canonical_url(row['url'])
        if post is not None and url:
            urls_by_post[post['id']].add(url)
            identity = ('SHARED_URL', url)
            resources[identity].add(post['id'])
            labels[identity] = '동일 URL · ' + url
    for post in indexed.values():
        text = texts[post['id']]
        for value in URL_RE.findall(text):
            url = canonical_url(value)
            if url:
                urls_by_post[post['id']].add(url)
        if len(text) >= 20:
            identity = ('EXACT_TEXT', text)
            resources[identity].add(post['id'])
            labels[identity] = '동일 문구 · ' + text[:90]
        raw = json.loads(post['raw_json'])
        relations = raw.get('relations', []) or []
        if not isinstance(relations, list):
            continue
        for relation in relations:
            if not isinstance(relation, dict) or relation.get('type') not in ('quotes', 'reposts', 'replies_to'):
                continue
            target = relation.get('target_post_id')
            if not isinstance(target, str) or not target or target == post['id']:
                continue
            declared_parents[post['id']].add(target)
            original = indexed.get(target)
            if original is not None and not timedelta(0) <= times[post['id']] - times[target] <= window:
                # A known future/too-old original cannot become a flow edge.
                continue
            identity = ('SHARED_REFERENCE', target)
            resources[identity].add(post['id'])
            labels[identity] = '원본 참조 · ' + target
            if original is not None:
                resources[identity].add(target)
                known_targets[post['id']].add(target)

    children = []
    for identity, ids in sorted(resources.items()):
        # Fixed 24h spans avoid both UTC-midnight splits and unlimited chaining.
        batches = []
        for pid in sorted(ids, key=order):
            if not batches or times[pid] - times[batches[-1][0]] > window:
                batches.append([])
            batches[-1].append(pid)
        for batch in batches:
            if len(batch) < 2:
                continue
            children.append({'id': key('RG_', [*identity, batch[0]]), 'kind': identity[0],
                             'resource': identity[1], 'utc_day': times[batch[0]].date().isoformat(),
                             'title': labels[identity], 'evidence_post_ids': sorted(batch)})

    parents = {pid: pid for pid in indexed}

    def find(pid):
        while parents[pid] != pid:
            parents[pid] = parents[parents[pid]]
            pid = parents[pid]
        return pid

    def join(ids):
        ids = sorted(ids, key=order)
        root = find(ids[0])
        for pid in ids[1:]:
            other = find(pid)
            if root != other:
                parents[other] = root

    for child in children:
        if child['kind'] == 'SHARED_REFERENCE':
            join(child['evidence_post_ids'])

    def components():
        result = defaultdict(set)
        for pid in indexed:
            result[find(pid)].add(pid)
        return result

    def roots(ids):
        observed = [pid for pid in ids if not (known_targets[pid] & ids)]
        # A reference cycle has no causal root; choose a reproducible observed anchor.
        return sorted(observed or ids, key=order)

    initial = components()
    for sentence_only in (False, True):
        root_texts = defaultdict(list)
        for ids in initial.values():
            anchors = roots(ids)
            if any(declared_parents[pid] for pid in anchors):
                # Missing/invalid parents do not turn a copied reply into an original.
                continue
            signatures = set()
            for pid in anchors:
                text = texts[pid]
                if sentence_only:
                    match = re.search(r'[。！？]|[.!?](?=\s|$)', text)
                    text = text[:match.end()] if match else ''
                signatures.add((text, tuple(sorted(urls_by_post[pid]))))
            if len(signatures) == 1:
                signature = next(iter(signatures))
                if len(signature[0]) >= 40:
                    root_texts[signature].append((anchors[0], ids))
        for (text, _), candidates in root_texts.items():
            batches = []
            for anchor, ids in sorted(candidates, key=lambda item: order(item[0])):
                if not batches or times[anchor] - times[batches[-1][0][0]] > window:
                    batches.append([])
                batches[-1].append((anchor, ids))
            for batch in batches:
                # Match original roots, never copied comments inside other flows.
                # Equal URL sets also prevent a root with two articles bridging them.
                if len(batch) >= 2 and any(len(ids) >= 2 for _, ids in batch):
                    if not sentence_only:
                        join({pid for _, ids in batch for pid in ids})
                    if sentence_only:
                        evidence = sorted({pid for _, ids in batch for pid in roots(ids)})
                        children.append({'id': key('RG_', ['ROOT_SENTENCE_MATCH', text, min(evidence, key=order)]),
                            'kind': 'ROOT_SENTENCE_MATCH', 'resource': text,
                            'title': '원문 첫 완결 문장 일치 · ' + text[:90],
                            'evidence_post_ids': evidence})

    flows, membership = [], {}
    for ids in sorted(components().values(), key=lambda value: order(min(value, key=order))):
        if len(ids) < 2:
            continue
        anchors = roots(ids)
        anchor = anchors[0]
        unresolved = sorted({c['resource'] for c in children
            if c['kind'] == 'SHARED_REFERENCE' and c['resource'] not in indexed
            and set(c['evidence_post_ids']) <= ids})
        basis = []
        if any(known_targets[pid] & ids for pid in ids):
            basis.append('명시적 원본 참조 체인(각 알려진 원본과 24시간 이내)')
        if unresolved:
            basis.append('동일 미확인 원본 ID 참조(참조 게시물 관측 간격 24시간 이내)')
        if len(anchors) >= 2 and len({texts[pid] for pid in anchors}) == 1 and len(texts[anchor]) >= 40:
            basis.append('부모 없는 원문 전체 일치(40자 이상·원문 관측 간격 24시간 이내)')
        if any(c['kind'] == 'ROOT_SENTENCE_MATCH' and set(c['evidence_post_ids']) & ids for c in children):
            basis.append('관련 원문 첫 문장 일치(상위 흐름 병합 근거로 사용하지 않음)')
        flow = {'id': key('RG_', ['REFERENCE_FLOW', anchor]), 'kind': 'REFERENCE_FLOW',
                'resource': anchor, 'utc_day': times[anchor].date().isoformat(),
                'title': '관측 자료 흐름 · ' + (texts[anchor][:90] or anchor),
                'evidence_post_ids': sorted(ids), 'root_post_ids': anchors,
                'first_seen': stamp(min(times[pid] for pid in ids)),
                'last_seen': stamp(max(times[pid] for pid in ids)),
                'child_groups': [],
                'basis': basis, 'reference_span_hours': 24,
                'unresolved_target_post_ids': unresolved}
        flows.append(flow)
        for pid in ids:
            membership[pid] = flow

    standalone = []
    for child in children:
        ids = set(child['evidence_post_ids'])
        local = defaultdict(set)
        for pid in ids:
            if pid in membership:
                local[membership[pid]['id']].add(pid)
        for flow_id, subset in local.items():
            flow = membership[next(iter(subset))]
            nested = {k: child[k] for k in ('id', 'kind', 'title', 'resource')}
            nested['evidence_post_ids'] = sorted(subset)
            if subset != ids:
                nested['related_post_ids'] = sorted(ids - subset)
            flow['child_groups'].append(nested)
        if child['kind'] == 'EXACT_TEXT':
            remaining = ids - membership.keys()
            if remaining:
                # Keep the full copy evidence when even one original is outside
                # all reference flows; no source post disappears from coverage.
                item = {**child, 'root_post_ids': sorted(remaining, key=order),
                        'child_groups': [{k: child[k] for k in ('id', 'kind', 'title', 'evidence_post_ids')}]}
                standalone.append(item)
        elif child['kind'] == 'SHARED_URL' and not any(ids <= set(f['evidence_post_ids']) for f in flows):
            standalone.append({**child, 'root_post_ids': [min(ids, key=order)], 'child_groups': []})
    for flow in flows:
        flow['child_groups'].sort(key=lambda child: (child['kind'], child['id']))
    return sorted(flows + standalone, key=lambda group: group['id'])
