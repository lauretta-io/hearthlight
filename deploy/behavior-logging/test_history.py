import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from activity import ActivityStore
from history import query_history


class HistoryRetrievalTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'history.sqlite3'
        store = ActivityStore(self.path)
        for index, identities in enumerate((['alice', 'bob'], ['alice'])):
            sample = {'sample_id': f'scene-{index}', 'camera_id': f'camera-{index}',
                      'camera_name': f'Camera {index}', 'sampled_at': f'2026-11-11T00:00:{index*30:02d}+00:00',
                      'activity_model': 'fixture', 'activity_model_revision': 'revision'}
            tracks = [{'track_id': track_id, 'person_id': person_id,
                       'detections': [{'frame_index': 0, 'box_xyxy': [0, 0, 20, 40]}]}
                      for track_id, person_id in enumerate(identities, start=1)]
            analysis = {'scene_description': f'Scene description {index}', 'persons': [
                {'track_id': track['track_id'], 'description': f"{track['person_id']} standing",
                 'events': [], 'analysis_status': 'analyzed', 'error_code': None} for track in tracks]}
            store.record_analysis(sample, {'tracks': tracks}, analysis, '{}', 'analyzed')
        store.db.close()

    def test_person_behaviors_are_retrievable_in_a_new_process_after_writer_closes(self):
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('history.py')),
                                 'behaviors', '--db', str(self.path), '--person-id', 'alice'],
                                capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        self.assertEqual(data['returned'], 2)
        self.assertEqual([row['person_id'] for row in data['records']], ['alice', 'alice'])
        self.assertEqual([row['scene_description'] for row in data['records']],
                         ['Scene description 1', 'Scene description 0'])
        self.assertEqual(data['records'][0]['description'], 'alice standing')

    def test_scene_and_camera_filters_preserve_person_links(self):
        scenes = query_history(self.path, 'scenes', person_id='bob')
        self.assertEqual([row['scene_id'] for row in scenes['records']], ['scene-0'])
        behaviors = query_history(self.path, 'behaviors', person_id='alice', scene_id='scene-1', camera_id='camera-1')
        self.assertEqual(behaviors['returned'], 1)
        self.assertEqual(behaviors['records'][0]['scene_description'], 'Scene description 1')
        people = query_history(self.path, 'persons', camera_id='camera-1')
        self.assertEqual([person['person_id'] for person in people['records']], ['alice'])

    def test_time_filters_normalize_offsets_and_use_exclusive_upper_bound(self):
        rows = query_history(self.path, 'scenes', since='2026-11-10T18:00:15-06:00',
                             until='2026-11-11T00:01:00Z')['records']
        self.assertEqual([row['scene_id'] for row in rows], ['scene-1'])
        rows = query_history(self.path, 'scenes', until='2026-11-11T00:00:30Z')['records']
        self.assertEqual([row['scene_id'] for row in rows], ['scene-0'])

    def test_pagination_is_bounded_and_ordered(self):
        first = query_history(self.path, 'scenes', limit=1)
        second = query_history(self.path, 'scenes', limit=1, offset=first['next_offset'])
        self.assertEqual(first['records'][0]['scene_id'], 'scene-1')
        self.assertEqual(second['records'][0]['scene_id'], 'scene-0')
        self.assertIsNone(second['next_offset'])

    def test_values_are_bound_as_parameters(self):
        result = query_history(self.path, 'behaviors', person_id="alice' OR 1=1 --")
        self.assertEqual(result['records'], [])
        self.assertEqual(query_history(self.path, 'persons')['returned'], 2)

    def test_missing_database_is_not_created_by_a_query(self):
        missing = self.path.with_name('missing.sqlite3')
        with self.assertRaises(sqlite3.OperationalError):
            query_history(missing, 'scenes')
        self.assertFalse(missing.exists())

    def test_invalid_query_arguments_are_rejected(self):
        for kwargs in ({'limit':0}, {'offset':-1}, {'since':'invalid'},
                       {'since':'2026-11-12', 'until':'2026-11-11'}):
            with self.assertRaises(ValueError):
                query_history(self.path, 'scenes', **kwargs)
