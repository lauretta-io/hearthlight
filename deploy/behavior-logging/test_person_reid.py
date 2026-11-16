from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

from person_reid import PersonGallery
from rerank import reciprocal_distances


class GalleryTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "gallery.sqlite3"
        self.gallery = self.open_gallery()
        self.left = np.array([1, 0], dtype=np.float32)
        self.right = np.array([0, 1], dtype=np.float32)

    def open_gallery(self):
        gallery = PersonGallery(self.path, "test-model")
        self.addCleanup(gallery.db.close)
        return gallery

    def test_births_and_tracking_outbox_survive_restarts_and_gallery_expiry(self):
        with patch("person_reid.time", return_value=1000):
            person_id, = self.gallery.assign([self.left], observed_at=990)
        sample = {"sample_id": "sample", "sample_started_at": "2026-11-11T00:00:00+00:00",
                  "sampled_at": "2026-11-11T00:00:01+00:00", "sample_fps": 2}
        tracks = [[(0, (1, 2, 3, 4)), (1, (1, 2, 3, 4))]]
        self.gallery.record_tracks(sample, tracks, [person_id])
        self.open_gallery().record_tracks(sample, tracks, [person_id])
        self.assertEqual(self.gallery.db.execute("SELECT COUNT(*) FROM track_observations").fetchone(), (1,))
        self.assertEqual(self.gallery.db.execute("SELECT created_at FROM identity_births WHERE person_id=?", (person_id,)).fetchone(), (990,))
        with patch("person_reid.time", return_value=1000 + 86401):
            self.gallery.assign([self.right])
        self.assertEqual(self.gallery.db.execute("SELECT COUNT(*) FROM people WHERE person_id=?", (person_id,)).fetchone(), (0,))
        self.assertEqual(self.open_gallery().db.execute("SELECT COUNT(*) FROM identity_births WHERE person_id=?", (person_id,)).fetchone(), (1,))

    def test_reuses_distinct_ids_after_restart(self):
        left_id, right_id = self.gallery.assign([self.left, self.right])
        self.assertNotEqual(left_id, right_id)
        self.assertEqual(self.open_gallery().assign([self.right, self.left]), [right_id, left_id])

    def test_abstains_when_two_tracks_claim_the_same_id(self):
        self.gallery.assign([self.left])
        self.assertEqual(self.gallery.assign([self.left, self.left, None]), [None, None, None])

    def test_abstains_when_two_gallery_entries_tie(self):
        self.gallery.assign([self.left, self.left])
        self.assertEqual(self.gallery.assign([self.left]), [None])

    def test_expires_id_after_inactivity(self):
        with patch("person_reid.time", return_value=1000):
            original, = self.gallery.assign([self.left])
        with patch("person_reid.time", return_value=1000 + 86401):
            renewed, = self.gallery.assign([self.left])
        self.assertNotEqual(original, renewed)

    def test_reranking_can_promote_a_close_candidate(self):
        left = np.array([0.9, np.sqrt(1 - 0.9**2)], dtype=np.float32)
        right = np.array([0.88, -np.sqrt(1 - 0.88**2)], dtype=np.float32)
        left_id, right_id = self.gallery.assign([left, right])

        def prefer_right(embeddings, query_count):
            self.assertEqual(query_count, 1)
            return np.array([[0.1 if vector @ right > vector @ left else 0.4
                              for vector in embeddings[query_count:]]])

        with patch("person_reid.reciprocal_distances", side_effect=prefer_right) as rerank:
            self.assertEqual(self.open_gallery().assign([self.left]), [right_id])
        rerank.assert_called_once()
        self.assertNotEqual(left_id, right_id)

    def test_recent_history_is_bounded_and_expires_before_the_ids(self):
        gallery = PersonGallery(self.path, "test-model", window_seconds=10, window_size=2)
        self.addCleanup(gallery.db.close)
        with patch("person_reid.time", return_value=1000):
            left_id, _ = gallery.assign([self.left, self.right])
            gallery.assign([self.left])
        self.assertEqual(gallery.db.execute("SELECT COUNT(*) FROM recent_observations").fetchone(), (2,))
        with patch("person_reid.time", return_value=1011):
            self.assertEqual(gallery.assign([self.left]), [left_id])
        self.assertEqual(gallery.db.execute("SELECT COUNT(*) FROM recent_observations").fetchone(), (1,))

    def test_reciprocal_neighbors_favor_the_local_cluster(self):
        embeddings = np.array([[1, 0], [1, 0], [0.995, 0.1], [0, 1], [0.1, 0.995]], dtype=np.float32)
        scores = reciprocal_distances(embeddings, query_count=1)
        self.assertEqual(scores.shape, (1, 4))
        self.assertTrue(np.isfinite(scores).all())
        self.assertLess(scores[0, :2].min(), scores[0, 2:].min())

    def test_persistent_prototypes_keep_a_match_after_recent_window_expires(self):
        left = np.array([0.9, np.sqrt(1 - 0.9**2)], dtype=np.float32)
        right = np.array([0.88, -np.sqrt(1 - 0.88**2)], dtype=np.float32)
        with patch("person_reid.time", return_value=1000):
            left_id, right_id = self.gallery.assign([left, right])
            for _ in range(3):
                self.assertEqual(self.gallery.assign([right]), [right_id])
            self.assertEqual(self.gallery.assign([self.left]), [left_id])
        with patch("person_reid.time", return_value=1301):
            self.assertEqual(self.gallery.assign([self.left]), [left_id])
