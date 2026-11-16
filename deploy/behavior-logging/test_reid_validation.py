import sqlite3,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
from reid_validation import capture_reid_encounters
from exit_observations import parse_exits

class ValidationTest(unittest.TestCase):
 def test_first_frame_gap_strictly_over_three_and_camera_independence(self):
  with tempfile.TemporaryDirectory() as root:
   gallery=SimpleNamespace(db=sqlite3.connect(':memory:'))
   frames=[Image.new('RGB',(100,100),color=c) for c in ['red','blue','green','yellow','black']]
   base=datetime.now(timezone.utc).isoformat()
   request={'scene_id':'a','sample_started_at':base,'sampled_at':base,'sample_fps':1,'camera_id':'a','tracks':[{'track_id':1,'person_id':'alice','detections':[{'frame_index':i,'box_xyxy':[10,10,40,80]} for i in [0,3]]}]}
   capture_reid_encounters(gallery,frames,request,Path(root)/'activities.sqlite3')
   self.assertEqual(gallery.db.execute('select frame_index from reid_encounters').fetchall(),[(0,)])
   request['scene_id']='b';request['tracks'][0]['detections']=[{'frame_index':4,'box_xyxy':[10,10,40,80]}]
   # Four seconds after the last observation, not four seconds after first sighting.
   request['sample_started_at']=datetime.fromtimestamp(datetime.fromisoformat(base).timestamp()+3,timezone.utc).isoformat()
   capture_reid_encounters(gallery,frames,request,Path(root)/'activities.sqlite3')
   self.assertEqual(gallery.db.execute('select frame_index from reid_encounters order by observed_at').fetchall(),[(0,),(4,)])
   capture_reid_encounters(gallery,frames,request,Path(root)/'activities.sqlite3')
   self.assertEqual(gallery.db.execute('select count(*) from reid_encounters').fetchone()[0],2)
   request['camera_id']='b';capture_reid_encounters(gallery,frames,request,Path(root)/'activities.sqlite3')
   self.assertEqual(gallery.db.execute('select count(*) from reid_encounters').fetchone()[0],3)
   self.assertEqual(len(list((Path(root)/'reid-snapshots').glob('*.jpg'))),3)
 def test_exit_requires_outward_track_crossing_and_visual_transition(self):
  frames=[Image.new('RGB',(100,100),'red'),Image.new('RGB',(100,100),'blue')]
  request={'building_exit':{'id':'door','region':[.9,0,1,1]},'frame_size':{'width':100,'height':100}}
  track={'detections':[{'frame_index':0,'box_xyxy':[50,10,70,90]},{'frame_index':1,'box_xyxy':[90,10,100,90]}]}
  row={'exit_id':'door','direction':'outbound','certainty':'clear','start_frame':0,'end_frame':1,'evidence':'Crosses outward through doorway'}
  self.assertEqual(len(parse_exits([row],track,request,frames)),1)
  for change in [{'direction':'inbound'},{'certainty':'unclear'},{'end_frame':0},{'exit_id':'other'}]:self.assertEqual(parse_exits([{**row,**change}],track,request,frames),[])
  self.assertEqual(parse_exits([row],track,request,[frames[0],frames[0]]),[])
