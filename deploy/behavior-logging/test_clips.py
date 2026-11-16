from pathlib import Path
from tempfile import TemporaryDirectory
import json
import subprocess
import unittest
import os
import time
from unittest.mock import patch
import clips
from PIL import Image
from clips import capture_clip

class ClipTests(unittest.TestCase):
    def test_captured_frames_become_a_playable_clip_with_true_sample_timing(self):
        with TemporaryDirectory() as folder:
            request={'camera_id':'camera','sample_fps':2,'sample_started_at':'2026-11-13T00:00:00+00:00','sampled_at':'2026-11-13T00:00:02+00:00',
                     'tracks':[{'person_id':'alice','detections':[{'frame_index':0},{'frame_index':2}]}]}
            frames=[Image.new('RGB',(64,64),c) for c in ['red','blue','green','white']]
            capture_clip(frames,request,Path(folder)/'db.sqlite3')
            clip=request['recorded_clip'];path=Path(folder)/'person-clips'/clip['file']
            self.assertTrue(path.is_file());self.assertTrue(path.with_suffix('.jpg').is_file())
            self.assertEqual(clip['duration_seconds'],2)
            self.assertEqual(clip['end_at'],'2026-11-13T00:00:02+00:00')
            info=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=nb_frames,avg_frame_rate','-of','json',str(path)]))
            self.assertEqual(info['streams'][0]['nb_frames'],'4')
            self.assertEqual(info['streams'][0]['avg_frame_rate'],'2/1')

    def test_unidentified_or_empty_sightings_do_not_create_recordings(self):
        with TemporaryDirectory() as folder:
            request={'tracks':[{'person_id':None}]}
            capture_clip([],request,Path(folder)/'db.sqlite3')
            self.assertNotIn('recorded_clip',request)

    def test_camera_scene_remains_reviewable_when_no_person_was_detected(self):
        with TemporaryDirectory() as folder:
            request={'camera_id':'empty-camera','sample_fps':2,'sampled_at':'2026-11-16T12:00:00+00:00','tracks':[]}
            capture_clip([Image.new('RGB',(64,64),'white')]*2,request,Path(folder)/'db.sqlite3')
            self.assertIn('recorded_clip',request)
            self.assertTrue((Path(folder)/'person-clips'/request['recorded_clip']['file']).is_file())
    def test_expiry_uses_the_selected_thirty_day_policy_and_preserves_newer_footage(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)/'person-clips'/'a'
            root.mkdir(parents=True)
            old=root/'old.mp4';old.write_bytes(b'old');old.with_suffix('.jpg').write_bytes(b'preview')
            recent=root/'recent.mp4';recent.write_bytes(b'new')
            now=time.time();os.utime(old,(now-31*86400,now-31*86400));os.utime(recent,(now-29*86400,now-29*86400))
            request={'camera_id':'camera','sample_fps':2,'sample_started_at':'2026-11-13T00:00:00+00:00','sampled_at':'2026-11-13T00:00:01+00:00','tracks':[{'person_id':'alice','detections':[{'frame_index':0}]}]}
            clips._last_cleanup=0
            with patch.dict(os.environ,{'BEHAVIOR_CLIP_RETENTION_HOURS':'720'}):
                clips.prune_clips(Path(folder)/'db.sqlite3')
                capture_clip([Image.new('RGB',(64,64),'red')]*2,request,Path(folder)/'db.sqlite3')
            self.assertIn('expires_at',request['recorded_clip'])
            self.assertFalse(old.exists());self.assertFalse(old.with_suffix('.jpg').exists());self.assertTrue(recent.exists())

if __name__=='__main__':unittest.main()
