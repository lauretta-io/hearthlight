import unittest
from interaction_format import normalize_object_kind
from runner import scene_token_budget

class InteractionFormatTests(unittest.TestCase):
 def test_object_kind_alias_does_not_change_attribution_or_person_targets(self):
  value={'target_kind':'laptop','item':'laptop','interaction_type':'use','actor':'unclear','certainty':'unclear'}
  result=normalize_object_kind(value);self.assertEqual(result['target_kind'],'object');self.assertEqual(result['actor'],'unclear');self.assertEqual(result['certainty'],'unclear')
  person={**value,'target_kind':'person','target_track_id':2};self.assertEqual(normalize_object_kind(person),person)
  self.assertEqual(normalize_object_kind({**value,'item':'person'}),{**value,'item':'person'})
 def test_multi_track_response_budget_scales_and_is_bounded(self):
  self.assertEqual(scene_token_budget({'tracks':[{}],'zones':[]}),1536)
  self.assertGreater(scene_token_budget({'tracks':[{}]*11,'zones':[{}]}),2048)
  self.assertEqual(scene_token_budget({'tracks':[{}]*100,'zones':[{}]*20}),8192)
