from datetime import timedelta
import json
import unittest
from pathlib import Path
import tempfile

from behavior import analyze_behavior
from engine import parse_time, stamp
from resource_alerts import resource_bursts

BASE = parse_time('2026-10-01T23:59:40Z')


def fixture(count=12, accounts=6, step=2):
    posts = [{'id': 'root', 'account_id': 'source', 'created_at': stamp(BASE-timedelta(seconds=1)),
              'raw_json': '{}'}]
    for i in range(count):
        relation = {'type': 'quotes', 'target_post_id': 'root'}
        posts.append({'id': str(i), 'account_id': str(i % accounts),
                      'created_at': stamp(BASE+timedelta(seconds=i*step)),
                      'raw_json': json.dumps({'relations': [relation, relation]})})
    group = {'id': 'flow-root', 'kind': 'REFERENCE_FLOW', 'evidence_post_ids': [p['id'] for p in posts],
             'child_groups': []}
    return posts, group


class ResourceBurstTests(unittest.TestCase):
    def test_early_attention_without_fabricating_repeat_coordination(self):
        posts, group = fixture()
        alerts = resource_bursts([group], posts, BASE+timedelta(seconds=30))
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert['kind'], 'resource_burst')
        self.assertEqual(alert['phase'], 'active')
        self.assertNotIn('network_score', alert)
        self.assertIn('COORDINATION_UNCONFIRMED', alert['reason_codes'])
        self.assertEqual(analyze_behavior(posts, [], BASE+timedelta(seconds=30))['signals'], [])
        self.assertEqual(alerts, resource_bursts([group], list(reversed(posts)), BASE+timedelta(seconds=30)))

    def test_thresholds_single_actor_slow_spread_and_unrelated_posts(self):
        for args in [(9,6,2), (12,1,2), (12,6,61)]:
            posts, group = fixture(*args)
            self.assertEqual(resource_bursts([group], posts, BASE+timedelta(seconds=800)), [])
        posts, group = fixture()
        for p in posts:p['raw_json']='{}'
        self.assertEqual(resource_bursts([group], posts, BASE+timedelta(seconds=30)), [])

    def test_future_unknown_and_duplicate_relations_do_not_supply_link_count(self):
        posts, group = fixture()
        posts[0]['created_at'] = stamp(BASE+timedelta(hours=1))
        self.assertEqual(resource_bursts([group], posts, BASE+timedelta(seconds=30)), [])
        self.assertEqual(resource_bursts([group], posts[1:], BASE+timedelta(seconds=30)), [])

    def test_history_retained_and_current_activity_not_claimed_after_idle(self):
        posts, group = fixture()
        first = resource_bursts([group], posts, BASE+timedelta(seconds=30))[0]
        later = resource_bursts([group], posts, BASE+timedelta(hours=1))[0]
        self.assertEqual(first['id'], later['id'])
        self.assertEqual(first['first_triggered_at'], later['first_triggered_at'])
        self.assertEqual(later['phase'], 'historical')
        self.assertEqual(later['metrics']['current_post_count'], 0)
        self.assertEqual(resource_bursts([group], posts, BASE+timedelta(hours=25)), [])

    def test_crowded_breaking_news_url_is_attention_not_coordination(self):
        posts, group = fixture()
        for p in posts:p['raw_json']='{}'
        group['child_groups'] = [{'kind':'SHARED_URL', 'evidence_post_ids':group['evidence_post_ids']}]
        self.assertEqual(len(resource_bursts([group], posts, BASE+timedelta(seconds=30))), 1)
        self.assertEqual(analyze_behavior(posts, [{'post_id':p['id'],'url':'https://news.invalid/a'} for p in posts], BASE+timedelta(seconds=30))['signals'], [])

    def test_exact_sixty_second_boundary_and_invalid_reference(self):
        posts, group = fixture(step=5)
        posts[-1]['created_at'] = stamp(BASE+timedelta(seconds=60))
        alert = resource_bursts([group], posts, BASE+timedelta(seconds=60))[0]
        self.assertEqual(alert['phase'], 'active')
        self.assertEqual(alert['metrics']['current_post_count'], 12)
        posts[1]['raw_json'] = json.dumps({'relations':[{'type':'quotes','target_post_id':[]}]})
        self.assertEqual(len(resource_bursts([group], posts, BASE+timedelta(seconds=60))), 1)

    def test_actual_standalone_url_group_supplies_sharing_evidence(self):
        from resources import group_resources
        posts, _ = fixture()
        for post in posts:
            post['raw_json'] = '{}'
            post['text'] = 'Distinct report ' + post['id']
        urls = [{'post_id': p['id'], 'url': 'https://news.invalid/article'} for p in posts]
        groups = group_resources(posts, urls)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['kind'], 'SHARED_URL')
        self.assertEqual(len(resource_bursts(groups, posts, BASE+timedelta(seconds=30))), 1)
        self.assertEqual(analyze_behavior(posts, urls, BASE+timedelta(seconds=30))['signals'], [])

    def test_runtime_counts_persistence_evidence_and_live_idle_phase(self):
        from server import RawOnlyEmbedder, Runtime
        posts, group = fixture()
        raw = [{**{k:p[k] for k in ('id','account_id','created_at')},
                'text': 'Original report about a public exercise.' if p['id']=='root' else 'Reader response '+p['id'],
                'relations': json.loads(p['raw_json']).get('relations',[])} for p in posts]
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder)/'test.sqlite3'
            now = [BASE+timedelta(seconds=30)]
            runtime=Runtime(db,RawOnlyEmbedder(db),no_ai=True,clock=lambda:now[0])
            runtime.ingest(raw)
            data=runtime.dashboard()
            self.assertEqual(data['early_alerts_count'],1)
            self.assertEqual(data['global_signals_count'],0)
            self.assertEqual(data['summary']['alert_count'],1)
            case=next(c for c in data['cases'] if c['alerts'])
            alert=next(a for a in case['alerts'] if a['kind']=='resource_burst')
            self.assertTrue(set(alert['evidence_post_ids'])<={p['id'] for p in case['posts']})
            self.assertEqual(sum(e['weight'] for e in case['network']['edges']),12)
            self.assertEqual(data['investigations'],[])
            runtime2=Runtime(db,RawOnlyEmbedder(db),no_ai=True,clock=lambda:now[0])
            self.assertEqual(runtime2.dashboard()['early_alerts_count'],1)
            now[0]+=timedelta(minutes=3)
            historical=next(a for c in runtime2.dashboard()['cases'] for a in c['alerts'] if a['kind']=='resource_burst')
            self.assertEqual(historical['phase'],'historical')
            self.assertEqual(historical['id'],alert['id'])
            self.assertEqual(historical['metrics']['current_post_count'],0)

    def test_behavior_investigation_keeps_nested_material_evidence(self):
        from server import RawOnlyEmbedder, Runtime
        raw=[]
        for i in range(3):
            raw.append({'id':f'root{i}','account_id':'source','text':f'Original report number {i}',
                        'created_at':stamp(BASE+timedelta(seconds=i*600-10))})
            for account,offset in [('a',0),('b',2)]:
                raw.append({'id':f'{i}{account}','account_id':account,'text':f'Response {i}{account}',
                    'created_at':stamp(BASE+timedelta(seconds=i*600+offset)),
                    'relations':[{'type':'quotes','target_post_id':f'root{i}'}]})
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'test.sqlite3'
            runtime=Runtime(db,RawOnlyEmbedder(db),no_ai=True,clock=lambda:BASE+timedelta(hours=1))
            runtime.ingest(raw,stamp(BASE+timedelta(hours=1)))
            case=runtime.dashboard()['investigations'][0]
            self.assertEqual(len(case['related_case_ids']),3)
            self.assertEqual(len(case['narratives']),3)
            self.assertEqual(len({n['id'] for n in case['narratives']}),3)
            evidence=set(case['alerts'][0]['evidence_post_ids'])
            self.assertEqual({p for n in case['narratives'] for p in n['evidence_post_ids']},evidence)

    def test_alert_identity_survives_parent_change_and_disjoint_later_peak(self):
        posts, group = fixture()
        before=resource_bursts([group],posts,BASE+timedelta(seconds=30))
        additions, unused=fixture(count=20)
        additions=[{**p,'id':'new'+p['id'], 'created_at':stamp(parse_time(p['created_at'])+timedelta(seconds=200))}
                   for p in additions if p['id']!='root']
        after_group={**group,'id':'recovered-parent','evidence_post_ids':group['evidence_post_ids']+[p['id'] for p in additions]}
        after=resource_bursts([after_group],posts+additions,BASE+timedelta(seconds=250),before)
        self.assertEqual(after[0]['id'],before[0]['id'])
        self.assertEqual(after[0]['metrics']['post_count'],20)
        self.assertFalse(set(after[0]['evidence_post_ids'])&set(before[0]['evidence_post_ids']))


if __name__ == '__main__':unittest.main()
