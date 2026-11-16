"""Structured VLM observations and person-associated item histories."""

from datetime import datetime, timezone
import json
import re
import sqlite3
from uuid import NAMESPACE_URL, uuid5

import interactions
import moments
from zone_explanations import zone_explanation

ACTIVITY_PROMPT = '''Examine only the person inside the red box in these ordered camera frames.
Other people may overlap the box. Report visible item handling by the boxed person.
For a stationary person holding something, use hold. Use pick_up only when a visible
item moves from a table or shelf into their hands across different frames.
A pickup requires a visible change from resting on a surface to held in the hand.
Holding an item alone does not establish a pickup. Do not infer ownership, contents
of bags, intent, theft, or actions between sampled frames.
Return exactly one JSON object with keys "description" (string) and "events" (list). Use an empty events list
when item handling is absent or cannot be seen. Each event must have these fields:
- action: one of pick_up, hold, carry, put_down, put_in_bag, take_out_of_bag, give, receive, unclear
- item: the kind of visible item
- appearance: its visible color and distinguishing features
- start_frame and end_frame: integer frame numbers starting at 0
- actor: the exact string "target" if the boxed person handles the item, otherwise "unclear"
- certainty: the exact string "clear" or "unclear"
- evidence: a short description of the visible support for this action
Transitions require distinct start and end frames. Use actor unclear and certainty
unclear if several people prevent attribution. Do not include Markdown.'''

ACTIONS = {
    "pick_up": "observed_with_person",
    "hold": "observed_with_person",
    "carry": "observed_with_person",
    "put_down": "observed_released",
    "put_in_bag": "observed_in_bag",
    "take_out_of_bag": "observed_with_person",
    "give": "observed_released",
    "receive": "observed_with_person",
    "unclear": "unclear",
}
TRANSITIONS = set(ACTIONS) - {"hold", "carry", "unclear"}


def activity_images(frames, track):
    from PIL import ImageDraw

    images = []
    for index, box in track:
        frame = frames[index]
        x1, y1, x2, y2 = box
        pad_x, pad_y = int((x2 - x1) * 0.35), int((y2 - y1) * 0.2)
        left, top = max(0, x1 - pad_x), max(0, y1 - pad_y)
        right, bottom = min(frame.width, x2 + pad_x), min(frame.height, y2 + pad_y)
        image = frame.crop((left, top, right, bottom))
        ImageDraw.Draw(image).rectangle((x1 - left, y1 - top, x2 - left, y2 - top), outline="red", width=3)
        images.append(image)
    return images


def parse_activity(raw, frame_count, frames=None):
    text = raw.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    payload = json.loads(text)
    if isinstance(payload, list):
        payload = {"description": "", "events": payload}
    if not isinstance(payload, dict) or not isinstance(payload.get("description"), str):
        raise ValueError("activity_description_missing")
    events = payload.get("events")
    if not isinstance(events, list) or len(events) > 8:
        raise ValueError("invalid_activity_events")
    validated = []
    for event in events:
        if not isinstance(event, dict) or event.get("action") not in ACTIONS:
            raise ValueError("invalid_activity_action")
        if event.get("actor") not in {"target", "unclear"} or event.get("certainty") not in {"clear", "unclear"}:
            raise ValueError("invalid_activity_attribution")
        for name in ("item", "appearance", "evidence"):
            if not isinstance(event.get(name), str) or not event[name].strip() or len(event[name]) > 500:
                raise ValueError("invalid_activity_item")
        start, end = event.get("start_frame"), event.get("end_frame")
        if type(start) is not int or type(end) is not int or not 0 <= start <= end < frame_count:
            raise ValueError("invalid_activity_frames")
        if event["action"] in TRANSITIONS:
            if start == end:
                raise ValueError("activity_transition_requires_two_frames")
            if frames is not None and frames[start].tobytes() == frames[end].tobytes():
                raise ValueError("activity_transition_on_identical_frames")
        validated.append({name: event[name] for name in (
            "action", "item", "appearance", "start_frame", "end_frame", "actor", "certainty", "evidence"
        )})
    description = payload["description"] or " ".join(event["evidence"] for event in validated)
    return {"description": description[:2000],
            "events": sorted(validated, key=lambda event: (event["end_frame"], event["start_frame"]))}


class ActivityStore:
    def __init__(self, path):
        self.path = path
        path.touch(mode=0o600, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA foreign_keys = ON")
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS activities (
                event_id TEXT PRIMARY KEY, sample_id TEXT NOT NULL, track_id INTEGER NOT NULL,
                person_id TEXT, camera_id TEXT NOT NULL, observed_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )""")
            self.db.execute("CREATE INDEX IF NOT EXISTS activities_person ON activities(person_id, observed_at)")
            self.db.execute("""CREATE TABLE IF NOT EXISTS person_items (
                item_id TEXT PRIMARY KEY, person_id TEXT NOT NULL, item TEXT NOT NULL,
                appearance TEXT NOT NULL, last_observed_state TEXT NOT NULL,
                last_observed_at TEXT NOT NULL, camera_id TEXT NOT NULL,
                event_id TEXT NOT NULL, last_checked_at TEXT NOT NULL,
                visibility TEXT NOT NULL
            )""")

        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS persons (
                person_id TEXT PRIMARY KEY, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scene_descriptions (
                scene_id TEXT PRIMARY KEY, camera_id TEXT NOT NULL, camera_name TEXT,
                observed_at TEXT NOT NULL, description TEXT, analysis_status TEXT NOT NULL,
                model_id TEXT NOT NULL, model_revision TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS scene_camera_time ON scene_descriptions(camera_id, observed_at);
            CREATE TABLE IF NOT EXISTS scene_persons (
                scene_id TEXT NOT NULL REFERENCES scene_descriptions(scene_id),
                track_id INTEGER NOT NULL, person_id TEXT REFERENCES persons(person_id),
                detections_json TEXT NOT NULL, PRIMARY KEY(scene_id, track_id)
            );
            CREATE INDEX IF NOT EXISTS scene_person_identity ON scene_persons(person_id, scene_id);
            CREATE TABLE IF NOT EXISTS person_behaviors (
                behavior_id TEXT PRIMARY KEY, scene_id TEXT NOT NULL, track_id INTEGER NOT NULL,
                person_id TEXT REFERENCES persons(person_id), observed_at TEXT NOT NULL,
                description TEXT, analysis_status TEXT NOT NULL, payload TEXT NOT NULL,
                UNIQUE(scene_id, track_id),
                FOREIGN KEY(scene_id, track_id) REFERENCES scene_persons(scene_id, track_id)
            );
            CREATE INDEX IF NOT EXISTS behavior_person_time ON person_behaviors(person_id, observed_at);
            CREATE VIEW IF NOT EXISTS person_scene_history AS
                SELECT p.person_id, p.track_id, s.scene_id, s.camera_id, s.camera_name,
                       s.observed_at, s.description AS scene_description, s.analysis_status
                FROM scene_persons p JOIN scene_descriptions s ON p.scene_id=s.scene_id;
            CREATE VIEW IF NOT EXISTS person_behavior_history AS
                SELECT b.person_id, b.track_id, b.behavior_id, b.scene_id,
                       s.camera_id, s.camera_name, b.observed_at,
                       b.description AS behavior_description, s.description AS scene_description,
                       b.analysis_status, b.payload
                FROM person_behaviors b JOIN scene_descriptions s ON b.scene_id=s.scene_id;
        """)
        interactions.initialize(self.db)
        moments.initialize(self.db)

    def prior_state(self, person_id, aliases=None):
        return interactions.prior_context(self.db, aliases or person_id)

    def record(self, sample, track_id, person_id, track, activity):
        with self.db:
            return self._record(sample, track_id, person_id, track, activity)

    def _record(self, sample, track_id, person_id, track, activity):
        now = datetime.now(timezone.utc).isoformat()
        observed_at = sample["sampled_at"]
        rows = []
        if person_id is not None:
            self.db.execute("""UPDATE person_items SET visibility='unobserved', last_checked_at=?
                WHERE person_id=? AND last_checked_at < ?""", (observed_at, person_id, observed_at))
        for index, event in enumerate(activity["events"]):
            event_id = uuid5(NAMESPACE_URL, f"{sample['sample_id']}:{track_id}:{index}").hex
            attributed = person_id is not None and event["actor"] == "target" and event["certainty"] == "clear"
            state = ACTIONS[event["action"]] if attributed else "unclear"
            item_id = None
            if state != "unclear":
                # This key groups descriptions for one person. It cannot establish
                # that two matching descriptions refer to a unique physical object.
                descriptor = re.sub(r"\s+", " ", f"{event['item']}|{event['appearance']}".lower().strip())
                item_id = uuid5(NAMESPACE_URL, f"{person_id}:{descriptor}").hex
            row = {
                "timestamp": now, **sample, "event_id": event_id,
                "track_id": track_id, "person_id": person_id, "item_id": item_id,
                "attributed_person_id": person_id if attributed else None,
                "item_reference_scope": "person_and_description",
                "assessment": "vlm_observation", "possession_status": state, **event,
                "start_frame": track[event["start_frame"]][0],
                "end_frame": track[event["end_frame"]][0],
                "start_offset_seconds": track[event["start_frame"]][0] / sample.get("sample_fps", 1),
                "end_offset_seconds": track[event["end_frame"]][0] / sample.get("sample_fps", 1),
            }
            inserted = self.db.execute("INSERT OR IGNORE INTO activities VALUES (?, ?, ?, ?, ?, ?, ?)", (
                event_id, sample["sample_id"], track_id, person_id, sample["camera_id"],
                observed_at, json.dumps(row),
            )).rowcount
            if not inserted:
                continue
            if item_id is not None:
                self.db.execute("""INSERT INTO person_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'observed')
                    ON CONFLICT(item_id) DO UPDATE SET
                        last_observed_state=excluded.last_observed_state,
                        last_observed_at=excluded.last_observed_at, camera_id=excluded.camera_id,
                        event_id=excluded.event_id, last_checked_at=excluded.last_checked_at,
                        visibility=excluded.visibility
                    WHERE excluded.last_observed_at >= person_items.last_observed_at
                """, (item_id, person_id, event["item"], event["appearance"], state,
                      observed_at, sample["camera_id"], event_id, observed_at))
            interactions.record(self.db, row, row, event_id, possession=state)
            rows.append(row)
        return rows

    def record_analysis(self, sample, request, analysis, raw_output, status, error_code=None,
                        visual_matches=None):
        """Commit the scene, actor links, behaviors, and item events together."""
        scene_id = sample["sample_id"]
        observed_at = sample["sampled_at"]
        scene = {
            "timestamp": datetime.now(timezone.utc).isoformat(), **sample,
            "scene_id": scene_id, "description": analysis["scene_description"] if analysis else None,
            "analysis_status": status, "error_code": error_code,
            "input_request": request, "zone_reports": request.get("zone_reports", []),
            "zone_explanation": zone_explanation(request.get("zone_reports", [])), "raw_model_output": raw_output,
            "visual_matches": visual_matches or [],
        }
        reports = {report["track_id"]: report for report in analysis["persons"]} if analysis else {}
        catalog = {track["track_id"]: track for track in request["tracks"]}
        behaviors, activities = [], []
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            previous = self.db.execute("SELECT payload FROM scene_descriptions WHERE scene_id=?", (scene_id,)).fetchone()
            if previous:
                return {"inserted": False, "scene": json.loads(previous[0]), "behaviors": [], "activities": []}
            self.db.execute("INSERT INTO scene_descriptions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                scene_id, sample["camera_id"], sample.get("camera_name"), observed_at,
                scene["description"], status, sample["activity_model"],
                sample["activity_model_revision"], json.dumps(scene),
            ))
            for track in request["tracks"]:
                track_id, person_id = track["track_id"], track["person_id"]
                if person_id is not None:
                    self.db.execute("""INSERT INTO persons VALUES (?, ?, ?)
                        ON CONFLICT(person_id) DO UPDATE SET
                            first_seen=MIN(persons.first_seen,excluded.first_seen),
                            last_seen=MAX(persons.last_seen,excluded.last_seen)
                    """, (person_id, observed_at, observed_at))
                self.db.execute("INSERT INTO scene_persons VALUES (?, ?, ?, ?)", (
                    scene_id, track_id, person_id, json.dumps(track["detections"]),
                ))
                report = reports.get(track_id, {
                    "description": None, "events": [], "analysis_status": status,
                    "error_code": error_code,
                })
                behavior_id = uuid5(NAMESPACE_URL, f"behavior:{scene_id}:{track_id}").hex
                behavior = {
                    "timestamp": scene["timestamp"], **sample, "scene_id": scene_id,
                    "behavior_id": behavior_id, "track_id": track_id, "person_id": person_id,
                    "description": report["description"], "events": report["events"],
                    "moment": report.get("moment"),
                    "object_refinement": report.get("object_refinement"),
                    "state_changes": report.get("state_changes", {}),
                    "analysis_status": report["analysis_status"], "error_code": report["error_code"],
                    "detections": track["detections"],
                    "snapshot_file": track.get("snapshot_file"),
                    "snapshot_frame": track.get("snapshot_frame"),
                    "exits": report.get("exits", []),
                }
                behavior["interactions"] = interactions.record_report(
                    self.db, {**sample, "behavior_id": behavior_id, "moment": report.get("moment")}, track, report, catalog
                ) if report.get("interactions") else []
                self.db.execute("INSERT INTO person_behaviors VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (
                    behavior_id, scene_id, track_id, person_id, observed_at,
                    behavior["description"], behavior["analysis_status"], json.dumps(behavior),
                ))
                if report["analysis_status"] == "analyzed" or report.get("events"):
                    indices = [detection["frame_index"] for detection in track["detections"]]
                    positions = {index: position for position, index in enumerate(indices)}
                    local_activity = {"description": report["description"], "events": [
                        {**event, "start_frame": positions[event["start_frame"]],
                         "end_frame": positions[event["end_frame"]]} for event in report["events"]
                    ]}
                    local_track = [(detection["frame_index"], detection["box_xyxy"])
                                   for detection in track["detections"]]
                    activities.extend(self._record({**sample, "scene_id": scene_id, "behavior_id": behavior_id, "moment": report.get("moment")},
                                                   track_id, person_id, local_track, local_activity))
                moments.commit(self.db, report.get("moment"))
                behaviors.append(behavior)
        return {"inserted": True, "scene": scene, "behaviors": behaviors, "activities": activities}
