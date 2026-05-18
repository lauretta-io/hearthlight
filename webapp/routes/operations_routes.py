import os
import shutil
import logging
import asyncio
import json
from typing import List
from datetime import datetime
import subprocess
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, Response
from sqlalchemy.orm import Session
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from ...shared.utils.image import encode_base64
from ...shared.database.database import get_db
from ...shared.database.database import SessionLocal
from ...shared.models import SQLModels
from ...shared.models.OperationsModels import (
    Location,
    IncidentUpdate,
    IncidentCard,
    Incident,
    EntityCard,
    JourneyNode,
    Entity,
    AssociatedEntity,
    AssociatedIncident,
    POIResultCard,
    POIResult,
)
from ...shared.constants import EntityType, IncidentStatus, IncidentType
from ...shared.utils.alert_rules import ensure_alert_rule_tables
from ...shared.rabbit_messenger import ResolutionPublisher
from ...shared.models.DataModels import ResolutionMessage
from ...shared.utils.security import is_valid_incident_status_transition
from ...shared.utils.time_utils import seconds_since_datetime

operations_router = APIRouter()
logger = logging.getLogger(__name__)
resolution_publisher = None
ENTITY_IMAGE_DIR = Path(os.environ.get("ENTITY_IMAGE_DIR", "shared/output/entity_images"))
INCIDENT_STREAM_POLL_INTERVAL = float(
    os.environ.get("OPERATIONS_INCIDENT_STREAM_POLL_INTERVAL", "1.0")
)


def get_resolution_publisher():
    global resolution_publisher
    if resolution_publisher is None:
        resolution_publisher = ResolutionPublisher()
    return resolution_publisher


def shutdown_operations_resources():
    global resolution_publisher
    if resolution_publisher is not None:
        resolution_publisher.close()
        resolution_publisher = None


def get_ffmpeg_binary():
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise HTTPException(status_code=503, detail="ffmpeg is not available")
    return ffmpeg_path


def resolve_camera_recording_path(path: str | None) -> str | None:
    if not path:
        return None
    app_root = Path(os.environ.get("HEARTHLIGHT_APP_ROOT", "/app"))
    candidates = [Path(path)]
    if path.startswith("src/shared/"):
        candidates.append(Path("shared") / path[len("src/shared/"):])
    for candidate in candidates:
        resolved = candidate if candidate.is_absolute() else app_root / candidate
        if resolved.exists():
            return str(resolved)
    return path


def require_existing_file(path: str | None, description: str):
    resolved_path = resolve_camera_recording_path(path)
    if not resolved_path or not os.path.exists(resolved_path):
        raise HTTPException(status_code=404, detail=f"{description} not found")


def clip_bbox_to_frame(bbox: list[int], width: int, height: int):
    left = max(0, min(width, bbox[0]))
    top = max(0, min(height, bbox[1]))
    right = max(0, min(width, bbox[2]))
    bottom = max(0, min(height, bbox[3]))
    if right <= left or bottom <= top:
        return None
    return [left, top, right, bottom]


def start_ffmpeg(command: list[str]):
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        logger.exception("Failed to start ffmpeg")
        raise HTTPException(status_code=503, detail="failed to start ffmpeg") from exc
    if process.stdout is None or process.stderr is None:
        process.kill()
        raise HTTPException(status_code=500, detail="failed to create ffmpeg pipes")
    return process


def iter_process_output(process: subprocess.Popen[bytes], chunk_size: int = 1024 * 1024):
    try:
        while True:
            chunk = process.stdout.read(chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()
        return_code = process.wait()
        if return_code:
            logger.warning("ffmpeg exited with return code %s", return_code)


@operations_router.get("/runs", response_model=List[str])
def get_run_identifiers(db: Session = Depends(get_db)):
    runs = db.query(SQLModels.Run).order_by(SQLModels.Run.created_at).all()
    return [run.run_identifier for run in runs]


@operations_router.get("/incidents", response_model=List[IncidentCard])
def incident_cards(run_identifier: str, include_crop: bool = False, db: Session = Depends(get_db)):
    run = db.query(SQLModels.Run).filter_by(run_identifier=run_identifier).first()
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    db_incidents = db.query(SQLModels.Incident).filter_by(run_id=run.id).order_by(SQLModels.Incident.created_at).all()
    if db_incidents is None:
        return []
    return [
        get_incident_card(db_incident, db, include_crop=include_crop)
        for db_incident in db_incidents
    ]


@operations_router.get("/incident_card", response_model=IncidentCard)
def incident_card(incident_id: str, db: Session = Depends(get_db)):
    db_indicent = get_db_indicent(incident_id, db)
    return get_incident_card(db_indicent, db)


@operations_router.get("/incident", response_model=Incident)
def incident(incident_id: str, db: Session = Depends(get_db)):
    db_indicent = get_db_indicent(incident_id, db)
    return get_incident(incident_id, db_indicent, db)

@operations_router.get("/entities", response_model=List[EntityCard])
def entity_cards(run_identifier: str, include_crop: bool = False, db: Session = Depends(get_db)):
    run = db.query(SQLModels.Run).filter_by(run_identifier=run_identifier).first()
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    db_persons = db.query(SQLModels.Person).filter_by(run_id=run.id, is_deleted=False).all()
    if db_persons is None:
        return []
    return [
        get_entity_card(db_person.id, EntityType.PERSON, db)
        for db_person in db_persons if db_person.id > 0
    ]

@operations_router.get("/entity_card", response_model=EntityCard)
def entity_card(entity_id: str, db: Session = Depends(get_db)):
    db_id, entity_type = parse_entity_id(entity_id)
    return get_entity_card(db_id, entity_type, db)


@operations_router.get("/entity", response_model=Entity)
def entity(entity_id: str, db: Session = Depends(get_db)):
    db_id, entity_type = parse_entity_id(entity_id)
    return get_entity(db_id, entity_type, db)


@operations_router.post("/update_incident", response_model=Incident)
def update_incident(update: IncidentUpdate, db: Session = Depends(get_db)):
    db_id = parse_incident_id(update.incident_id)
    db_incident = db.get(SQLModels.Incident, db_id)
    if db_incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    if update.old_status and update.old_status != db_incident.status:
        raise HTTPException(status_code=409, detail="incident status is stale")
    if not is_valid_incident_status_transition(db_incident.status, update.new_status):
        raise HTTPException(
            status_code=409,
            detail=f"invalid incident status transition from {db_incident.status} to {update.new_status}",
        )
    update_model = SQLModels.IncidentUpdate(
        incident_id=db_incident.id,
        run_id=db_incident.run_id,
        new_status=update.new_status,
        old_status=update.old_status if update.old_status else db_incident.status,
        updated_by=update.updated_by if update.updated_by else None,
    )
    try:
        db.add(update_model)
        db.commit()
        db.refresh(update_model)
        assert update_model is not None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail="failed to update incident")
    db_incident.status = update.new_status
    db_incident.current_update = update_model.id
    db_incident.updated_at = update_model.created_at
    db.commit()
    db.refresh(db_incident)
    message = ResolutionMessage(incident_id=db_id, status=update.new_status)
    try:
        get_resolution_publisher().publish_resolution(message)
    except Exception:
        logger.exception(
            "Failed to publish incident status message for incident %s", db_id
        )
    return get_incident(update.incident_id, db_incident, db)


def _build_run_signature(db: Session):
    rows = (
        db.query(SQLModels.Run.run_identifier, SQLModels.Run.created_at)
        .order_by(SQLModels.Run.created_at, SQLModels.Run.id)
        .all()
    )
    return [
        {
            "run_identifier": run_identifier,
            "created_at": created_at.isoformat() if created_at else None,
        }
        for run_identifier, created_at in rows
    ]


def _build_incident_signature(db: Session):
    rows = (
        db.query(
            SQLModels.Incident.id,
            SQLModels.Incident.run_id,
            SQLModels.Incident.status,
            SQLModels.Incident.updated_at,
            SQLModels.Incident.created_at,
        )
        .order_by(SQLModels.Incident.id)
        .all()
    )
    return [
        {
            "id": incident_id,
            "run_id": run_id,
            "status": status,
            "updated_at": (
                updated_at.isoformat()
                if updated_at
                else created_at.isoformat() if created_at else None
            ),
        }
        for incident_id, run_id, status, updated_at, created_at in rows
    ]


def _build_entity_signature(db: Session):
    rows = (
        db.query(
            SQLModels.Person.id,
            SQLModels.Person.run_id,
            SQLModels.Person.updated_at,
            SQLModels.Person.created_at,
        )
        .filter_by(is_deleted=False)
        .order_by(SQLModels.Person.id)
        .all()
    )
    return [
        {
            "id": entity_id,
            "run_id": run_id,
            "updated_at": (
                updated_at.isoformat()
                if updated_at
                else created_at.isoformat() if created_at else None
            ),
        }
        for entity_id, run_id, updated_at, created_at in rows
    ]


def _build_incident_stream_state():
    with SessionLocal() as db:
        return {
            "runs": _build_run_signature(db),
            "incidents": _build_incident_signature(db),
            "entities": _build_entity_signature(db),
        }


def _format_sse_event(event_name: str, payload: dict):
    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"


@operations_router.get("/events")
async def operations_events(request: Request):
    async def event_generator():
        previous_state = None

        while True:
            if await request.is_disconnected():
                break

            state = _build_incident_stream_state()
            if previous_state is None:
                previous_state = state
                yield _format_sse_event("snapshot", state)
            else:
                emitted_update = False
                if state["runs"] != previous_state["runs"]:
                    emitted_update = True
                    yield _format_sse_event(
                        "runs.updated",
                        {"run_identifiers": [run["run_identifier"] for run in state["runs"]]},
                    )
                if state["incidents"] != previous_state["incidents"]:
                    emitted_update = True
                    yield _format_sse_event(
                        "incidents.updated",
                        {
                            "run_ids": sorted(
                                {
                                    incident["run_id"]
                                    for incident in state["incidents"]
                                    if incident["run_id"] is not None
                                }
                            ),
                            "incident_ids": [
                                incident["id"] for incident in state["incidents"]
                            ],
                        },
                    )
                if state["entities"] != previous_state["entities"]:
                    emitted_update = True
                    yield _format_sse_event(
                        "entities.updated",
                        {
                            "run_ids": sorted(
                                {
                                    entity["run_id"]
                                    for entity in state["entities"]
                                    if entity["run_id"] is not None
                                }
                            ),
                            "entity_ids": [entity["id"] for entity in state["entities"]],
                        },
                    )
                if not emitted_update:
                    yield ": keepalive\n\n"
                previous_state = state

            await asyncio.sleep(INCIDENT_STREAM_POLL_INTERVAL)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@operations_router.get("/pois", response_model=List[POIResultCard])
def pois(db: Session = Depends(get_db)):
    last_run = db.query(SQLModels.Run).order_by(SQLModels.Run.created_at.desc()).first()
    if last_run is None:
        return []
    db_pois = db.query(SQLModels.POISearch).filter_by(run_id=last_run.id).all()
    if db_pois is None:
        return []
    return [get_poi_card(db_poi, db) for db_poi in db_pois]


@operations_router.get("/poi", response_model=POIResult)
def poi(poi_id: int, db: Session = Depends(get_db)):
    db_poi = db.query(SQLModels.POISearch).filter_by(id=poi_id).first()
    if db_poi is None:
        raise HTTPException(status_code=404, detail="poi not found")
    return get_poi_result(db_poi, db)


@operations_router.head("/incident_video/")
def get_video_headers(incident_id: str, db: Session = Depends(get_db)):
    get_db_indicent(incident_id, db)
    return Response(content=None, headers={"Content-Type": "video/mp4"})


@operations_router.get("/incident_video/")
def get_incident_video(
    incident_id: str, duration: int = 10, db: Session = Depends(get_db)
):
    if duration < 1 or duration > 120:
        raise HTTPException(status_code=400, detail="duration must be between 1 and 120 seconds")
    db_incident = get_db_indicent(incident_id, db)

    cam_id = db_incident.camera_id
    run_id = db_incident.run_id

    camera = get_db_camera(cam_id, run_id, db)
    recording_path = resolve_camera_recording_path(camera.cam_recording_path)
    require_existing_file(recording_path, "camera recording")

    incident_timestamp = db_incident.timestamp
    if incident_timestamp is None and db_incident.created_at is not None:
        incident_timestamp = db_incident.created_at.timestamp()
    if incident_timestamp is None:
        raise HTTPException(status_code=404, detail="incident timestamp not available")

    recording_start_time = camera.start_timestamp or 0.0
    start_time = max(incident_timestamp - duration / 2, recording_start_time)
    seek_seconds = start_time - recording_start_time

    # fmt: off
    command = [
        get_ffmpeg_binary(),
        "-i", recording_path,    # Input file
        "-ss", str(seek_seconds),           # Output seek — avoids HEVC keyframe/VPS errors
        "-t", str(duration),                # Duration of clip
        "-an",                              # No audio
        "-f", "mp4",                        # Output format
        "-c:v", "libx264",                  # Video codec
        "-preset", "ultrafast",             # Faster processing
        "-crf", "23",                       # Quality level (lower = better)
        "-movflags", "frag_keyframe+empty_moov",  # Streaming optimization
        "pipe:1"                            # Output to stdout
    ]
    # fmt: on

    process = start_ffmpeg(command)

    return StreamingResponse(
        iter_process_output(process),
        media_type="video/mp4",
    )


def get_db_camera(cam_id: int, run_id: int, db: Session):
    camera = (
        db.query(SQLModels.CameraRecording)
        .filter_by(cam_id=cam_id, run_id=run_id)
        .first()
    )
    if camera is None:
        raise HTTPException(status_code=404, detail="camera recording not found")
    return camera


def get_db_camera_for_anomaly(anomaly_event: SQLModels.AnomalyEvent, db: Session):
    query = db.query(SQLModels.CameraRecording).filter_by(
        run_id=anomaly_event.run_id,
        is_deleted=False,
    )
    if anomaly_event.source_template_id is not None:
        camera = query.filter_by(
            source_template_id=anomaly_event.source_template_id
        ).first()
        if camera is not None:
            return camera
    if anomaly_event.camera_id is not None:
        camera = query.filter_by(cam_id=anomaly_event.camera_id).first()
        if camera is not None:
            return camera
    raise HTTPException(status_code=404, detail="camera recording not found")


@operations_router.get("/anomaly_video/")
def get_anomaly_video(event_id: str, run_identifier: str, db: Session = Depends(get_db)):
    run = db.query(SQLModels.Run).filter_by(run_identifier=run_identifier).first()
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    anomaly_event = (
        db.query(SQLModels.AnomalyEvent)
        .filter_by(run_id=run.id, event_key=event_id, is_deleted=False)
        .first()
    )
    if anomaly_event is None:
        raise HTTPException(status_code=404, detail="anomaly event not found")

    clip_path = os.path.join(run.output_dir, "anomaly", f"{event_id}.mp4")
    require_existing_file(clip_path, "anomaly video")

    command = [
        get_ffmpeg_binary(),
        "-i", clip_path,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-an",
        "-movflags", "frag_keyframe+empty_moov",
        "-f", "mp4",
        "pipe:1",
    ]
    process = start_ffmpeg(command)
    return StreamingResponse(iter_process_output(process), media_type="video/mp4")


def resolve_entity_id(db_id: int, entity_type: str, db: Session) -> int:

    db_entity_type = "PERSON" if entity_type == EntityType.PERSON else "BAG"

    if db_id < 0:
        mapping = (
            db.query(SQLModels.EntityIdMapping)
            .filter_by(temporary_id=db_id, entity_type=db_entity_type)
            .first()
        )

        if mapping:
            return mapping.persistent_id

    model = get_entity_db_model(entity_type)
    if db.query(model.id).filter(model.id == db_id).first():
        return db_id

    raise HTTPException(
        status_code=404,
        detail=f"Entity of type {entity_type} with ID {db_id} not found.",
    )


def create_incident_id(incident: SQLModels.Incident):
    type_abbr = IncidentType.get_abbr(incident.incident_type)
    if type_abbr is None:
        raise HTTPException(status_code=400, detail="invalid incident type")
    date_string = incident.created_at.strftime("%Y%m%d")
    return f"{type_abbr}-{date_string}-{incident.id}"


def get_db_indicent(incident_id: str, db: Session):
    db_id = parse_incident_id(incident_id)
    incident = db.get(SQLModels.Incident, db_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return incident


def parse_incident_id(incident_id: str):
    id_parts = incident_id.split("-")
    if len(id_parts) != 3:
        raise HTTPException(status_code=400, detail="invalid incident ID format")
    if not id_parts[2].isdigit():
        raise HTTPException(status_code=400, detail="invalid incident ID format")
    return int(id_parts[2])


def get_alert_incident_row(incident_db_id: int, db: Session):
    ensure_alert_rule_tables()
    return (
        db.query(SQLModels.AlertIncident)
        .filter_by(incident_id=incident_db_id, is_deleted=False)
        .first()
    )


def get_incident_card(incident: SQLModels.Incident, db: Session, include_crop=True):
    alert_row = get_alert_incident_row(incident.id, db)
    if include_crop:
        model = SQLModels.IncidentPersonMapping
        person_mapping = db.query(model).filter_by(incident_id=incident.id).first()
        try:
            if person_mapping is None:
                crop = None
            else:
                last_node = get_last_journey_node(
                    person_mapping.person_id, EntityType.PERSON, db
                )
                crop = get_journey_crop(last_node, db)
            if incident.incident_type == IncidentType.UNATTENDED_BAG:
                model = SQLModels.IncidentBagMapping
                bag_mapping = db.query(model).filter_by(incident_id=incident.id).first()
                if bag_mapping is not None:
                    last_node = get_last_journey_node(
                        bag_mapping.bag_id, EntityType.BAG, db
                    )
                    crop = get_journey_crop(last_node, db)
        except Exception:
            crop = None
    else:
        crop = None
    return IncidentCard(
        incident_id=create_incident_id(incident),
        incident_type=incident.incident_type,
        display_title=alert_row.title if alert_row is not None else None,
        alert_level=alert_row.alert_level if alert_row is not None else None,
        metadata=(
            {
                "signal_family": alert_row.signal_family,
                "matched_target": alert_row.matched_target,
                "confidence": float(alert_row.confidence),
            }
            if alert_row is not None
            else None
        ),
        incident_time=incident.created_at.isoformat(),
        status=incident.status,
        location=Location(camera_id=incident.camera_id, zone_id=incident.zone_id),
        last_update_time=incident.updated_at.isoformat(),
        last_updated_by=incident.updated_by,
        crop=crop,
    )


def get_journey_node_ids(entity_id: int, entity_type: str, db: Session):
    entity_id = resolve_entity_id(entity_id, entity_type, db)
    model = get_entity_journey_db_model(entity_type)
    id_key = get_entity_db_id_key(entity_type)
    node_db_ids = (
        db.query(model.journey_node_id).filter_by(**{id_key: entity_id}).all()
    )
    node_db_ids = [node[0] for node in node_db_ids]
    return node_db_ids


def get_last_journey_node(
    entity_id: int, entity_type: str, db: Session
) -> SQLModels.JourneyNode:
    node_db_ids = get_journey_node_ids(entity_id, entity_type, db)
    latest_journey_node = (
        db.query(SQLModels.JourneyNode)
        .filter(SQLModels.JourneyNode.id.in_(node_db_ids))
        .order_by(SQLModels.JourneyNode.start_timestamp.desc())
        .first()
    )
    return latest_journey_node


def get_crop(path: str):
    if not os.path.exists(path):
        return None
    try:
        crop = cv2.imread(path)
    except Exception:
        logger.exception("Failed to read crop %s", path)
        return None
    if crop is None:
        return None
    return encode_base64(crop)


def get_entity_image_path(journey_node: SQLModels.JourneyNode) -> Path:
    return (
        ENTITY_IMAGE_DIR
        / f"run_{journey_node.run_id}"
        / f"camera_{journey_node.camera_id}"
        / f"{journey_node.id}.jpg"
    )


def get_journey_crop(journey_node: SQLModels.JourneyNode, db: Session):
    if journey_node is None:
        return None
    cache_path = get_entity_image_path(journey_node)
    if cache_path.exists():
        return get_crop(str(cache_path))

    cam_id = journey_node.camera_id
    run_id = journey_node.run_id

    camera = get_db_camera(cam_id, run_id, db)
    require_existing_file(camera.cam_recording_path, "camera recording")

    recording_start_time = camera.start_timestamp
    seek_seconds = max(0.0, journey_node.start_timestamp - recording_start_time)

    # fmt: off
    command = [
        get_ffmpeg_binary(),
        "-i", camera.cam_recording_path,    # Input file
        "-ss", str(seek_seconds),           # Output seek — decodes from keyframe, avoids HEVC VPS/PPS errors
        "-frames:v", "1",                  # Extract exactly 1 frame
        "-f", "rawvideo",                  # Output raw video (not JPEG)
        "-pix_fmt", "bgr24",               # BGR format for OpenCV
        "pipe:1",                          # Output to stdout
    ]
    # fmt: on

    process = start_ffmpeg(command)

    width = camera.width
    height = camera.height

    frame_size = width * height * 3

    raw_frame = process.stdout.read(frame_size)
    process.stdout.close()
    process.stderr.close()
    return_code = process.wait()
    if return_code != 0 or len(raw_frame) != frame_size:
        logger.warning("ffmpeg failed to extract frame for journey node %s", journey_node.id)
        return None

    try:
        frame = np.frombuffer(raw_frame, dtype=np.uint8).reshape((height, width, 3))
    except Exception:
        logger.exception("Failed to decode frame for journey node %s", journey_node.id)
        return None

    bbox = clip_bbox_to_frame([int(x) for x in journey_node.crop_bbox], width, height)
    if bbox is None:
        logger.warning("Journey node %s has invalid crop bounds", journey_node.id)
        return None
    crop = frame[bbox[1] : bbox[3], bbox[0] : bbox[2]]
    if crop.size == 0:
        logger.warning("Journey node %s produced an empty crop", journey_node.id)
        return None

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    success = cv2.imwrite(str(cache_path), crop)
    if not success:
        logger.warning("Failed to cache crop for journey node %s", journey_node.id)
        return None

    return encode_base64(crop)


def get_incident(incident_id: str, incident: SQLModels.Incident, db: Session):
    entities, crop = get_associated_entities_incident(incident, db)
    update_history = get_incident_update_history(incident_id, incident, db)
    alert_row = get_alert_incident_row(incident.id, db)
    return Incident(
        incident_id=incident_id,
        incident_type=incident.incident_type,
        display_title=alert_row.title if alert_row is not None else None,
        alert_level=alert_row.alert_level if alert_row is not None else None,
        metadata=(
            {
                "signal_family": alert_row.signal_family,
                "matched_target": alert_row.matched_target,
                "confidence": float(alert_row.confidence),
            }
            if alert_row is not None
            else None
        ),
        incident_time=incident.created_at.isoformat(),
        status=incident.status,
        location=Location(camera_id=incident.camera_id, zone_id=incident.zone_id),
        last_update_time=incident.updated_at.isoformat(),
        last_updated_by=incident.updated_by,
        update_history=update_history,
        entities=entities,
        crop=crop,
    )


def get_associated_entities_incident(incident: SQLModels.Incident, db: Session):
    associated_entities = []
    crop = None
    person_mapping = (
        db.query(SQLModels.IncidentPersonMapping)
        .filter_by(incident_id=incident.id)
        .all()
    )
    if person_mapping:
        for item in person_mapping:
            entity_card = get_entity_card(item.person_id, EntityType.PERSON, db)
            associated_entities.append(
                AssociatedEntity(role=item.role, entity=entity_card)
            )
            if crop is None and entity_card.crop is not None:
                crop = entity_card.crop
    elif incident.incident_type not in {IncidentType.UNATTENDED_BAG, IncidentType.ANOMALY, IncidentType.ALERT}:
        raise HTTPException(status_code=404, detail="associated persons not found")
    bag_mapping = (
        db.query(SQLModels.IncidentBagMapping).filter_by(incident_id=incident.id).all()
    )
    if bag_mapping:
        for item in bag_mapping:
            entity_card = get_entity_card(item.bag_id, EntityType.BAG, db)
            associated_entities.append(
                AssociatedEntity(role=item.role, entity=entity_card)
            )
    elif incident.incident_type == IncidentType.UNATTENDED_BAG:
        raise HTTPException(status_code=404, detail="associated bag not found")
    return associated_entities, crop


def get_entity_card(db_id: int, entity_type: str, db: Session):
    db_id = resolve_entity_id(db_id, entity_type, db)
    last_node = get_last_journey_node(db_id, entity_type, db)
    if last_node is None:
        current_id = resolve_entity_id(db_id, entity_type, db)
        model = get_entity_db_model(entity_type)
        entity_record = db.get(model, current_id)
        if entity_record is None:
            raise HTTPException(
                status_code=404, detail="Could not find entity record after resolving ID."
            )

        simple_entity_id = (
            f"{entity_type}-{entity_record.created_at.strftime('%Y%m%d')}-{db_id}"
        )

        return EntityCard(
            entity_id=simple_entity_id,
            entity_type=EntityType.FULL[entity_type],
            last_seen_time=entity_record.created_at.isoformat(),
            location=None,
            crop=None,
        )
    if last_node.stop_timestamp is None:
        last_seen = datetime.now().isoformat()
    else:
        last_seen = datetime.fromtimestamp(last_node.stop_timestamp).isoformat()
    return EntityCard(
        entity_id=create_entity_id(last_node, entity_type, db_id),
        entity_type=EntityType.FULL[entity_type],
        last_seen_time=last_seen,
        location=Location(camera_id=last_node.camera_id, zone_id=last_node.zone_id),
        crop=get_journey_crop(last_node, db),
    )


def get_entity_db_model(entity_type: str):
    if entity_type == EntityType.PERSON:
        return SQLModels.Person
    elif entity_type == EntityType.BAG:
        return SQLModels.Bag
    raise HTTPException(status_code=400, detail=f"invalid entity type {entity_type}")


def get_entity_instance_db_model(entity_type: str):
    if entity_type == EntityType.PERSON:
        return SQLModels.PersonInstance
    elif entity_type == EntityType.BAG:
        return SQLModels.BagInstance
    raise HTTPException(status_code=400, detail=f"invalid entity type {entity_type}")


def get_entity_incident_db_model(entity_type: str):
    if entity_type == EntityType.PERSON:
        return SQLModels.IncidentPersonMapping
    elif entity_type == EntityType.BAG:
        return SQLModels.IncidentBagMapping
    raise HTTPException(status_code=400, detail=f"invalid entity type {entity_type}")


def get_incident_entity_db_model(incident_type: str):
    if incident_type == IncidentType.UNATTENDED_BAG:
        return SQLModels.IncidentBagMapping
    else:
        return SQLModels.IncidentPersonMapping


def get_entity_journey_db_model(entity_type: str):
    if entity_type == EntityType.PERSON:
        return SQLModels.PersonJourneyMapping
    elif entity_type == EntityType.BAG:
        return SQLModels.BagJourneyMapping
    raise HTTPException(status_code=400, detail=f"invalid entity type {entity_type}")


def get_entity_entity_db_models(entity_type: str):
    if entity_type == EntityType.PERSON:
        return (
            SQLModels.PersonBagMapping.bag_id,
            EntityType.BAG,
        )
    elif entity_type == EntityType.BAG:
        return (
            SQLModels.PersonBagMapping.person_id,
            EntityType.PERSON,
        )
    raise HTTPException(status_code=400, detail=f"invalid entity type {entity_type}")


def get_entity_db_id_key(entity_type: str):
    if entity_type == EntityType.PERSON:
        return "person_id"
    elif entity_type == EntityType.BAG:
        return "bag_id"
    raise HTTPException(status_code=400, detail=f"invalid entity type {entity_type}")


def get_last_entity_instance(db_id: int, entity_type: str, db: Session):
    model = get_entity_instance_db_model(entity_type)
    id_key = get_entity_db_id_key(entity_type)
    last_instance = (
        db.query(model)
        .filter_by(**{id_key: db_id})
        .order_by(model.timestamp.desc())
        .first()
    )
    if last_instance is None:
        raise HTTPException(status_code=404, detail="entity instance not found")
    return last_instance


def create_entity_id(node: SQLModels.JourneyNode, entity_type: str, db_id: int):
    date_string = datetime.fromtimestamp(node.start_timestamp).strftime("%Y%m%d")
    return f"{entity_type}-{date_string}-{db_id}"


def get_incident_update_history(
    str_incident_id: str, incident: SQLModels.Incident, db: Session
):
    updates = (
        db.query(SQLModels.IncidentUpdate)
        .filter_by(incident_id=incident.id)
        .order_by(SQLModels.IncidentUpdate.created_at)
        .all()
    )
    return [
        IncidentUpdate(
            incident_id=str_incident_id,
            new_status=update.new_status,
            old_status=update.old_status,
            update_time=update.created_at.isoformat(),
            updated_by=update.updated_by,
        )
        for update in updates
    ]


def parse_entity_id(entity_id: str):
    id_parts = entity_id.split("-")
    if len(id_parts) != 3:
        raise HTTPException(status_code=400, detail="invalid entity ID format")
    if not id_parts[2].isdigit():
        raise HTTPException(status_code=400, detail="invalid entity ID format")
    db_id = int(id_parts[2])
    entity_type = id_parts[0]
    return db_id, entity_type


def get_entity(db_id: int, entity_type: str, db: Session):
    last_node = get_last_journey_node(db_id, entity_type, db)

    if last_node is None:
        # Entity exists but has no journey nodes. Return a minimal entity object.
        current_id = resolve_entity_id(db_id, entity_type, db)
        model = get_entity_db_model(entity_type)
        entity_record = db.get(model, current_id)
        if entity_record is None:
            raise HTTPException(
                status_code=404, detail="Could not find entity record after resolving ID."
            )

        simple_entity_id = (
            f"{entity_type}-{entity_record.created_at.strftime('%Y%m%d')}-{db_id}"
        )

        return Entity(
            entity_id=simple_entity_id,
            entity_type=EntityType.FULL[entity_type],
            last_seen_time=entity_record.created_at.isoformat(),
            location=None,
            associated_entities=get_associated_entities_entity(db_id, entity_type, db),
            associated_incidents=get_associated_incidents(db_id, entity_type, db),
            journey=[],  # No journey nodes
            crop=None,
        )

    if last_node.stop_timestamp is None:
        last_seen = datetime.now().isoformat()
    else:
        last_seen = datetime.fromtimestamp(last_node.stop_timestamp).isoformat()
    return Entity(
        entity_id=create_entity_id(last_node, entity_type, db_id),
        entity_type=EntityType.FULL[entity_type],
        last_seen_time=last_seen,
        location=Location(camera_id=last_node.camera_id, zone_id=last_node.zone_id),
        associated_entities=get_associated_entities_entity(db_id, entity_type, db),
        associated_incidents=get_associated_incidents(db_id, entity_type, db),
        journey=get_journey(db_id, entity_type, db),
        crop=get_journey_crop(last_node, db),
    )


def get_associated_incidents(entity_id: int, entity_type: str, db: Session):
    current_entity_id = resolve_entity_id(entity_id, entity_type, db)

    model = get_entity_incident_db_model(entity_type)
    id_key = get_entity_db_id_key(entity_type)
    incident_data = (
        db.query(model.incident_id, model.role)
        .filter_by(**{id_key: current_entity_id})
        .all()
    )
    incident_roles = {incident_id: role for incident_id, role in incident_data}
    ids = list(incident_roles.keys())
    db_incidents = (
        db.query(SQLModels.Incident).filter(SQLModels.Incident.id.in_(ids)).all()
    )
    associated_incidents = []
    for incident in db_incidents:
        incident_card = get_incident_card(incident, db, include_crop=False)
        role = incident_roles[incident.id]
        associated_incidents.append(
            AssociatedIncident(role=role, incident=incident_card)
        )
    return associated_incidents


def get_journey(entity_id: int, entity_type: str, db: Session):
    node_db_ids = get_journey_node_ids(entity_id, entity_type, db)
    db_nodes = (
        db.query(SQLModels.JourneyNode)
        .filter(SQLModels.JourneyNode.id.in_(node_db_ids))
        .order_by(SQLModels.JourneyNode.start_timestamp.desc())
        .all()
    )
    return [
        JourneyNode(
            start_time=datetime.fromtimestamp(node.start_timestamp).isoformat(),
            stop_time=(
                datetime.fromtimestamp(node.stop_timestamp).isoformat()
                if node.stop_timestamp
                else None
            ),
            location=Location(camera_id=node.camera_id, zone_id=node.zone_id),
            crop=get_journey_crop(node, db),
        )
        for node in db_nodes
    ]


def get_associated_entities_entity(entity_id: int, entity_type: str, db: Session):
    current_entity_id = resolve_entity_id(entity_id, entity_type, db)

    associated_entity_cards = []
    model_column, other_type = get_entity_entity_db_models(entity_type)
    id_key = get_entity_db_id_key(entity_type)
    associated_db_ids = (
        db.query(model_column).filter_by(**{id_key: current_entity_id}).all()
    )
    for db_id in associated_db_ids:
        associated_entity_cards.append(get_entity_card(db_id[0], other_type, db))
    return associated_entity_cards


def get_poi_card(db_poi: SQLModels.POISearch, db: Session):
    num_entities = 0
    last_update_time = None
    seconds_since_update = None
    result = get_db_poi_result(db_poi, db)
    if result is not None:
        num_entities = len(result.person_ids)
        last_update_time = result.created_at.isoformat()
        seconds_since_update = seconds_since_datetime(result.created_at)
    return POIResultCard(
        id=db_poi.id,
        name=db_poi.name,
        num_entities=num_entities,
        last_update_time=last_update_time,
        seconds_since_update=seconds_since_update,
        crop=get_poi_crop(db_poi),
    )


def get_poi_result(db_poi: SQLModels.POISearch, db: Session):
    entities = []
    last_update_time = None
    seconds_since_update = None
    result = get_db_poi_result(db_poi, db)
    if result is not None:
        entities = [
            get_entity_card(entity_id, EntityType.PERSON, db)
            for entity_id in result.person_ids
        ]
        last_update_time = result.created_at.isoformat()
        seconds_since_update = seconds_since_datetime(result.created_at)
    return POIResult(
        id=db_poi.id,
        name=db_poi.name,
        entities=entities,
        last_update_time=last_update_time,
        seconds_since_update=seconds_since_update,
        crop=get_poi_crop(db_poi),
    )

def get_poi_crop(db_poi: SQLModels.POISearch):
    if not db_poi.crop_dir or not os.path.isdir(db_poi.crop_dir):
        return None
    crop_files = sorted(os.listdir(db_poi.crop_dir))
    if not crop_files:
        return None
    crop_name = crop_files[0]
    return get_crop(os.path.join(db_poi.crop_dir, crop_name))


def get_db_poi_result(db_poi: SQLModels.POISearch, db: Session):
    result_mapping = (
        db.query(SQLModels.POIResultMapping)
        .filter_by(search_id=db_poi.id)
        .order_by(SQLModels.POIResultMapping.created_at.desc())
        .first()
    )
    if result_mapping is None:
        return None
    result = db.get(SQLModels.POISearchResult, result_mapping.result_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail="poi result record found but no result found"
        )
    return result
