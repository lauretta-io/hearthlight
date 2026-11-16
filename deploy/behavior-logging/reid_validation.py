"""Durable first-frame evidence after an observed identity gap of >3 seconds."""
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import os
import time


def capture_reid_encounters(gallery, frames, request, database):
    db = gallery.db
    db.execute('''CREATE TABLE IF NOT EXISTS reid_encounters (
        id TEXT PRIMARY KEY, person_id TEXT NOT NULL, camera_id TEXT NOT NULL,
        observed_at REAL NOT NULL, gap_seconds REAL, scene_id TEXT NOT NULL,
        frame_index INTEGER NOT NULL, image_file TEXT NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS reid_encounters_time ON reid_encounters(observed_at)')
    db.execute('''CREATE TABLE IF NOT EXISTS reid_camera_seen (
        person_id TEXT NOT NULL, camera_id TEXT NOT NULL, last_seen REAL NOT NULL,
        PRIMARY KEY(person_id,camera_id))''')
    base = datetime.fromisoformat(request['sample_started_at'] or request['sampled_at']).timestamp()
    fps = request['sample_fps']
    root = Path(database).parent / 'reid-snapshots'
    root.mkdir(exist_ok=True, mode=0o700)
    with db:
        cutoff = time.time() - 30*86400
        for key,file in db.execute('SELECT id,image_file FROM reid_encounters WHERE observed_at<? LIMIT 1000',(cutoff,)).fetchall():
            if len(file)==68 and file.endswith('.jpg') and all(c in '0123456789abcdef' for c in file[:-4]):
                (root/file).unlink(missing_ok=True)
            db.execute('DELETE FROM reid_encounters WHERE id=?',(key,))
        for track in request['tracks']:
            person = track['person_id']
            if not person:
                continue
            previous = db.execute('SELECT last_seen FROM reid_camera_seen WHERE person_id=? AND camera_id=?',
                                  (person, request['camera_id'])).fetchone()
            last = previous[0] if previous else None
            for detection in sorted(track['detections'], key=lambda d: d['frame_index']):
                index = detection['frame_index']
                observed = base + index / fps
                if last is None or observed - last > 3:
                    key = sha256(f"{request['camera_id']}:{request['scene_id']}:{track['track_id']}:{index}".encode()).hexdigest()
                    path = root / f'{key}.jpg'
                    frame = frames[index]
                    x1,y1,x2,y2 = detection['box_xyxy']
                    box = (max(0,x1),max(0,y1),min(frame.width,x2),min(frame.height,y2))
                    if box[2] > box[0] and box[3] > box[1]:
                        image = frame.crop(box)
                        image.thumbnail((160,240))
                        if not path.exists():
                            with path.open('xb') as output:
                                os.chmod(path,0o600)
                                image.convert('RGB').save(output,format='JPEG',quality=85)
                        db.execute('INSERT OR IGNORE INTO reid_encounters VALUES (?,?,?,?,?,?,?,?)',
                                   (key,person,request['camera_id'],observed,None if last is None else observed-last,
                                    request['scene_id'],index,path.name))
                last = max(last or observed, observed)
            if last is not None:
                db.execute('''INSERT INTO reid_camera_seen VALUES (?,?,?) ON CONFLICT(person_id,camera_id)
                    DO UPDATE SET last_seen=MAX(last_seen,excluded.last_seen)''',(person,request['camera_id'],last))
