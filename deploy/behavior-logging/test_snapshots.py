from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from PIL import Image
from snapshots import capture_snapshots, prune_snapshots

class SnapshotTests(unittest.TestCase):
    def test_person_crops_are_camera_scoped_bounded_and_unidentified_people_are_skipped(self):
        with TemporaryDirectory() as folder:
            db=Path(folder)/'history.sqlite3'
            frames=[Image.new('RGB',(640,360),'red')]
            def request(camera='a',person='alice'):
                return {'camera_id':camera,'tracks':[{'track_id':1,'person_id':person,'detections':[{'frame_index':0,'box_xyxy':[10,10,100,300]}]}]}
            for _ in range(4):
                r=request();capture_snapshots(frames,r,db);prune_snapshots(r,db)
            files=list((Path(folder)/'person-snapshots').glob('*/*.jpg'))
            self.assertEqual(len(files),2)
            image=Image.open(Path(folder)/'person-snapshots'/r['tracks'][0]['snapshot_file'])
            self.assertEqual(image.size,(90,290));image.close()
            other=request('private');capture_snapshots(frames,other,db);prune_snapshots(other,db)
            self.assertNotEqual(Path(r['tracks'][0]['snapshot_file']).parent,Path(other['tracks'][0]['snapshot_file']).parent)
            unknown=request(person=None);capture_snapshots(frames,unknown,db)
            self.assertNotIn('snapshot_file',unknown['tracks'][0])
            self.assertEqual(len(list((Path(folder)/'person-snapshots').glob('*/*.jpg'))),3)

if __name__=='__main__':unittest.main()
