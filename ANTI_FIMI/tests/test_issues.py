from datetime import timedelta
import json
import unittest

from engine import parse_time, stamp
from issues import issue_groups


BASE = parse_time('2026-10-01T12:00:00Z')


def post(pid, text, seconds=0, targets=(), **extra):
    return {'id': pid, 'text': text, 'created_at': stamp(BASE + timedelta(seconds=seconds)),
            'raw_json': json.dumps({'relations': [{'type': 'quotes', 'target_post_id': t} for t in targets], **extra})}


def by_id(posts, material=()):
    return {group['id']: group for group in issue_groups(posts, material)}


class IssueTests(unittest.TestCase):
    def test_claim_question_rebuttal_and_official_notice_stay_in_one_topic_without_stance(self):
        rows = [post('a', '전선이 무너졌습니다.'), post('b', '전선이 무너졌다는 것이 사실인가요?'),
                post('c', '전선이 무너졌다는 주장은 사실이 아닙니다.'),
                post('d', '공식 확인: 전선 상황은 구역별로 다릅니다.')]
        result = by_id(rows)
        self.assertEqual(set(result), {'ISSUE_FRONTLINE'})
        self.assertEqual(result['ISSUE_FRONTLINE']['evidence_post_ids'], ['a', 'b', 'c', 'd'])
        self.assertNotIn('stance', result['ISSUE_FRONTLINE'])
        self.assertTrue(all(match['matched_terms'] for match in result['ISSUE_FRONTLINE']['issue_matches']))

    def test_military_civilian_facilities_and_civilian_harm_are_distinct(self):
        rows = [post('mil', '주요 군 시설이 파괴됐다는 주장이 있습니다.'),
                post('civ', '민간 기반시설과 병원의 상황을 확인 중입니다.'), post('harm', '민간 피해 집계가 진행 중입니다.')]
        result = by_id(rows)
        self.assertEqual(result['ISSUE_MILITARY_FACILITIES']['evidence_post_ids'], ['mil'])
        self.assertEqual(result['ISSUE_CIVILIAN_FACILITIES']['evidence_post_ids'], ['civ'])
        self.assertEqual(result['ISSUE_CIVILIAN_HARM']['evidence_post_ids'], ['harm'])
        self.assertEqual(by_id([post('generic', '군인과 민간인 모두 뉴스를 읽습니다.')]), {})

    def test_multitopic_posts_do_not_merge_folders_or_spread_all_topics_to_generic_replies(self):
        rows = [post('multi', '전선 상황과 경제 위기를 검토합니다.'),
                post('reply', '추가 소식이 있나요?', 1, ['multi']), post('own', '산업시설을 확인합니다.', 2, ['multi'])]
        result = by_id(rows)
        self.assertEqual(set(result), {'ISSUE_FRONTLINE', 'ISSUE_ECONOMY', 'ISSUE_INDUSTRY'})
        self.assertTrue(all('reply' not in group['evidence_post_ids'] for group in result.values()))
        self.assertEqual(result['ISSUE_INDUSTRY']['evidence_post_ids'], ['own'])

    def test_valid_reference_inherits_topic_even_out_of_order_but_future_old_unknown_do_not(self):
        root = post('root', 'The frontline report needs verification.')
        reply = post('reply', 'Can anyone confirm this?', 1, ['root'])
        nested = post('nested', 'Following up.', 2, ['reply'])
        excluded = [post('future', 'Unknown report', -1, ['root']), post('old', 'Unknown report', 86401, ['root']),
                    post('missing', 'Unknown report', 2, ['not-found'])]
        result = by_id([nested, reply, root, *excluded])['ISSUE_FRONTLINE']
        self.assertEqual(result['evidence_post_ids'], ['nested', 'reply', 'root'])
        inherited = {m['post_id']: m for m in result['issue_matches']}
        self.assertEqual(inherited['reply']['target_post_id'], 'root')
        self.assertEqual(inherited['nested']['target_post_id'], 'reply')
        self.assertEqual(inherited['reply']['matched_terms'], [])

    def test_competing_parent_topics_remain_ambiguous_regardless_of_resolution_order(self):
        rows = [post('f', 'The frontline is stable.'), post('e', 'The economy is unstable.'),
                post('late-parent', 'Details?', 1, ['e']), post('bridge', 'Any updates?', 2, ['f', 'late-parent']),
                post('bridge-child', 'Please explain', 3, ['bridge'])]
        result = by_id(rows)
        self.assertTrue(all(not {'bridge', 'bridge-child'} & set(group['evidence_post_ids']) for group in result.values()))
        self.assertEqual(issue_groups(rows, []), issue_groups(list(reversed(rows)), []))

    def test_child_material_identity_and_scoped_evidence_are_preserved(self):
        rows = [post('f', '전선 상황'), post('e', '경제 위기')]
        material = [{'id': 'RG_fixture', 'kind': 'REFERENCE_FLOW', 'title': 'Original flow', 'resource': 'origin',
                     'evidence_post_ids': ['f', 'e']}]
        result = by_id(rows, material)
        child = result['ISSUE_FRONTLINE']['child_groups'][0]
        self.assertEqual(child['id'], 'RG_fixture')
        self.assertEqual(child['evidence_post_ids'], ['f'])
        self.assertEqual(child['related_post_ids'], ['e'])

    def test_ko_en_ja_zh_vocabulary_and_unknown_language_are_explicit(self):
        samples = [('ko', '군사 시설'), ('en', 'Military facilities'), ('ja', '軍事施設'), ('zh', '军事设施')]
        result = by_id([post(pid, text) for pid, text in samples])
        self.assertEqual(result['ISSUE_MILITARY_FACILITIES']['evidence_post_ids'], ['en', 'ja', 'ko', 'zh'])
        self.assertEqual(by_id([post('unknown', 'bonjour le monde'), post('daily', '오늘 점심이 맛있다')]), {})

    def test_ten_topics_are_not_created_until_observed(self):
        texts = ['전선 상황', '후퇴 명령', '동맹 충돌', '파병군', '군 시설', '민간 시설', '민간 피해', '피란민', '경제 위기', '산업시설']
        result = issue_groups([post(str(i), text) for i, text in enumerate(texts)], [])
        self.assertEqual(len(result), 10)
        self.assertEqual(len(issue_groups([post('one', '피란민')], [])), 1)

    def test_account_scenario_and_hidden_metadata_cannot_assign_a_topic(self):
        row = post('metadata', '무슨 일인가요?', scenario_id='frontline', ground_truth='economy', cluster_id='military')
        row['account_id'] = 'frontline_bot'
        self.assertEqual(issue_groups([row], []), [])

    def test_english_front_requires_military_context_not_storefront_or_front_door(self):
        result = by_id([post('claim', 'Every front has collapsed and all defence has stopped.'),
                        post('notice', 'Other defensive sectors are still active.'),
                        post('daily', 'The front door and storefront need paint.')])
        self.assertEqual(result['ISSUE_FRONTLINE']['evidence_post_ids'], ['claim', 'notice'])

    def test_malformed_relations_and_self_references_cannot_create_inheritance(self):
        root = post('root', '경제 위기')
        malformed = [42, {}, 'root', None, [{'type': 'quotes', 'target_post_id': []}],
                     [{'type': 'quotes', 'target_post_id': {}}], [{'type': 'quotes', 'target_post_id': 'self'}]]
        for relations in malformed:
            with self.subTest(relations=relations):
                row = post('self', 'Can anyone explain?', 1)
                row['raw_json'] = json.dumps({'relations': relations})
                result = by_id([root, row])
                self.assertEqual(result['ISSUE_ECONOMY']['evidence_post_ids'], ['root'])
                row['text'] = '경제 위기'
                self.assertEqual(by_id([row])['ISSUE_ECONOMY']['evidence_post_ids'], ['self'])


if __name__ == '__main__':
    unittest.main()
