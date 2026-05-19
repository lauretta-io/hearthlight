import importlib.util
import sys
import types
import unittest
from pathlib import Path

import numpy as np

repo_root = Path(__file__).resolve().parents[1]
package = types.ModuleType("hearthlight_repo")
package.__path__ = [str(repo_root)]
sys.modules.setdefault("hearthlight_repo", package)

ingestor_package = types.ModuleType("hearthlight_repo.ingestor")
ingestor_package.__path__ = [str(repo_root / "ingestor")]
sys.modules.setdefault("hearthlight_repo.ingestor", ingestor_package)

models_package = types.ModuleType("hearthlight_repo.ingestor.models")
models_package.__path__ = [str(repo_root / "ingestor" / "models")]
sys.modules.setdefault("hearthlight_repo.ingestor.models", models_package)

detector_spec = importlib.util.spec_from_file_location(
    "hearthlight_repo.ingestor.models.detector",
    repo_root / "ingestor" / "models" / "detector.py",
)
detector_module = importlib.util.module_from_spec(detector_spec)
sys.modules[detector_spec.name] = detector_module
detector_spec.loader.exec_module(detector_module)


class DetectorFallbackTests(unittest.TestCase):
    def test_numpy_nms_keeps_highest_scoring_overlapping_box(self):
        boxes = np.asarray(
            [
                [10, 10, 110, 110],
                [12, 12, 108, 108],
                [200, 200, 260, 260],
            ],
            dtype=np.float32,
        )
        scores = np.asarray([0.8, 0.95, 0.7], dtype=np.float32)

        keep = detector_module._nms_numpy(boxes, scores, iou_threshold=0.5)

        self.assertEqual(keep.tolist(), [1, 2])

    def test_filter_yolo_prediction_maps_coco_classes_to_hearthlight_classes(self):
        person_row = np.zeros(84, dtype=np.float32)
        person_row[:4] = [320, 320, 100, 200]
        person_row[4] = 0.9
        bag_row = np.zeros(84, dtype=np.float32)
        bag_row[:4] = [160, 160, 80, 80]
        bag_row[4 + 24] = 0.75
        low_confidence_row = np.zeros(84, dtype=np.float32)
        low_confidence_row[:4] = [500, 500, 100, 100]
        low_confidence_row[4] = 0.1
        prediction = np.stack([person_row, bag_row, low_confidence_row], axis=0)

        detections = detector_module._filter_yolo_prediction_rows(
            prediction,
            frame_shape=(480, 640, 3),
            model_size=640,
            person_threshold=0.35,
            bag_threshold=0.35,
        )

        self.assertEqual(detections.shape, (2, 6))
        self.assertEqual(set(detections[:, 5].astype(int).tolist()), {0, 1})
        self.assertTrue(np.all(detections[:, :4] >= 0))
        self.assertTrue(np.all(detections[:, 2] <= 640))
        self.assertTrue(np.all(detections[:, 3] <= 480))


if __name__ == "__main__":
    unittest.main()
