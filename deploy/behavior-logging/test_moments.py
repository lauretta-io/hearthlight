import json
import sqlite3
import unittest
from moments import initialize, prepare, commit, prepare_reports


class MomentTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        initialize(self.db)
        self.calls = []

    def record(self, n, events=None, interactions=None, changed=False, aliases=None, person='person-a'):
        sample = {'sample_id': f'scene-{n}', 'camera_id': 'camera-a', 'sampled_at': f'2026-11-16T12:00:{n:02d}Z',
                  'person_contexts': {person: 'Operator note: visitor uses a walking aid.'},
                  'scene_context': {'camera_description': 'Reception desk'}, 'activity_model': 'existing-qwen'}
        report = {'description': 'Seated at a desk.', 'events': events or [], 'interactions': interactions or []}
        def evaluate(prompt, **kwargs):
            self.calls.append(prompt)
            return json.dumps({'summary': report['description'], 'behavior_changed': changed, 'matched_rule_ids': []})
        value = prepare(self.db, sample, {'person_id': person, 'track_id': 1}, report, 'Reception with desks.', evaluate, aliases)
        with self.db:
            commit(self.db, value)
        return value

    def event(self, action):
        return {'action': action, 'item': 'bottle', 'appearance': 'blue', 'actor': 'target', 'certainty': 'clear', 'start_frame': 0, 'end_frame': 2}

    def test_same_behavior_merges_and_replay_is_idempotent(self):
        first = self.record(1)
        second = self.record(2)
        self.assertTrue(first['keyframe'])
        self.assertFalse(second['keyframe'])
        self.assertEqual(first['moment_id'], second['moment_id'])
        self.assertEqual(self.db.execute('SELECT count(*),max(observation_count) FROM person_moments').fetchone(), (1, 2))
        with self.db:
            commit(self.db, second)
        self.assertEqual(self.db.execute('SELECT observation_count FROM person_moments').fetchone()[0], 2)

    def test_possession_changes_override_unchanged_behavior_and_no_observation_does_not_release(self):
        self.record(1, [self.event('carry')])
        self.assertFalse(self.record(2)['keyframe'])
        released = self.record(3, [self.event('put_down')])
        pickup = self.record(4, [self.event('pick_up')])
        self.assertTrue(released['keyframe'])
        self.assertTrue(pickup['keyframe'])
        self.assertEqual(pickup['possessions']['bottle|blue']['origin'], 'observed_pickup')
        self.assertFalse(self.record(5, [self.event('hold')])['keyframe'])

    def test_interactions_compare_last_three_logs(self):
        interaction = {'target_kind': 'object', 'interaction_type': 'touch', 'item': 'desk', 'appearance': 'white', 'actor': 'target', 'certainty': 'clear'}
        self.record(1)
        self.assertTrue(self.record(2, interactions=[interaction])['keyframe'])
        self.assertFalse(self.record(3, interactions=[interaction])['keyframe'])
        self.record(4)
        self.record(5)
        self.record(6)
        self.assertTrue(self.record(7, interactions=[interaction])['keyframe'])

    def test_context_uses_person_scene_and_exactly_three_recent_logs_without_recursive_payloads(self):
        for n in range(1, 6):
            self.record(n)
        context = json.loads(self.calls[-1].split('INPUT_JSON:\n')[1])
        self.assertEqual(len(context['recent_logs']), 3)
        self.assertIn('walking aid', context['person_description'])
        self.assertEqual(context['scene_description'], 'Reception with desks.')
        self.assertEqual(context['camera_description'], 'Reception desk')
        self.assertEqual(context['existing_person_description'], 'Seated at a desk.')
        self.assertNotIn('context', context['previous_moment'])

    def test_aliases_share_existing_moment(self):
        first = self.record(1, person='old')
        next_value = self.record(2, person='new', aliases=['new', 'old'])
        self.assertFalse(next_value['keyframe'])
        self.assertEqual(first['moment_id'], next_value['moment_id'])

    def test_model_cannot_invent_alert_rule_ids_and_failure_preserves_raw_log(self):
        sample = {'sample_id': 'x', 'camera_id': 'camera-a', 'sampled_at': '2026-11-16T12:00:01Z'}
        result = prepare(self.db, sample, {'person_id': 'person-a', 'track_id': 1}, {'description': 'seated'}, 'office',
                         lambda *args, **kwargs: json.dumps({'summary': 'seated', 'behavior_changed': True, 'matched_rule_ids': ['invented']}))
        self.assertEqual(result['evaluation_status'], 'failed')
        self.assertFalse(result['keyframe'])
        with self.db:
            commit(self.db, result)
        self.assertEqual(self.db.execute('SELECT count(*) FROM person_moments').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM person_moment_logs').fetchone()[0], 1)

    def test_fragments_of_one_person_in_one_sample_share_one_decision_and_log(self):
        sample = {'sample_id': 'one-sample', 'camera_id': 'camera-a', 'sampled_at': '2026-11-16T12:00:01Z'}
        request = {'tracks': [{'track_id': n, 'person_id': 'person-a'} for n in [1, 2, 3]]}
        analysis = {'scene_description': 'Office', 'persons': [
            {'track_id': n, 'description': 'Seated at a desk.', 'events': [], 'interactions': [], 'analysis_status': 'analyzed'} for n in [1, 2, 3]]}
        calls = []
        def evaluate(prompt, **kwargs):
            calls.append(prompt)
            return json.dumps({'summary': 'Seated at a desk.', 'behavior_changed': False, 'matched_rule_ids': []})
        values = prepare_reports(self.db, sample, request, analysis, evaluate)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(values), 1)
        self.assertEqual(len({report['moment']['moment_id'] for report in analysis['persons']}), 1)
        with self.db:
            for report in analysis['persons']:
                commit(self.db, report['moment'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM person_moment_logs').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT observation_count FROM person_moments').fetchone()[0], 1)

    def test_return_to_a_camera_does_not_itself_create_a_behavior_change(self):
        first = self.record(1)
        sample = {'sample_id': 'other-camera', 'camera_id': 'camera-b', 'sampled_at': '2026-11-16T12:00:02Z'}
        value = prepare(self.db, sample, {'person_id': 'person-a', 'track_id': 1},
                        {'description': 'Seated at a desk.'}, 'Office',
                        lambda *args, **kwargs: json.dumps({'summary': 'Seated at a desk.', 'behavior_changed': False, 'matched_rule_ids': []}))
        with self.db:
            commit(self.db, value)
        returned = self.record(3)
        self.assertFalse(returned['keyframe'])
        self.assertEqual(returned['moment_id'], first['moment_id'])

    def test_fixture_contact_expires_from_active_state_after_three_noncontact_logs(self):
        interaction={'target_kind':'object','interaction_type':'touch','item':'shelves','appearance':'metal','actor':'target','certainty':'clear'}
        first=self.record(1,interactions=[interaction])
        self.assertEqual(first['possessions'],{})
        self.assertEqual(first['interaction_states']['shelves|metal']['status'],'active')
        self.record(2);self.record(3);latest=self.record(4)
        self.assertEqual(latest['interaction_states']['shelves|metal']['status'],'unobserved')
        self.assertTrue(latest['keyframe'])

    def test_removing_from_bag_is_not_a_surface_pickup(self):
        value = self.record(1, [self.event('take_out_of_bag')])
        self.assertEqual(value['possessions']['bottle|blue']['origin'], 'removed_from_bag')


if __name__ == '__main__':
    unittest.main()
