"""Early attention for observed dissemination; never a coordination verdict."""
from collections import Counter
from datetime import timedelta
import json

PARAMETERS = {'window_seconds': 60, 'lookback_hours': 24, 'min_posts': 12,
              'min_accounts': 6, 'min_linked_posts': 6, 'calibrated': False}


def resource_bursts(groups, posts, as_of, previous=()):
    from engine import key, parse_time, stamp

    cutoff = parse_time(as_of) if isinstance(as_of, str) else as_of
    indexed = {p['id']: p for p in posts if parse_time(p['created_at']) <= cutoff}
    times = {pid: parse_time(p['created_at']) for pid, p in indexed.items()}
    lower = cutoff - timedelta(hours=PARAMETERS['lookback_hours'])
    window = timedelta(seconds=PARAMETERS['window_seconds'])
    linked = set()
    for pid, p in indexed.items():
        relations = json.loads(p['raw_json']).get('relations', []) or []
        if not isinstance(relations, list):
            continue
        for relation in relations:
            if not isinstance(relation, dict) or relation.get('type') not in ('quotes', 'reposts', 'replies_to'):
                continue
            target = relation.get('target_post_id')
            if isinstance(target, str) and target != pid and target in times and timedelta(0) <= times[pid] - times[target] <= timedelta(hours=24):
                linked.add(pid)
    alerts = []
    previous = sorted(previous, key=lambda a: (a['first_triggered_at'], a['id']))
    retained_ids = set()
    current_group_ids = {g['id'] for g in groups}
    for group in groups:
        shared = set(linked)
        # Direct URL or exact-text replication is also observable material sharing.
        for evidence in (group.get('child_groups') or [group]):
            if evidence['kind'] in ('SHARED_URL', 'EXACT_TEXT'):
                shared.update(evidence['evidence_post_ids'])
        ordered = sorted((indexed[pid] for pid in set(group['evidence_post_ids'])
                          if pid in indexed and lower <= times[pid]),
                         key=lambda p: (times[p['id']], p['id']))
        accounts, left, linked_count = Counter(), 0, 0
        first, latest, peak = None, None, None
        for right, post in enumerate(ordered):
            accounts[post['account_id']] += 1
            linked_count += post['id'] in shared
            while times[ordered[left]['id']] < times[post['id']] - window:
                expired = ordered[left]
                accounts[expired['account_id']] -= 1
                if not accounts[expired['account_id']]:
                    del accounts[expired['account_id']]
                linked_count -= expired['id'] in shared
                left += 1
            count = right - left + 1
            if count < PARAMETERS['min_posts'] or len(accounts) < PARAMETERS['min_accounts'] or linked_count < PARAMETERS['min_linked_posts']:
                continue
            selected = ordered[left:right + 1]
            observation = {'start': times[selected[0]['id']], 'end': times[post['id']],
                           'posts': selected, 'accounts': len(accounts), 'linked': linked_count}
            if first is None:
                first = observation
            latest = observation
            if peak is None or (count, len(accounts)) > (len(peak['posts']), peak['accounts']):
                peak = observation
        if first is None:
            continue
        evidence = peak['posts']
        current = [p for p in ordered if cutoff - window <= times[p['id']] <= cutoff]
        current_accounts = len({p['account_id'] for p in current})
        current_linked = sum(p['id'] in shared for p in current)
        active = (len(current) >= PARAMETERS['min_posts'] and current_accounts >= PARAMETERS['min_accounts']
                  and current_linked >= PARAMETERS['min_linked_posts'])
        group_ids = {p['id'] for p in ordered}
        # Preserve notification identity when a missing original arrives or two
        # observed flows merge. Membership overlap preserves identity, not grouping.
        preserved = next((a for a in previous if a['id'] not in retained_ids
            and parse_time(a['last_seen']) >= lower
            and (a['group_id'] == group['id'] or (a['group_id'] not in current_group_ids and
                 len(group_ids & set(a.get('group_evidence_post_ids', a['evidence_post_ids']))) >=
                 max(2, len(a.get('group_evidence_post_ids', a['evidence_post_ids'])) * .5)))), None)
        identity = preserved['id'] if preserved else key('RB_', [group['id'], stamp(first['end'])])
        retained_ids.add(identity)
        alerts.append({'id': identity, 'group_id': group['id'], 'kind': 'resource_burst',
            'group_evidence_post_ids': sorted(group_ids),
            'label': '자료 확산 조기 주의', 'priority': 'review_medium',
            'phase': 'active' if active else 'historical',
            'summary': f"60초 안에 게시물 {len(evidence)}개·계정 {peak['accounts']}개가 관측됐습니다. 정상 속보·반박 확산도 포함될 수 있으며 반복 조정은 미확인입니다.",
            'reason_codes': ['RAPID_MULTI_ACCOUNT_DIFFUSION', 'OBSERVED_MATERIAL_LINKS', 'COORDINATION_UNCONFIRMED'],
            'reason_labels': ['60초 관측창에서 게시물 12개 이상·계정 6개 이상',
                              '관측 원문 참조 또는 동일 자료 공유 게시물 6개 이상',
                              '조기 검토용 미보정 기준 · 반복 조정·허위성 미확인'],
            'evidence_post_ids': sorted(p['id'] for p in evidence),
            'account_ids': sorted({p['account_id'] for p in evidence}),
            'first_seen': stamp(first['start']), 'last_seen': stamp(latest['end']),
            'first_triggered_at': stamp(first['end']), 'last_triggered_at': stamp(latest['end']),
            'metrics': {'window_seconds': 60, 'post_count': len(evidence), 'account_count': peak['accounts'],
                        'linked_post_count': peak['linked'], 'current_post_count': len(current),
                        'current_account_count': current_accounts, 'first_triggered_at': stamp(first['end']),
                        'peak_window_start': stamp(peak['start']), 'peak_window_end': stamp(peak['end'])}})
    return sorted(alerts, key=lambda a: (a['first_triggered_at'], a['id']))
