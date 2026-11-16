import unittest
from zone_explanations import zone_reports,zone_explanation
import test_zone_crossings as crossing_fixture

class ZoneExplanationTests(unittest.TestCase):
 def test_zone_context_and_actual_crossing_are_both_explained(self):
  request=crossing_fixture.ZoneCrossingTests().request();request.update(tracking_status='ready',frame_count=5)
  report=zone_reports(request)[0]
  self.assertEqual(report['occupied_frames'],3);self.assertEqual(report['outbound_crossings'],1)
  text=zone_explanation([report]);self.assertIn('Leave (exit)',text);self.assertIn('left to right',text);self.assertIn('left 72%',text);self.assertIn('3/5 sampled frames',text)
 def test_unoccupied_zone_is_still_included_and_presence_is_not_contact(self):
  request=crossing_fixture.ZoneCrossingTests().request([.2,.3,.4]);request.update(tracking_status='ready',frame_count=3)
  report=zone_reports(request)[0];self.assertEqual(report['occupied_frames'],0);self.assertNotIn('interactions',report)
  self.assertIn('0/3 sampled frames',zone_explanation([report]))
 def test_unavailable_tracking_does_not_assert_an_empty_zone(self):
  request=crossing_fixture.ZoneCrossingTests().request();request.update(tracking_status='unavailable',frame_count=5)
  text=zone_explanation(zone_reports(request));self.assertIn('unavailable',text);self.assertNotIn('0 outbound crossings',text)
