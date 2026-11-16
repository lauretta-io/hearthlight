"""Link person detections between consecutive frames of a single sample."""

from math import ceil, floor


def overlap(left, right):
    x1 = max(left[0], right[0])
    y1 = max(left[1], right[1])
    x2 = min(left[2], right[2])
    y2 = min(left[3], right[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    if not intersection:
        return 0
    left_area = (left[2] - left[0]) * (left[3] - left[1])
    right_area = (right[2] - right[0]) * (right[3] - right[1])
    return intersection / (left_area + right_area - intersection)


def link_detections(frames, threshold=0.3):
    tracks = []
    active = {}
    for frame_index, boxes in enumerate(frames):
        candidates = {
            detection: [track for track, previous in active.items() if overlap(box, previous) >= threshold]
            for detection, box in enumerate(boxes)
        }
        next_active = {}
        for detection, box in enumerate(boxes):
            matches = candidates[detection]
            if len(matches) == 1 and sum(matches[0] in others for others in candidates.values()) == 1:
                track = matches[0]
            else:
                track = len(tracks)
                tracks.append([])
            tracks[track].append((frame_index, box))
            next_active[track] = box
        active = next_active
    return tracks


class PersonDetector:
    def __init__(self, device, weights):
        from ultralytics import YOLO

        self.model = YOLO(str(weights))
        self.device = device

    def detect(self, images):
        results = self.model.predict(images, classes=[0], conf=0.35, device=self.device, verbose=False)
        return [
            [
                (floor(x1), floor(y1), ceil(x2), ceil(y2))
                for x1, y1, x2, y2 in result.boxes.xyxy.cpu().tolist()
            ]
            for result in results
        ]
