import unittest
from PIL import Image
from exit_tracker import CrossingWindow
from compact_context import model_input

CAMERA={'id':'cam','name':'Exit camera','building_exit':{'id':'exit'},'zones':[{'id':'leave','name':'Leave','description':'Doorway approach','kind':'exit','region':[.72,.28,.94,.98],'outboundDirection':'right','entryGate':.4,'exitGate':.7}]}

class ContinuousExitTests(unittest.TestCase):
 def feed(self,window,xs,start=1000):
  jobs=[]
  for i,x in enumerate(xs):
   window.append(Image.new('RGB',(1000,1000)),[[x*1000-40,400,x*1000+40,700]],start+i/4)
   jobs.extend(window.crossings(CAMERA))
  return jobs
 def test_crossing_persists_once_across_rolling_window_without_model(self):
  w=CrossingWindow(size=12)
  jobs=self.feed(w,[.77,.79,.81,.83,.85,.87,.89,.90,.91,.92,.93,.94,.95,.96,.97])
  self.assertEqual(len(jobs),1)
  sample,request,analysis,frames=jobs[0]
  self.assertEqual(analysis['persons'][0]['exits'][0]['evidence_method'],'tracked_zone_crossing')
  self.assertEqual(sample['sample_fps'],4)
  self.assertEqual(request['tracks'][0]['person_id'],None)
  self.assertEqual(request['scene_id'],sample['sample_id'])
 def test_inbound_gap_disappearance_never_become_exit(self):
  for xs in [[.93,.90,.87,.85,.83,.81,.79,.77],[.77,.79,.81,.83,.85]]:
   self.assertEqual(self.feed(CrossingWindow(),xs),[])
  w=CrossingWindow();self.feed(w,[.77,.79,.81,.83]);self.assertEqual(self.feed(w,[.85,.87,.89],start=1010),[])
 def test_crossing_commits_to_history_without_any_language_model(self):
  import tempfile,json
  from pathlib import Path
  from activity import ActivityStore
  sample,request,analysis,frames=self.feed(CrossingWindow(),[.77,.79,.81,.83,.85,.87,.89])[0]
  sample.update(activity_model='directional-person-tracker',activity_model_revision='continuous-v1')
  with tempfile.TemporaryDirectory() as folder:
   store=ActivityStore(Path(folder)/'history.sqlite3')
   result=store.record_analysis(sample,request,analysis,None,'tracked')
   self.assertEqual(result['behaviors'][0]['exits'][0]['certainty'],'clear')
   self.assertEqual(store.db.execute('SELECT COUNT(*) FROM person_behaviors').fetchone()[0],1)
   self.assertIsNone(result['scene']['raw_model_output'])
   self.assertFalse(store.record_analysis(sample,request,analysis,None,'tracked')['inserted'])
   store.db.close()
 def test_compact_input_retains_times_zones_and_prior_state_without_boxes(self):
  w=CrossingWindow();job=self.feed(w,[.77,.79,.81,.83,.85,.87,.89])[0]
  request=job[1];track=request['tracks'][0]
  track['prior_state']=[{'reference_key':'phone|white','item':'phone'}]
  short,catalog=model_input(request,list(range(7)))
  t=short['tracks'][0]
  self.assertNotIn('detections',t);self.assertNotIn('person_id',t)
  self.assertEqual(t['duration_seconds'],1.5);self.assertEqual(t['zones'][0]['name'],'Leave')
  self.assertEqual(t['prior_state'],track['prior_state']);self.assertIn('detections',catalog['tracks'][0])

if __name__=='__main__':unittest.main()
