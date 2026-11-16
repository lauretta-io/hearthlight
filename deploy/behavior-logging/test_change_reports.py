import json,sqlite3,unittest
from PIL import Image
from scene import build_request,parse_scene
from moments import initialize,prepare,commit

class ChangeReportTests(unittest.TestCase):
 def setUp(self):
  self.frames=[Image.new('RGB',(64,64),c) for c in ['red','green','blue']]
  self.sample={'sample_id':'s','camera_id':'c','sampled_at':'2026-11-16T12:00:00Z','sample_fps':2}
  self.request=build_request(self.sample,self.frames,[[(i,(1,1,60,60)) for i in range(3)]],['p'])
 def report(self,**changes):
  return {'track_id':1,'description':'Visible actions.','new_interactions':[],'ended_interactions':[],'new_possessions':[],'ended_possessions':[],**changes}
 def interaction(self,**patch):
  return {'target_kind':'object','interaction_type':'touch','item':'shelf','appearance':'metal','actor':'target','certainty':'clear','start_frame':0,'end_frame':2,'evidence':'Hand moves away from the shelf.',**patch}
 def item(self,**patch):
  return {'action':'put_down','item':'bottle','appearance':'white','actor':'target','certainty':'clear','start_frame':0,'end_frame':2,'evidence':'Bottle moves from hand to table.',**patch}
 def parse(self,report):return parse_scene(json.dumps({'scene_description':'A room with shelves.','persons':[report]}),self.request,self.frames)['persons'][0]
 def test_explicit_ends_are_kept_separate_from_new_contact_and_release_updates_items(self):
  report=self.parse(self.report(ended_interactions=[self.interaction()],ended_possessions=[self.item()]))
  self.assertEqual(report['interactions'],[]);self.assertEqual(report['events'][0]['action'],'put_down')
  self.assertEqual(len(report['state_changes']['ended_interactions']),1)
  self.assertEqual(set(report['state_changes']),{'new_interactions','ended_interactions','new_possessions','ended_possessions'})
 def test_missing_item_is_uncertain_candidate_not_a_release(self):
  report=self.parse(self.report(ended_possessions=[self.item(action='no_longer_visible',certainty='unclear')]))
  self.assertEqual(report['events'][0]['action'],'unclear');self.assertEqual(report['state_changes']['ended_possessions'][0]['certainty'],'unclear')
 def test_clear_single_frame_end_is_rejected_and_fixture_cannot_be_released(self):
  report=self.parse(self.report(ended_interactions=[self.interaction(start_frame=2)],ended_possessions=[self.item(item='shelf')]))
  self.assertEqual(report['state_changes']['ended_interactions'],[]);self.assertEqual(report['events'],[])
 def test_known_reference_anchors_an_end_to_existing_object_description(self):
  self.request['tracks'][0]['prior_state']=[{'reference_key':'bottle|white','target_kind':'object','item':'bottle','appearance':'white'}]
  report=self.parse(self.report(ended_possessions=[self.item(reference_key='bottle|white',item='object',appearance='light')]))
  self.assertEqual(report['events'][0]['item'],'bottle')
  bad=self.parse(self.report(ended_possessions=[self.item(reference_key='invented')]))
  self.assertEqual(bad['events'],[])
 def test_uncertain_end_keeps_existing_possession(self):
  db=sqlite3.connect(':memory:');initialize(db);track=self.request['tracks'][0]
  evaluate=lambda *a,**k:json.dumps({'summary':'Visible behavior.','behavior_changed':False,'matched_rule_ids':[]})
  first=self.parse(self.report(new_possessions=[self.item(action='hold')]))
  one=prepare(db,self.sample,track,first,'Room',evaluate)
  with db:commit(db,one)
  later={**self.sample,'sample_id':'later','sampled_at':'2026-11-16T12:00:10Z'}
  two=prepare(db,later,track,self.parse(self.report(ended_possessions=[self.item(action='no_longer_visible',certainty='unclear')])),'Room',evaluate)
  self.assertEqual(two['possessions']['bottle|white']['state'],'with_person')
  self.assertEqual(two['state_changes']['ended_possessions'][0]['certainty'],'unclear')
  self.assertTrue(two['keyframe']);db.close()
 def test_explicit_contact_end_creates_keyframe_and_ends_active_contact(self):
  db=sqlite3.connect(':memory:');initialize(db)
  track=self.request['tracks'][0]
  first=self.parse(self.report(new_interactions=[self.interaction()]))
  evaluate=lambda *a,**k:json.dumps({'summary':'Visible behavior.','behavior_changed':False,'matched_rule_ids':[]})
  one=prepare(db,self.sample,track,first,'Room',evaluate)
  with db:commit(db,one)
  later={**self.sample,'sample_id':'later','sampled_at':'2026-11-16T12:00:10Z'}
  two=prepare(db,later,track,self.parse(self.report(ended_interactions=[self.interaction()])),'Room',evaluate)
  self.assertTrue(two['keyframe']);self.assertEqual(two['interaction_states']['shelf|metal']['status'],'ended')
  db.close()
