import unittest

from tracking import link_detections


class TrackingTests(unittest.TestCase):
    def test_matches_two_people_even_when_detection_order_changes(self):
        left = (0, 0, 10, 20)
        moved_left = (1, 0, 11, 20)
        right = (30, 0, 40, 20)
        self.assertEqual(link_detections([[left, right], [right, moved_left]]), [
            [(0, left), (1, moved_left)],
            [(0, right), (1, right)],
        ])

    def test_does_not_link_across_a_missing_detection(self):
        box = (0, 0, 10, 20)
        self.assertEqual(link_detections([[box], [], [box]]), [[(0, box)], [(2, box)]])

    def test_splits_ambiguous_matches(self):
        left = (0, 0, 10, 20)
        right = (10, 0, 20, 20)
        middle = (5, 0, 15, 20)
        self.assertEqual(link_detections([[left, right], [middle]]), [
            [(0, left)], [(0, right)], [(1, middle)],
        ])
