"""Bounded representative person snapshots; separate files for every camera."""
from hashlib import sha256
from pathlib import Path
import os
from uuid import uuid4


def capture_snapshots(frames, request, database):
    root = Path(database).parent / 'person-snapshots'
    for track in request['tracks']:
        if not track['person_id'] or not track['detections']:
            continue
        detection = max(track['detections'], key=lambda d: (d['box_xyxy'][2]-d['box_xyxy'][0]) * (d['box_xyxy'][3]-d['box_xyxy'][1]))
        frame = frames[detection['frame_index']]
        x1,y1,x2,y2 = detection['box_xyxy']
        box = (max(0,x1),max(0,y1),min(frame.width,x2),min(frame.height,y2))
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        key = sha256(f"{request['camera_id']}:{track['person_id']}".encode()).hexdigest()
        folder = root / key
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = folder / f'{uuid4().hex}.jpg'
        image = frame.crop(box)
        image.thumbnail((320,480))
        with path.open('xb') as output:
            os.chmod(path,0o600)
            image.convert('RGB').save(output,format='JPEG',quality=85)
        track['snapshot_file'] = str(path.relative_to(root))
        track['snapshot_frame'] = detection['frame_index']


def prune_snapshots(request, database):
    # Keep the current and previous committed snapshot for each person/camera.
    # Historical observations retain their text/frame references; these images
    # are representatives rather than a recording archive.
    root = Path(database).parent / 'person-snapshots'
    for track in request['tracks']:
        if not track.get('snapshot_file'):
            continue
        current = root / track['snapshot_file']
        files = sorted(current.parent.glob('*.jpg'), key=lambda p:p.stat().st_mtime_ns, reverse=True)
        for old in [p for p in files if p != current][1:]:
            old.unlink(missing_ok=True)
