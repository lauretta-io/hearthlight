from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from activity import ActivityStore, parse_activity


def event(action="pick_up", **changes):
    return {"action": action, "item": "bottle", "appearance": "blue water bottle",
            "start_frame": 0, "end_frame": 2, "actor": "target", "certainty": "clear",
            "evidence": "bottle moves from the table into the boxed person's hand", **changes}


class ActivityTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "activities.sqlite3"
        self.store = ActivityStore(self.path)
        self.addCleanup(self.store.db.close)
        self.sample = {"sample_id": "clip-one", "camera_id": "camera-one",
                       "sampled_at": datetime.now(timezone.utc).isoformat()}
        self.track = [(0, (0, 0, 10, 10)), (1, (0, 0, 10, 10)), (2, (0, 0, 10, 10))]

    def record(self, events, person_id="person-one", sample=None):
        return self.store.record(sample or self.sample, 1, person_id, self.track,
                                 {"description": "visible activity", "events": events})

    def test_rejects_unsupported_transitions_and_frames(self):
        for bad in (event(start_frame=2, end_frame=2), event(end_frame=3),
                    event(start_frame=True), event(action="steals")):
            with self.assertRaises(ValueError):
                parse_activity(json.dumps({"description": "activity", "events": [bad]}), 3)

    def test_invalid_json_and_missing_events_are_rejected(self):
        for raw in ("person holding a bottle", '{"description":"activity"}', '{"description":"activity", "events":"invalid"}'):
            with self.assertRaises(ValueError):
                parse_activity(raw, 3)

    def test_pickup_and_release_persist_across_restart(self):
        pickup, = self.record([event()])
        later = {**self.sample, "sample_id": "clip-two", "camera_id": "camera-two",
                 "sampled_at": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()}
        release, = self.record([event("put_down")], sample=later)
        self.assertEqual(pickup["item_id"], release["item_id"])
        reopened = ActivityStore(self.path)
        self.addCleanup(reopened.db.close)
        self.assertEqual(reopened.db.execute(
            "SELECT person_id, last_observed_state FROM person_items"
        ).fetchall(), [("person-one", "observed_released")])

    def test_ambiguous_and_unidentified_tracks_do_not_assign_possession(self):
        rows = self.record([event(actor="unclear"), event(certainty="unclear")])
        unidentified = self.record([event()], person_id=None,
                                   sample={**self.sample, "sample_id": "unknown-person"})
        self.assertTrue(all(row["possession_status"] == "unclear" for row in rows + unidentified))
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM person_items").fetchone(), (0,))

    def test_retries_preserve_state_without_duplicate_events(self):
        self.record([event()])
        self.assertEqual(self.record([event()]), [])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM activities").fetchone(), (1,))
        self.assertEqual(self.store.db.execute("SELECT visibility FROM person_items").fetchone(), ("observed",))

    def test_same_description_for_different_people_has_separate_associations(self):
        one, = self.record([event()])
        two, = self.record([event()], person_id="person-two",
                           sample={**self.sample, "sample_id": "other-person"})
        self.assertNotEqual(one["item_id"], two["item_id"])

    def test_empty_followup_marks_item_unobserved_without_inventing_release(self):
        self.record([event()])
        later = {**self.sample, "sample_id": "clip-two",
                 "sampled_at": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()}
        self.record([], sample=later)
        self.assertEqual(self.store.db.execute(
            "SELECT last_observed_state, visibility FROM person_items"
        ).fetchone(), ("observed_with_person", "unobserved"))

    def test_transition_on_frozen_video_is_rejected(self):
        from PIL import Image
        image = Image.new("RGB", (64, 64))
        with self.assertRaisesRegex(ValueError, "identical_frames"):
            parse_activity(json.dumps({"description": "activity", "events": [event()]}),
                           3, [image, image.copy(), image.copy()])

    def test_logger_entry_point_links_valid_activity_to_reid_person(self):
        from unittest.mock import Mock
        from PIL import Image
        from runner import analyze_sample

        detector = Mock()
        detector.detect.return_value = [[(0, 0, 40, 60)]] * 3
        models = Mock(vlm_id="fixture-model", revisions={"fixture-model": "fixture-revision"})
        models.visual_matches.return_value = []
        models.describe.return_value = json.dumps({"scene_description": "A person lifts a bottle.",
                                                   "persons": [{"track_id": 1, "description": "pickup", "events": [event()]}]})
        reid, gallery = Mock(), Mock()
        gallery.assign.return_value = ["person-one"]
        frames = [Image.new("RGB", (64, 64), color) for color in ("white", "red", "blue")]
        result = analyze_sample(detector, models, frames, self.sample, self.store, Mock(), reid, gallery)
        self.assertTrue(result["scene_ok"])
        record = result["activities"][0]
        self.assertEqual(result["behaviors"][0]["person_id"], "person-one")
        self.assertEqual(record["attributed_person_id"], "person-one")
        self.assertEqual(record["possession_status"], "observed_with_person")
        self.assertEqual(record["action"], "pick_up")
        self.assertEqual(record["activity_model_revision"], "fixture-revision")

    def test_event_array_format_is_validated(self):
        result = parse_activity(json.dumps([event("hold")]), 3)
        self.assertEqual(result["events"][0]["action"], "hold")
        self.assertTrue(result["description"])
