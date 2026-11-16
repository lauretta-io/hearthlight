"""Retained, playable clips of the actual sampled camera frames."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

_last_cleanup = 0


def prune_clips(database):
    global _last_cleanup
    retention = float(os.environ.get('BEHAVIOR_CLIP_RETENTION_HOURS','0'))
    if retention <= 0 or (_last_cleanup and time.monotonic()-_last_cleanup <= 1800):
        return
    root = Path(database).parent / 'person-clips'
    cutoff = time.time()-retention*3600
    for old in root.glob('*/*.mp4'):
        if old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)
            old.with_suffix('.jpg').unlink(missing_ok=True)
    _last_cleanup = time.monotonic()


def capture_clip(frames, request, database):
    if not frames:
        return
    fps = float(request['sample_fps'])
    if fps <= 0 or len(frames) < 2:
        return
    root = Path(database).parent / 'person-clips'
    folder = root / sha256(request['camera_id'].encode()).hexdigest()[:32]
    folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    path = folder / f'{uuid4().hex}.mp4'
    temporary = path.with_suffix('.tmp.mp4')
    first = frames[0]
    try:
        result = subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',
            '-f','rawvideo','-pixel_format','rgb24','-video_size',f'{first.width}x{first.height}',
            '-framerate',str(fps),'-i','pipe:0','-an','-c:v','libx264','-preset','veryfast',
            '-crf','25','-threads','1','-pix_fmt','yuv420p','-movflags','+faststart',str(temporary)],
            input=b''.join(frame.convert('RGB').tobytes() for frame in frames),
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
        if result.returncode:
            raise RuntimeError('sample_clip_encoding_failed')
        os.chmod(temporary,0o600)
        temporary.replace(path)
        index = min((d['frame_index'] for t in request['tracks'] for d in t.get('detections', [])),default=0)
        frames[index].convert('RGB').save(path.with_suffix('.jpg'),format='JPEG',quality=80)
        os.chmod(path.with_suffix('.jpg'),0o600)
    finally:
        temporary.unlink(missing_ok=True)
    start = request.get('sample_started_at') or request['sampled_at']
    end = datetime.fromisoformat(start) + timedelta(seconds=len(frames)/fps)
    request['recorded_clip'] = {'file':str(path.relative_to(root)), 'start_at':start,
        'end_at':end.isoformat(), 'duration_seconds':len(frames)/fps,
        'kind':'sampled_frames','sample_fps':fps,'frame_count':len(frames)}
    retention = float(os.environ.get('BEHAVIOR_CLIP_RETENTION_HOURS','0'))
    if retention > 0:
        request['recorded_clip']['expires_at'] = (datetime.now(timezone.utc)+timedelta(hours=retention)).isoformat()
    prune_clips(database)
