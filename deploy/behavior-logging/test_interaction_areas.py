import unittest,json
from PIL import Image
from scene import build_request,parse_scene

class InteractionAreaTests(unittest.TestCase):
 def test_display_contact_is_annotated_only_for_valid_configured_area(self):
  frames=[Image.new('RGB',(64,64),c) for c in ['red','blue']]
  sample={'sample_id':'sample','camera_id':'cam','sampled_at':'2026-11-16T12:00:00Z','sample_fps':2,'zones':[{'id':'display','name':'Display','kind':'context','itemHoldingArea':True,'description':'Merchandise display','region':[.2,.2,.8,.8],'outboundDirection':'right'}]}
  request=build_request(sample,frames,[[(i,(5,5,50,60)) for i in range(2)]],['person'])
  item={'target_kind':'object','interaction_type':'touch','item':'shirt','appearance':'blue','actor_track_id':1,'certainty':'clear','evidence':'Hand touches displayed shirt','start_frame':0,'end_frame':1,'interaction_area_id':'display','interaction_target_role':'displayed_item'}
  report={'track_id':1,'description':'Touching a displayed shirt.','new_interactions':[item],'ended_interactions':[],'new_possessions':[],'ended_possessions':[],'exits':[]}
  def parse():return parse_scene(json.dumps({'scene_description':'Display area.','persons':[report]}),request,frames)['persons'][0]
  row=parse()['interactions'][0];self.assertEqual(row['interaction_area_id'],'display')
  item['interaction_area_id']='invented';row=parse()['interactions'][0];self.assertNotIn('interaction_area_id',row)
  item['interaction_area_id']='display';sample['zones'][0]['itemHoldingArea']=False;request['zones']=sample['zones'];self.assertNotIn('interaction_area_id',parse()['interactions'][0])
 def test_displayed_held_item_can_qualify_without_a_pickup_frame(self):
  frames=[Image.new('RGB',(64,64),c) for c in ['red','blue']]
  sample={'sample_id':'sample','camera_id':'cam','sampled_at':'2026-11-16T12:00:00Z','sample_fps':2,'zones':[{'id':'display','name':'Display','kind':'context','itemHoldingArea':True,'description':'Merchandise display','region':[.2,.2,.8,.8],'outboundDirection':'right'}]}
  request=build_request(sample,frames,[[(i,(5,5,50,60)) for i in range(2)]],['person'])
  report={'track_id':1,'description':'Holding displayed shirt.','new_interactions':[],'ended_interactions':[],'new_possessions':[{'action':'hold','item':'shirt','appearance':'blue','actor_track_id':1,'certainty':'clear','evidence':'Holding a shirt from the display.','start_frame':0,'end_frame':1,'interaction_area_id':'display','interaction_target_role':'displayed_item'}],'ended_possessions':[],'exits':[]}
  row=parse_scene(json.dumps({'scene_description':'Display.','persons':[report]}),request,frames)['persons'][0]
  self.assertEqual(row['events'][0]['action'],'hold');self.assertEqual(row['events'][0]['interaction_area_id'],'display')
