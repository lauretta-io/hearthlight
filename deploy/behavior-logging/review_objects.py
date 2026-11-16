"""Review retained scene crops with existing Qwen; optionally preserve derived evidence."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from uuid import NAMESPACE_URL, uuid5
from PIL import Image
from activity import ActivityStore
from interactions import record as record_interaction
from object_focus import refine
from runner import Models


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scene', action='append', required=True)
    parser.add_argument('--record', action='store_true')
    args = parser.parse_args()
    logs = Path(os.environ.get('BEHAVIOR_LOG_DIR', '/logs'))
    store = ActivityStore(logs / 'person-activities.sqlite3')
    models = Models(os.environ.get('BEHAVIOR_DEVICE', 'cuda'))
    results = []
    try:
        for scene_id in args.scene:
            row = store.db.execute('SELECT payload FROM scene_descriptions WHERE scene_id=?', (scene_id,)).fetchone()
            if not row:
                raise ValueError('scene_not_found')
            scene = json.loads(row[0])
            request = scene['input_request']
            file = request.get('recorded_clip', {}).get('file', '')
            if not re.fullmatch(r'[a-f0-9]{32}/[a-f0-9]{32}\.mp4', file):
                results.append({'scene_id': scene_id, 'status': 'recording_unavailable'})
                continue
            root = (logs / 'person-clips').resolve()
            path = (root / file).resolve()
            if root not in path.parents or not path.is_file():
                raise ValueError('recording_unavailable')
            with tempfile.TemporaryDirectory(prefix='object-review-') as folder:
                subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-i', str(path),
                                '-vsync', '0', '-frames:v', str(request['recorded_clip']['frame_count']),
                                '-q:v', '2', str(Path(folder) / 'frame-%03d.jpg')],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
                frames = [Image.open(p).convert('RGB').copy() for p in sorted(Path(folder).glob('frame-*.jpg'))]
                for track in request['tracks']:
                    if not track.get('detections'):
                        continue
                    try:
                        result = refine(models, frames, track, {}, scene.get('description') or '')
                    except (ValueError, KeyError, TypeError) as error:
                        results.append({'scene_id': scene_id, 'track_id': track['track_id'], 'status': 'review_failed', 'error': str(error)})
                        continue
                    result.update(scene_id=scene_id, track_id=track['track_id'], source_person_id=track.get('person_id'))
                    if args.record:
                        sample = {**scene, 'sample_id': 'object-review:' + scene_id,
                                  'scene_id': scene_id, 'activity_model': models.vlm_id, 'activity_model_revision': models.revisions[models.vlm_id],
                                  'sample_started_at': request.get('sample_started_at'),
                                  'sample_fps': request['sample_fps'],
                                  'behavior_id': uuid5(NAMESPACE_URL, f"behavior:{scene_id}:{track['track_id']}").hex,
                                  'moment': {'evaluation_status': 'historical_review', 'keyframe': False}}
                        positions = {d['frame_index']: i for i, d in enumerate(track['detections'])}
                        events = [{**e, 'start_frame': positions[e['start_frame']], 'end_frame': positions[e['end_frame']]} for e in result['events']]
                        linked_track = [(d['frame_index'], d['box_xyxy']) for d in track['detections']]
                        with store.db:
                            result['recorded_activities'] = store._record(sample, track['track_id'], track.get('person_id'), linked_track,
                                {'description': result['description'], 'events': events})
                            result['recorded_interactions'] = [record_interaction(store.db, {**sample, 'track_id': track['track_id'], 'person_id': track.get('person_id')}, e,
                                uuid5(NAMESPACE_URL, f"object-review-interaction:{scene_id}:{track['track_id']}:{i}").hex) for i, e in enumerate(result['interactions'])]
                    results.append(result)
        destination = logs / 'object-review-results.json'
        destination.write_text(json.dumps({'model_id': models.vlm_id, 'recorded': args.record, 'results': results}, indent=2))
        os.chmod(destination, 0o600)
        print(json.dumps({'model_id': models.vlm_id, 'recorded': args.record, 'results': [{key: row.get(key) for key in ['scene_id', 'track_id', 'status', 'description', 'events', 'interactions']} for row in results]}), flush=True)
    finally:
        store.db.close()


if __name__ == '__main__':
    main()
