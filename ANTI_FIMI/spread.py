"""Observed post-time spread, independent of truth, intent and risk assessment."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import math

from engine import parse_time, stamp


def spread_metrics(posts, as_of, observed_start=None):
    cutoff = parse_time(as_of) if isinstance(as_of, str) else as_of
    start = parse_time(observed_start) if isinstance(observed_start, str) else observed_start
    current_start = cutoff - timedelta(minutes=5)
    previous_start = cutoff - timedelta(minutes=10)
    unique = {post['id']: post for post in posts}
    timed = [(parse_time(post['created_at']), post['account_id']) for post in unique.values()]
    current = [(time, account) for time, account in timed if current_start < time <= cutoff]
    previous = [(time, account) for time, account in timed if previous_start < time <= current_start]
    current_accounts = len({account for _, account in current})
    previous_accounts = len({account for _, account in previous})
    n, before = len(current), len(previous)
    baseline_ready = start is not None and start <= previous_start
    if not baseline_ready:
        state = 'insufficient'
    elif before >= 5 and n <= before * .7 and before - n >= 3:
        state = 'declining'
    elif n < 5 or current_accounts < 3:
        state = 'low_volume'
    elif n >= max(8, before * 2) and current_accounts >= previous_accounts:
        state = 'surging'
    elif n >= before * 1.3 and n - before >= 3 and current_accounts >= previous_accounts:
        state = 'accelerating'
    else:
        state = 'steady'
    plot = _plot_history(timed, cutoff, start)
    return {'state': state, 'as_of': stamp(cutoff), 'window_minutes': 5,
            'current_post_count': n, 'previous_post_count': before,
            'current_account_count': current_accounts, 'previous_account_count': previous_accounts,
            'baseline_ready': baseline_ready, **plot,
            'basis': '수집된 게시물의 게시 시각 기준. 자료 범위는 수집의 연속성·완전성을 보장하지 않음.',
            'calibrated': False}


def _plot_history(timed, cutoff, observed_start):
    """Keep all selected post history with <=120 UTC-aligned plot buckets.

    Buckets are [time, time + bucket_seconds), with the as_of instant included
    in the final bucket. `end` clips that bucket to as_of. `partial` marks a
    bucket clipped by the first selected post or as_of; `partial_last` marks
    the still-open final bucket. `observed` means at least one post was seen,
    while `within_observed_range` keeps the separate collection-start hint.
    Zero posts never establish complete collection or absence of activity.
    """
    visible = [(time, account) for time, account in timed if time <= cutoff]
    if not visible:
        return {'history': [], 'bucket_seconds': 1, 'history_span_seconds': 0,
                'history_start': stamp(cutoff), 'history_end': stamp(cutoff)}
    first = min(time for time, _ in visible)
    span = (cutoff - first).total_seconds()
    candidates = [1, 2, 5, 10, 30, 60, 120, 300, 600, 1800, 3600]
    candidates.append(max(3600, math.ceil(span / 119 / 3600) * 3600))
    for seconds in candidates:
        lower_index = math.floor(first.timestamp() / seconds)
        upper_index = math.floor(cutoff.timestamp() / seconds)
        if upper_index - lower_index + 1 <= 120:
            break
    counts, accounts = Counter(), defaultdict(set)
    for time, account in visible:
        index = math.floor(time.timestamp() / seconds)
        counts[index] += 1
        accounts[index].add(account)
    history = []
    for index in range(lower_index, upper_index + 1):
        lower = datetime.fromtimestamp(index * seconds, timezone.utc)
        end = lower + timedelta(seconds=seconds)
        partial_last = index == upper_index and cutoff < end
        history.append({'time': stamp(lower), 'end': stamp(min(end, cutoff)),
                        'post_count': counts[index], 'account_count': len(accounts[index]),
                        'partial': first > lower or partial_last,
                        'partial_last': partial_last, 'observed': counts[index] > 0,
                        'within_observed_range': observed_start is not None and observed_start <= lower})
    beginning = parse_time(history[0]['time'])
    return {'history': history, 'bucket_seconds': seconds,
            'history_span_seconds': (cutoff - beginning).total_seconds(),
            'history_start': stamp(beginning), 'history_end': stamp(cutoff)}
