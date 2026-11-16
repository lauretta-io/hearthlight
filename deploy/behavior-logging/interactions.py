"""Validated interactions and persistent, evidence-backed person state."""

import json
from object_semantics import is_fixed_fixture
import re
from uuid import NAMESPACE_URL, uuid5

OBJECT_INTERACTIONS = {"touch", "use", "open", "close", "move", "unclear"}
PERSON_INTERACTIONS = {"talk", "gesture", "approach", "follow", "physical_contact",
                       "give", "receive", "help", "unclear"}
TAKEN = {"pick_up", "receive", "take_out_of_bag"}


def parse_interactions(value, track_id, catalog, frames):
    if not isinstance(value, list) or len(value) > 8:
        raise ValueError("invalid_interactions")
    result = []
    for interaction in value:
        if not isinstance(interaction, dict):
            raise ValueError("invalid_interaction")
        kind, action = interaction.get("target_kind"), interaction.get("interaction_type")
        if kind not in {"object", "person"} or action not in (
                OBJECT_INTERACTIONS if kind == "object" else PERSON_INTERACTIONS):
            raise ValueError("invalid_interaction_type")
        if interaction.get("actor") not in {"target", "unclear"} or interaction.get("certainty") not in {"clear", "unclear"}:
            raise ValueError("invalid_interaction_attribution")
        required = ("evidence", "item", "appearance") if kind == "object" else ("evidence",)
        for name in required:
            if not isinstance(interaction.get(name), str) or not interaction[name].strip() or len(interaction[name]) > 500:
                raise ValueError("invalid_interaction_description")
        start, end = interaction.get("start_frame"), interaction.get("end_frame")
        if type(start) is not int or type(end) is not int or not 0 <= start <= end < len(frames):
            raise ValueError("invalid_interaction_frames")
        if action in {"give", "receive", "open", "close", "move"} and (
                start == end or frames[start].tobytes() == frames[end].tobytes()):
            raise ValueError("interaction_transition_requires_distinct_evidence")
        participants = [track_id]
        other = interaction.get("target_track_id")
        if kind == "person":
            if type(other) is not int or other not in catalog or other == track_id:
                raise ValueError("invalid_interaction_target")
            subject_id, target_id = catalog[track_id]["person_id"], catalog[other]["person_id"]
            if subject_id is not None and subject_id == target_id:
                raise ValueError("interaction_with_same_identity")
            participants.append(other)
        for participant in participants:
            indices = {d["frame_index"] for d in catalog[participant]["detections"]}
            if start not in indices or end not in indices:
                raise ValueError("interaction_outside_participant_track")
        # Copy only validated fields. Model-supplied person IDs are never trusted.
        result.append({name: interaction[name] for name in (
            "target_kind", "interaction_type", "actor", "certainty", "evidence", "start_frame", "end_frame",
            *( ("item", "appearance") if kind == "object" else ("target_track_id",) ))})
    return sorted(result, key=lambda event: (event["end_frame"], event["start_frame"]))


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS person_interactions (
            event_id TEXT PRIMARY KEY, person_id TEXT, target_kind TEXT NOT NULL,
            target_key TEXT NOT NULL, target_person_id TEXT, interaction_type TEXT NOT NULL,
            item TEXT, appearance TEXT, evidence TEXT NOT NULL, actor TEXT NOT NULL,
            certainty TEXT NOT NULL, scene_id TEXT NOT NULL, behavior_id TEXT,
            camera_id TEXT NOT NULL, observed_at TEXT NOT NULL, start_frame INTEGER NOT NULL,
            end_frame INTEGER NOT NULL, possession_status TEXT, payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS interaction_subject_time ON person_interactions(person_id, observed_at);
        CREATE INDEX IF NOT EXISTS interaction_target_time ON person_interactions(target_person_id, observed_at);
        CREATE VIEW IF NOT EXISTS person_state_evidence AS
          SELECT *, 'outgoing' AS direction FROM person_interactions
            WHERE person_id IS NOT NULL AND actor='target' AND certainty='clear' AND interaction_type!='unclear'
          UNION ALL
          SELECT event_id, target_person_id, target_kind, person_id, person_id, interaction_type,
            item, appearance, evidence, actor, certainty, scene_id, behavior_id, camera_id,
            observed_at, start_frame, end_frame, possession_status, payload, 'incoming'
          FROM person_interactions WHERE target_kind='person' AND target_person_id IS NOT NULL
            AND person_id IS NOT NULL AND actor='target' AND certainty='clear' AND interaction_type!='unclear';
        CREATE TABLE IF NOT EXISTS person_state_migrations (version INTEGER PRIMARY KEY);
    """)
    with db:
        if not db.execute("SELECT 1 FROM person_state_migrations WHERE version=1").fetchone():
            # Preserve pre-upgrade item evidence; do not invent historical social interactions.
            for (payload,) in db.execute("SELECT payload FROM activities"):
                row = json.loads(payload)
                if row.get("action") and row.get("item") and row.get("event_id"):
                    record(db, row, row, row["event_id"], possession=row.get("possession_status"))
            db.execute("INSERT INTO person_state_migrations VALUES (1)")


def record(db, sample, interaction, event_id, person_id=None, target_person_id=None, possession=None):
    person_id = person_id if person_id is not None else sample.get("person_id")
    kind = interaction.get("target_kind", "object")
    if kind == "object":
        key = re.sub(r"\s+", " ", f"{interaction['item']}|{interaction['appearance']}".lower().strip())
    else:
        key = target_person_id or f"unresolved:{event_id}"
    action = interaction.get("interaction_type", interaction.get("action"))
    row = {**interaction, "interaction_id": event_id, "person_id": person_id,
           "target_person_id": target_person_id, "target_kind": kind,
           "interaction_type": action, "camera_id": sample["camera_id"],
           "scene_id": sample.get("scene_id", sample.get("sample_id")),
           "behavior_id": sample.get("behavior_id"), "sampled_at": sample["sampled_at"],
           "track_id": sample.get("track_id"), "sample_started_at": sample.get("sample_started_at"),
           "sample_fps": sample.get("sample_fps"), "activity_model": sample.get("activity_model"),
           "activity_model_revision": sample.get("activity_model_revision"),
           "attributed_person_id": person_id if interaction["actor"] == "target" and interaction["certainty"] == "clear" else None,
           "possession_status": possession, "moment": sample.get("moment"),
           "reference_scope": "person_and_description" if kind == "object" else "trusted_person_identity"}
    db.execute("INSERT OR IGNORE INTO person_interactions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        event_id, person_id, kind, key, target_person_id, action, interaction.get("item"),
        interaction.get("appearance"), interaction["evidence"], interaction["actor"], interaction["certainty"],
        row["scene_id"], row["behavior_id"], row["camera_id"], row["sampled_at"],
        interaction["start_frame"], interaction["end_frame"], possession, json.dumps(row)))
    return row


def record_report(db, sample, track, report, catalog):
    rows = []
    for index, interaction in enumerate(report.get("interactions", [])):
        other = catalog.get(interaction.get("target_track_id"), {})
        event_id = uuid5(NAMESPACE_URL, f"interaction:{sample['sample_id']}:{track['track_id']}:{index}").hex
        rows.append(record(db, {**sample, "track_id": track["track_id"]}, interaction, event_id,
                           track["person_id"], other.get("person_id")))
    return rows


# Filter BEFORE ranking: inaccessible cameras must never influence returned state.
STATE_SQL = """
WITH filtered AS (SELECT *, CASE
  WHEN interaction_type IN ('pick_up','hold','carry','receive','take_out_of_bag') THEN 'observed_with_person'
  WHEN interaction_type='put_in_bag' THEN 'observed_in_bag'
  WHEN interaction_type IN ('put_down','give') THEN 'observed_released'
  ELSE possession_status END AS effective_possession_status
  FROM person_state_evidence WHERE person_id IN ({person_placeholders}) {camera_filter}),
ranked AS (SELECT *,
  ROW_NUMBER() OVER (PARTITION BY target_kind,target_key,
    CASE WHEN target_kind='person' THEN interaction_type || ':' || direction ELSE '' END
    ORDER BY observed_at DESC,end_frame DESC,event_id DESC) AS rank,
  MIN(observed_at) OVER (PARTITION BY target_kind,target_key) AS first_observed_at,
  COUNT(*) OVER (PARTITION BY target_kind,target_key) AS observation_count,
  MAX(CASE WHEN target_kind='object' AND interaction_type IN ('pick_up','receive')
    THEN observed_at END) OVER (PARTITION BY target_kind,target_key) AS last_taken_at
  FROM filtered)
SELECT r.*,
 (SELECT p.interaction_type FROM filtered p WHERE r.target_kind='object' AND p.target_kind='object'
    AND p.target_key=r.target_key AND p.interaction_type IN ('pick_up','receive')
    ORDER BY p.observed_at DESC,p.end_frame DESC,p.event_id DESC LIMIT 1) AS last_acquisition_type,
 (SELECT p.effective_possession_status FROM filtered p WHERE r.target_kind='object' AND p.target_kind='object'
    AND p.target_key=r.target_key AND p.effective_possession_status IS NOT NULL AND p.effective_possession_status!='unclear'
    ORDER BY p.observed_at DESC,p.end_frame DESC,p.event_id DESC LIMIT 1) AS last_possession_status,
 (SELECT p.observed_at FROM filtered p WHERE r.target_kind='object' AND p.target_kind='object'
    AND p.target_key=r.target_key AND p.effective_possession_status IS NOT NULL AND p.effective_possession_status!='unclear'
    ORDER BY p.observed_at DESC,p.end_frame DESC,p.event_id DESC LIMIT 1) AS possession_observed_at
FROM ranked r WHERE rank=1 ORDER BY observed_at DESC,event_id DESC LIMIT ? OFFSET ?
"""


def read_state(db, person_id, camera_ids=None, limit=20, offset=0):
    persons=person_id if isinstance(person_id,list) else [person_id]
    clause = "" if camera_ids is None else "AND camera_id IN (" + ",".join("?" for _ in camera_ids) + ")"
    cursor = db.execute(STATE_SQL.format(camera_filter=clause,person_placeholders=",".join("?" for _ in persons)),
                        [*persons, *(camera_ids or []), limit, offset])
    columns = [c[0] for c in cursor.description]
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    for row in rows:
        if is_fixed_fixture(row.get('item')):
            row['last_possession_status'] = 'not_applicable'
            row['last_taken_at'] = None
            if row['interaction_type'] in {'hold', 'carry'}:
                row['interaction_type'] = 'touch'
    return rows


def prior_context(db, person_id, limit=100):
    rows = read_state(db, person_id, limit=limit)
    return [{"reference_key":r["target_key"] if r["target_kind"]=="object" else None,"target_kind": r["target_kind"], "item": r["item"], "appearance": r["appearance"],
             "target_person_id": r["target_person_id"], "interaction_type": r["interaction_type"],
             "direction": r["direction"], "last_observed_at": r["possession_observed_at"] or r["observed_at"],
             "last_acquisition_type": r["last_acquisition_type"],
             "last_observed_possession": r["last_possession_status"]} for r in rows]
