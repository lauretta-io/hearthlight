import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from activity import ActivityStore
from history import query_history
from scene import build_request, parse_scene


class PersistentStateTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'state.sqlite3'
        self.store = ActivityStore(self.path)
        self.addCleanup(self.store.db.close)
        self.frames = [Image.new('RGB', (64, 64), c) for c in ('red', 'blue', 'green')]
        self.tracks = [[(i, (0, 0, 20, 50)) for i in range(3)],
                       [(i, (30, 0, 60, 50)) for i in range(3)]]

    def item(self, action='pick_up'):
        return dict(action=action, item='bottle', appearance='blue bottle', start_frame=0,
                    end_frame=2, actor='target', certainty='clear', evidence='bottle moves into hand')

    def interaction(self, **changes):
        return dict(target_kind='person', target_track_id=2, interaction_type='gesture',
                    start_frame=0, end_frame=2, actor='target', certainty='clear',
                    evidence='Person 1 waves toward person 2', **changes)

    def save(self, index=0, events=None, interactions=None, identities=None, camera='camera-a'):
        sample = dict(sample_id=f'scene-{index}', camera_id=camera,
                      sampled_at=f'2026-11-12T00:00:{index:02d}+00:00', sample_fps=1,
                      activity_model='fixture', activity_model_revision='rev')
        request = build_request(sample, self.frames, self.tracks, identities or ['alice', 'bob'])
        output = dict(scene_description='Two people near a table.', persons=[
            dict(track_id=1, description='Person 1 near table', events=events or [], interactions=interactions or []),
            dict(track_id=2, description='Person 2 standing', events=[], interactions=[])])
        raw = json.dumps(output)
        return self.store.record_analysis(sample, request, parse_scene(raw, request, self.frames), raw, 'analyzed')

    def state(self, person='alice', **filters):
        return query_history(self.path, 'state', person_id=person, **filters)['records']

    def test_objects_taken_and_other_people_persist_after_restart_and_empty_window(self):
        self.save(events=[self.item()], interactions=[self.interaction()])
        self.save(1)
        reopened = ActivityStore(self.path)
        self.addCleanup(reopened.db.close)
        records = self.state()
        obj = next(r for r in records if r['target_kind'] == 'object')
        self.assertEqual(obj['last_possession_status'], 'observed_with_person')
        self.assertEqual(obj['observed_at'], '2026-11-12T00:00:00+00:00')
        self.assertEqual(obj['last_taken_at'], obj['observed_at'])
        self.assertEqual(len(reopened.prior_state('alice')), 2)
        other = self.state('bob')[0]
        self.assertEqual((other['target_person_id'], other['direction']), ('alice', 'incoming'))

    def test_object_use_does_not_erase_possession_and_release_keeps_taken_history(self):
        self.save(events=[self.item()])
        touch = dict(target_kind='object', interaction_type='use', item='bottle', appearance='blue bottle',
                     start_frame=0, end_frame=2, actor='target', certainty='clear', evidence='drinks from bottle')
        self.save(1, interactions=[touch])
        obj = self.state()[0]
        self.assertEqual((obj['interaction_type'], obj['last_possession_status']), ('use', 'observed_with_person'))
        self.assertEqual(obj['possession_observed_at'], '2026-11-12T00:00:00+00:00')
        self.save(2, events=[self.item('put_down')])
        obj = self.state()[0]
        self.assertEqual(obj['last_possession_status'], 'observed_released')
        self.assertEqual(obj['last_taken_at'], '2026-11-12T00:00:00+00:00')

    def test_retries_and_out_of_order_windows_do_not_overwrite_latest_state(self):
        self.save(2, events=[self.item('put_down')])
        self.save(0, events=[self.item()])
        self.assertFalse(self.save(0, events=[self.item()])['inserted'])
        state = self.state()[0]
        self.assertEqual(state['last_possession_status'], 'observed_released')
        self.assertEqual(state['observation_count'], 2)

    def test_camera_filter_is_applied_before_latest_state_and_history_counts(self):
        self.save(0, events=[self.item()], camera='camera-a')
        self.save(1, events=[self.item('put_down')], camera='private-camera')
        state = self.state(camera_id='camera-a')[0]
        self.assertEqual(state['last_possession_status'], 'observed_with_person')
        self.assertEqual(state['observation_count'], 1)
        self.assertEqual(self.state(camera_id='unknown'), [])

    def test_ambiguous_or_unidentified_actors_do_not_update_trusted_state(self):
        self.save(interactions=[{**self.interaction(), 'certainty': 'unclear'}])
        self.save(1, interactions=[self.interaction()], identities=[None, 'bob'])
        self.assertEqual(self.state(), [])
        self.assertEqual(self.state('bob'), [])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM person_interactions').fetchone()[0], 2)

    def test_model_ids_are_ignored_and_unresolved_counterpart_remains_unresolved(self):
        interaction = {**self.interaction(), 'target_person_id': 'invented'}
        result = self.save(interactions=[interaction], identities=['alice', None])
        row = result['behaviors'][0]['interactions'][0]
        self.assertIsNone(row['target_person_id'])
        self.assertEqual(row['person_id'], 'alice')
        self.assertIsNone(self.state()[0]['target_person_id'])

    def test_unknown_self_or_absent_counterpart_is_rejected(self):
        for i, changes in enumerate(({'target_track_id': 99}, {'target_track_id': 1},
                                     {'start_frame': True}, {'interaction_type': 'friends'})):
            result = self.save(i, interactions=[{**self.interaction(), **changes}])
            self.assertEqual(result['behaviors'][0]['analysis_status'], 'partial')
            self.assertEqual(result['scene']['description'], 'Two people near a table.')
        self.assertEqual(self.state(), [])

    def test_counterpart_must_be_present_at_both_evidence_endpoints(self):
        self.tracks[1] = self.tracks[1][1:]
        result = self.save(interactions=[self.interaction()])
        self.assertEqual(result['behaviors'][0]['analysis_status'], 'partial')
        self.assertEqual(self.state(), [])

    def test_transfers_require_distinct_frames_and_visible_change(self):
        result = self.save(interactions=[{**self.interaction(), 'interaction_type': 'give', 'end_frame': 0}])
        self.assertEqual(result['behaviors'][0]['analysis_status'], 'partial')
        self.frames = [self.frames[0].copy() for _ in range(3)]
        result = self.save(1, interactions=[{**self.interaction(), 'interaction_type': 'give'}])
        self.assertEqual(result['behaviors'][0]['analysis_status'], 'partial')
        self.assertEqual(self.state(), [])

    def test_independent_interaction_types_and_directions_are_retained(self):
        self.save(interactions=[self.interaction()])
        self.save(1, interactions=[{**self.interaction(), 'interaction_type': 'approach'}])
        self.assertEqual({r['interaction_type'] for r in self.state()}, {'gesture', 'approach'})
        self.assertEqual(len(self.state('bob')), 2)

    def test_state_pagination_and_legacy_backfill(self):
        self.save(events=[self.item()], interactions=[self.interaction()])
        first = query_history(self.path, 'state', person_id='alice', limit=1)
        second = query_history(self.path, 'state', person_id='alice', limit=1, offset=first['next_offset'])
        self.assertNotEqual(first['records'][0]['event_id'], second['records'][0]['event_id'])
        self.store.db.execute('DELETE FROM person_interactions')
        self.store.db.execute('DELETE FROM person_state_migrations')
        self.store.db.commit()
        upgraded = ActivityStore(self.path)
        self.addCleanup(upgraded.db.close)
        self.assertEqual(self.state()[0]['item'], 'bottle')
        self.assertEqual(len(self.state()), 1)  # No fabricated historical social evidence.


if __name__ == '__main__':
    unittest.main()
