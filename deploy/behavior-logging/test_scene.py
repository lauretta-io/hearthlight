from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from activity import ActivityStore
from runner import analyze_sample
from scene import build_request, parse_scene


class SceneHistoryTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'activities.sqlite3'
        self.store = ActivityStore(self.path)
        self.addCleanup(self.store.db.close)
        self.sample = {'sample_id': 'clip-one', 'camera_id': 'camera-one', 'camera_name': 'Office',
                       'sampled_at': datetime.now(timezone.utc).isoformat(), 'sample_fps': 2,
                       'activity_model': 'fixture', 'activity_model_revision': 'revision'}
        self.frames = [Image.new('RGB', (64, 64), color) for color in ('white', 'red', 'blue')]
        self.tracks = [[(0, (0, 0, 20, 50)), (1, (1, 0, 21, 50)), (2, (2, 0, 22, 50))],
                       [(1, (30, 0, 60, 50)), (2, (31, 0, 61, 50))]]
        self.request = build_request(self.sample, self.frames, self.tracks, ['alice-id', 'bob-id'])
        self.output = {'scene_description': 'Two people are near a table.', 'persons': [
            {'track_id': 1, 'person_id': 'model-invented-id', 'description': 'Standing by a table.', 'events': []},
            {'track_id': 2, 'description': 'Walking past the table.', 'events': []}]}

    def save(self, output=None, sample=None, request=None):
        request = request or self.request
        raw = json.dumps(output or self.output)
        analysis = parse_scene(raw, request, self.frames)
        return self.store.record_analysis(sample or self.sample, request, analysis, raw, 'analyzed')

    def test_request_tracks_keep_frame_positions_and_identity_mapping(self):
        bob = self.request['tracks'][1]
        self.assertEqual(bob['person_id'], 'bob-id')
        self.assertEqual([d['frame_index'] for d in bob['detections']], [1, 2])
        self.assertEqual(bob['detections'][1]['offset_seconds'], 1)
        self.assertEqual(bob['detections'][1]['box_xyxy'], [31, 0, 61, 50])

    def test_distinct_behaviors_and_scene_context_link_to_trusted_person_ids(self):
        result = self.save()
        self.assertEqual([b['person_id'] for b in result['behaviors']], ['alice-id', 'bob-id'])
        rows = self.store.db.execute('SELECT person_id, behavior_description, scene_description FROM person_behavior_history ORDER BY track_id').fetchall()
        self.assertEqual(rows, [('alice-id', 'Standing by a table.', self.output['scene_description']),
                                ('bob-id', 'Walking past the table.', self.output['scene_description'])])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM person_scene_history').fetchone(), (2,))

    def test_history_continues_across_cameras_and_reopening(self):
        self.save()
        later = {**self.sample, 'sample_id': 'clip-two', 'camera_id': 'camera-two',
                 'sampled_at': (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()}
        request = build_request(later, self.frames, self.tracks, ['bob-id', 'alice-id'])
        self.save(sample=later, request=request)
        reopened = ActivityStore(self.path)
        self.addCleanup(reopened.db.close)
        self.assertEqual(reopened.db.execute("SELECT COUNT(*) FROM person_behavior_history WHERE person_id='alice-id'").fetchone(), (2,))
        self.assertEqual(reopened.db.execute('SELECT COUNT(*) FROM persons').fetchone(), (2,))
        descriptions = reopened.db.execute("SELECT behavior_description FROM person_behavior_history WHERE person_id='alice-id' ORDER BY observed_at").fetchall()
        self.assertEqual(descriptions, [('Standing by a table.',), ('Walking past the table.',)])

    def test_unknown_and_duplicate_track_ids_do_not_attach_invented_behaviors(self):
        self.output['persons'].append({'track_id': 99, 'description': 'Unknown actor', 'events': []})
        self.output['persons'].append({'track_id': 1, 'description': 'Conflicting actor', 'events': []})
        result = self.save()
        self.assertEqual(result['behaviors'][0]['analysis_status'], 'invalid_response')
        self.assertIsNone(result['behaviors'][0]['description'])
        self.assertEqual(len(result['behaviors']), 2)
        self.assertEqual(result['behaviors'][1]['person_id'], 'bob-id')

    def test_omitted_person_still_links_to_the_scene_with_explicit_status(self):
        self.output['persons'].pop()
        result = self.save()
        self.assertEqual(result['behaviors'][1]['analysis_status'], 'omitted')
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM person_scene_history WHERE person_id='bob-id'").fetchone(), (1,))

    def test_partial_item_events_keep_description_without_updating_possession(self):
        self.output['persons'][1]['events'] = [{'action': 'pick_up'}]
        result = self.save()
        self.assertEqual(result['behaviors'][1]['analysis_status'], 'partial')
        self.assertEqual(result['behaviors'][1]['description'], 'Walking past the table.')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM activities').fetchone(), (0,))

    def test_empty_scene_and_unresolved_person_are_retained(self):
        request = build_request(self.sample, self.frames, [], [])
        result = self.save({'scene_description': 'Empty office.', 'persons': []}, request=request)
        self.assertEqual(result['behaviors'], [])
        later = {**self.sample, 'sample_id': 'clip-two'}
        request = build_request(later, self.frames, [self.tracks[0]], [None])
        self.save({'scene_description': 'A person stands.', 'persons': [self.output['persons'][0]]}, later, request)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM scene_descriptions').fetchone(), (2,))
        self.assertEqual(self.store.db.execute('SELECT person_id FROM person_behaviors').fetchone(), (None,))

    def test_duplicate_sample_is_idempotent(self):
        self.save()
        again = self.save()
        self.assertFalse(again['inserted'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM scene_descriptions').fetchone(), (1,))
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM person_behaviors').fetchone(), (2,))

    def test_failure_rolls_back_the_scene_links_and_item_updates(self):
        with patch.object(self.store, '_record', side_effect=RuntimeError('storage failure')):
            with self.assertRaises(RuntimeError):
                self.save()
        for table in ('scene_descriptions', 'scene_persons', 'person_behaviors', 'persons', 'person_interactions'):
            self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM '+table).fetchone(), (0,))
        self.assertTrue(self.save()['inserted'])

    def test_event_must_refer_to_frames_where_the_actor_exists(self):
        self.output['persons'][1]['events'] = [{'action': 'hold', 'item': 'bag', 'appearance': 'red bag',
            'start_frame': 0, 'end_frame': 2, 'actor': 'target', 'certainty': 'clear', 'evidence': 'bag is held'}]
        result = self.save()
        self.assertEqual(result['behaviors'][1]['analysis_status'], 'partial')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM person_items').fetchone(), (0,))

    def test_vlm_failure_still_creates_a_scene_and_person_presence_history(self):
        detector = Mock()
        detector.detect.return_value = [[(0, 0, 40, 60)]] * 3
        models = Mock(vlm_id='fixture', revisions={'fixture': 'revision'})
        models.visual_matches.return_value = []
        models.describe.side_effect = RuntimeError('inference failure')
        reid, gallery = Mock(), Mock()
        gallery.assign.return_value = ['alice-id']
        result = analyze_sample(detector, models, self.frames, self.sample, self.store, Mock(), reid, gallery)
        self.assertFalse(result['scene_ok'])
        self.assertEqual(result['behaviors'][0]['analysis_status'], 'inference_failed')
        snapshot = result['behaviors'][0]['snapshot_file']
        self.assertTrue((self.path.parent / 'person-snapshots' / snapshot).is_file())
        self.assertNotIn('snapshot_file', models.describe.call_args.args[1])
        clip = result['scene']['input_request']['recorded_clip']['file']
        self.assertTrue((self.path.parent / 'person-clips' / clip).is_file())
        self.assertNotIn('recorded_clip', models.describe.call_args.args[1])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM person_scene_history WHERE person_id='alice-id'").fetchone(), (1,))

    def test_legacy_activity_database_is_upgraded_without_losing_existing_events(self):
        legacy_path = self.path.with_name('legacy.sqlite3')
        with sqlite3.connect(legacy_path) as legacy:
            for table in ('activities', 'person_items'):
                sql, = self.store.db.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()
                legacy.execute(sql)
            legacy.execute('INSERT INTO activities VALUES (?, ?, ?, ?, ?, ?, ?)',
                           ('old-event', 'old-clip', 1, 'old-person', 'old-camera',
                            self.sample['sampled_at'], '{"legacy":true}'))
        upgraded = ActivityStore(legacy_path)
        self.addCleanup(upgraded.db.close)
        self.assertEqual(upgraded.db.execute('SELECT event_id,payload FROM activities').fetchall(),
                         [('old-event', '{"legacy":true}')])
        self.assertEqual(upgraded.db.execute('SELECT COUNT(*) FROM scene_descriptions').fetchone(), (0,))

    def test_concurrent_retries_create_one_scene_and_one_set_of_behaviors(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        barrier = Barrier(2)
        raw = json.dumps(self.output)
        analysis = parse_scene(raw, self.request, self.frames)

        def write():
            store = ActivityStore(self.path)
            try:
                barrier.wait(timeout=5)
                return store.record_analysis(self.sample, self.request, analysis, raw, 'analyzed')['inserted']
            finally:
                store.db.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: write(), range(2)))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM scene_descriptions').fetchone(), (1,))
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM person_behaviors').fetchone(), (2,))

    def test_person_identity_actor_is_valid_only_for_its_trusted_track(self):
        item = {'action': 'hold', 'item': 'bag', 'appearance': 'red bag', 'start_frame': 0,
                'end_frame': 2, 'actor': 'alice-id', 'certainty': 'clear', 'evidence': 'bag is held'}
        self.output['persons'][0]['events'] = [item]
        result = self.save()
        self.assertEqual(result['activities'][0]['attributed_person_id'], 'alice-id')
        later = {**self.sample, 'sample_id': 'clip-two'}
        self.output['persons'][0]['events'] = [{**item, 'actor': 'bob-id'}]
        result = self.save(sample=later)
        self.assertEqual(result['behaviors'][0]['analysis_status'], 'partial')
        self.assertEqual(result['activities'], [])

    def test_valid_pickup_survives_an_invalid_sibling_event(self):
        pickup = {'action': 'pick_up', 'item': 'bag', 'appearance': 'red bag', 'start_frame': 0,
                  'end_frame': 2, 'actor': 'target', 'certainty': 'clear', 'evidence': 'bag moves from desk to hand'}
        self.output['persons'][0]['events'] = [pickup, {'action': 'hold'}]
        result = self.save()
        self.assertEqual(result['behaviors'][0]['analysis_status'], 'partial')
        self.assertEqual(len(result['activities']), 1)
        self.assertEqual(result['activities'][0]['possession_status'], 'observed_with_person')

    def test_misfiled_use_is_an_interaction_and_movement_is_not_possession(self):
        use = {'action': 'use', 'item': 'laptop', 'appearance': 'black', 'start_frame': 0,
               'end_frame': 2, 'actor': 'target', 'certainty': 'clear', 'evidence': 'typing on the keyboard'}
        self.output['persons'][0]['events'] = [use, {'action': 'sit'}]
        result = self.save()
        self.assertEqual(result['activities'], [])
        self.assertEqual(result['behaviors'][0]['interactions'][0]['interaction_type'], 'use')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM person_items').fetchone()[0], 0)

    def test_valid_scene_is_kept_when_the_person_section_is_missing(self):
        result = self.save({'scene_description': 'Two people stand near a table.'})
        self.assertEqual(result['scene']['description'], 'Two people stand near a table.')
        self.assertEqual([b['analysis_status'] for b in result['behaviors']], ['omitted', 'omitted'])

    def test_item_events_preserve_global_frame_indices_for_late_starting_tracks(self):
        self.output['persons'][1]['events'] = [{'action': 'hold', 'item': 'bag', 'appearance': 'red bag',
            'start_frame': 1, 'end_frame': 2, 'actor': 'target', 'certainty': 'clear', 'evidence': 'bag is held'}]
        result = self.save()
        item, = result['activities']
        self.assertEqual((item['start_frame'], item['end_frame']), (1, 2))
        self.assertEqual((item['start_offset_seconds'], item['end_offset_seconds']), (0.5, 1))
        self.assertEqual(item['person_id'], 'bob-id')
        self.assertEqual(item['behavior_id'], result['behaviors'][1]['behavior_id'])
