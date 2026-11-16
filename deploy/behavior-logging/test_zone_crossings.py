import unittest
from zone_crossings import crossing_events,attach_crossings,ground_exit_descriptions

class ZoneCrossingTests(unittest.TestCase):
 def request(self,xs=None):
  xs=xs or [.6,.76,.83,.92,.98]
  return {'frame_size':{'width':1000,'height':1000},'building_exit':{'id':'building-exit'},'zones':[{'id':'leave','name':'Leave','kind':'exit','description':'Exit approach','outboundDirection':'right','region':[.72,.28,.94,.98]}],
   'tracks':[{'track_id':1,'person_id':None,'detections':[{'frame_index':i,'box_xyxy':[x*1000-20,400,x*1000+20,700]} for i,x in enumerate(xs)]}]}
 def test_outbound_crossing_uses_one_track_and_preserves_frame_evidence(self):
  row=crossing_events(self.request())[1][0]
  self.assertEqual(row['direction'],'outbound');self.assertEqual(row['evidence_method'],'tracked_zone_crossing');self.assertEqual((row['start_frame'],row['end_frame']),(0,4));self.assertEqual(row['inside_frame_count'],3)
 def test_inbound_stationary_disappearance_or_reversal_do_not_exit(self):
  for xs in [[.98,.92,.83,.76,.6],[.8]*5,[.6,.76,.83],[.6,.76,.83,.76,.6],[.8,.83,.92,.98]]:
   self.assertEqual(crossing_events(self.request(xs)),{})
 def test_missing_frames_or_fragmented_tracks_cannot_be_stitched_into_exit(self):
  r=self.request();r['tracks'][0]['detections'][-1]['frame_index']=10
  self.assertEqual(crossing_events(r),{})
  r=self.request();track=r['tracks'][0];track['person_id']='same-id';r['tracks']=[{**track,'detections':track['detections'][:3]},{**track,'track_id':2,'detections':track['detections'][3:]}]
  self.assertEqual(crossing_events(r),{})
 def test_other_direction_and_wrong_zone_edge(self):
  r=self.request();r['zones'][0]['outboundDirection']='left';self.assertEqual(crossing_events(r),{})
  for d in r['tracks'][0]['detections']:d['box_xyxy'][1]=0;d['box_xyxy'][3]=100
  self.assertEqual(crossing_events(r),{})
 def test_tracker_evidence_survives_missing_scene_model_output(self):
  analysis=attach_crossings(None,self.request());report=analysis['persons'][0]
  self.assertTrue(report['description']);self.assertEqual(len(report['exits']),1)
 def test_same_exit_model_proposal_is_replaced_by_tracked_evidence(self):
  analysis={'persons':[{'track_id':1,'description':'Walking','events':[],'exits':[{'exit_id':'building-exit'}]}]}
  report=attach_crossings(analysis,self.request())['persons'][0]
  self.assertEqual(len(report['exits']),1);self.assertEqual(report['exits'][0]['evidence_method'],'tracked_zone_crossing')

class DirectionalGateTests(unittest.TestCase):
 def test_visible_passage_inside_oversized_area_crosses_calibrated_lines(self):
  values=[.785,.802,.818,.830,.823,.827,.813,.816,.828,.843,.905]
  request=ZoneCrossingTests().request(values)
  request['zones'][0].update(entryGate=.4,exitGate=.7)
  result=crossing_events(request)
  self.assertEqual(len(result[1]),1);self.assertEqual(result[1][0]['end_frame'],10)
  request['tracks'][0]['detections'].reverse()
  for i,d in enumerate(request['tracks'][0]['detections']):d['frame_index']=i
  self.assertEqual(crossing_events(request),{})

class DirectionGroundingTests(unittest.TestCase):
 def test_roomward_tracks_cannot_be_described_as_outbound(self):
  request=ZoneCrossingTests().request([.9,.85,.8,.7,.6])
  value={'persons':[{'track_id':1,'description':'A person walks left to right through the Leave zone.','exits':[]}]}
  report=ground_exit_descriptions(value,request)['persons'][0]
  self.assertIn('right to left',report['description']);self.assertIn('toward the room',report['description'])
  self.assertIn('left to right',report['model_description_before_zone_check'])

if __name__=='__main__':unittest.main()
