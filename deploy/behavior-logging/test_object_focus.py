import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock
from PIL import Image
from object_focus import refine, needed
from clips import capture_clip

class ObjectFocusTests(unittest.TestCase):
    def setUp(self):
        self.frames = [Image.new('RGB', (64, 64), color) for color in ['white', 'red', 'blue', 'green', 'yellow', 'black']]
        self.track = {'track_id': 1, 'person_id': None, 'detections': [{'frame_index': i, 'box_xyxy': [2, 2, 60, 60]} for i in [2, 5]]}
        self.model = Mock(vlm_id='existing-qwen')
    def evaluate(self, events, interactions=None):
        self.model.describe.return_value=json.dumps({'description':'Visible object handling.','events':events,'interactions':interactions or []})
        return refine(self.model,self.frames,self.track,{},'Office')
    def item(self, item='water bottle', appearance='white'):
        return {'action':'hold','item':item,'appearance':appearance,'start_frame':0,'end_frame':1,'actor':'target','certainty':'clear','evidence':'Object visible in the hand.'}
    def test_specific_object_evidence_preserves_original_frame_indices_without_an_identity(self):
        result=self.evaluate([self.item()]);self.assertEqual(result['events'][0]['item'],'water bottle')
        self.assertEqual((result['events'][0]['start_frame'],result['events'][0]['end_frame']),(2,5))
        self.assertNotIn('water bottle',self.model.describe.call_args.args[1])
    def test_fixture_contact_is_not_a_possession(self):
        result=self.evaluate([self.item('shelves','metal')]);self.assertEqual(result['events'],[])
        self.assertEqual(result['interactions'][0]['interaction_type'],'touch')
    def test_laptop_use_can_be_an_interaction_without_being_held(self):
        interaction={**self.item('laptop','black'),'target_kind':'object','interaction_type':'use'}
        result=self.evaluate([], [interaction]);self.assertEqual(result['events'],[])
        self.assertEqual(result['interactions'][0]['interaction_type'],'use')
    def test_invalid_interaction_does_not_discard_valid_item_evidence(self):
        invalid={**self.item('laptop','black'),'target_kind':'object','interaction_type':'use'}
        del invalid['certainty']
        result=self.evaluate([self.item()], [invalid])
        self.assertEqual(len(result['events']),1)
        self.assertEqual(result['interactions'],[])
        self.assertEqual(len(result['rejected_entries']),1)
    def test_explicit_object_name_in_target_kind_is_a_format_error_not_missing_evidence(self):
        interaction={**self.item('laptop','black'),'target_kind':'laptop','interaction_type':'use'}
        result=self.evaluate([], [interaction]);self.assertEqual(result['interactions'][0]['target_kind'],'object')
        self.assertEqual(result['interactions'][0]['certainty'],'clear')
    def test_format_normalization_does_not_promote_uncertain_actor_or_certainty(self):
        interaction={**self.item('laptop','black'),'target_kind':'laptop','interaction_type':'use','actor':'unclear','certainty':'unclear'}
        result=self.evaluate([], [interaction]);self.assertEqual(result['interactions'][0]['actor'],'unclear')
        self.assertEqual(result['interactions'][0]['certainty'],'unclear')
    def test_empty_object_evidence_does_not_invent_an_association(self):
        result=self.evaluate([]);self.assertEqual(result['events'],[]);self.assertEqual(result['interactions'],[])
    def test_vague_object_description_requests_a_focused_review(self):
        self.assertTrue(needed(self.track,{'description':'Holding a white object.','events':[]}))
        self.assertFalse(needed(self.track,{'description':'Walking past the desk.','events':[]}))
    def test_described_table_or_computer_contact_without_structured_interactions_requests_review(self):
        self.assertTrue(needed(self.track,{'description':'Typing on a laptop at the table.','events':[],'interactions':[]}))
        self.assertTrue(needed(self.track,{'description':'Touching the shelves.','events':[],'interactions':[]}))
        self.assertFalse(needed(self.track,{'description':'Standing near the shelves.','events':[],'interactions':[]}))
    def test_unidentified_actor_with_detections_still_retains_a_clip(self):
        with TemporaryDirectory() as folder:
            request={'camera_id':'camera','sampled_at':'2026-11-16T12:00:00+00:00','sample_fps':2,'tracks':[self.track]}
            capture_clip(self.frames,request,Path(folder)/'history.sqlite3')
            self.assertTrue((Path(folder)/'person-clips'/request['recorded_clip']['file']).is_file())

if __name__=='__main__':unittest.main()
