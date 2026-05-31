"""
This file contains the Pydantic models for the Operations API.
"""

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from ..constants import IncidentStatus


VALID_INCIDENT_STATUSES = {
    IncidentStatus.UNCONFIRMED,
    IncidentStatus.CONFIRMED,
    IncidentStatus.IN_PROGRESS,
    IncidentStatus.PENDING_RESOLVE,
    IncidentStatus.RESOLVED,
}


class Location(BaseModel):
    camera_id: int
    zone_id: Optional[int]


class IncidentUpdate(BaseModel):
    incident_id: str
    new_status: str
    update_time: Optional[str]
    updated_by: Optional[str] = Field(default=None, max_length=255)
    old_status: Optional[str] = None

    @field_validator("incident_id")
    def validate_incident_id(cls, value):
        value = value.strip()
        if len(value.split("-")) != 3:
            raise ValueError("incident_id must have format TYPE-YYYYMMDD-ID")
        return value

    @field_validator("new_status", "old_status")
    def validate_status(cls, value):
        if value is None:
            return value
        value = value.strip().upper()
        if value not in VALID_INCIDENT_STATUSES:
            raise ValueError(f"invalid incident status {value}")
        return value

    @field_validator("updated_by")
    def validate_updated_by(cls, value):
        if value is None:
            return value
        value = value.strip()
        return value or None


class IncidentCard(BaseModel):
    run_identifier: Optional[str] = None
    incident_id: str
    incident_type: str
    display_title: Optional[str] = None
    alert_level: Optional[str] = None
    metadata: Optional[dict] = None
    delivery_summary: Optional[str] = None
    incident_time: str
    status: str
    location: Location
    last_update_time: str
    last_updated_by: Optional[str]
    crop: Optional[str]


class EntityCard(BaseModel):
    entity_id: str
    entity_type: str
    last_seen_time: str
    location: Optional[Location]
    crop: Optional[str]


class JourneyNode(BaseModel):
    location: Location
    start_time: str
    stop_time: Optional[str]
    crop: Optional[str]


class AssociatedIncident(BaseModel):
    role: str
    incident: IncidentCard


class Entity(BaseModel):
    entity_id: str
    entity_type: str
    last_seen_time: str
    location: Optional[Location]
    crop: Optional[str]
    associated_entities: Optional[List[EntityCard]]
    associated_incidents: Optional[List[AssociatedIncident]]
    journey: Optional[List[JourneyNode]]


class AssociatedEntity(BaseModel):
    role: str
    entity: EntityCard


class Incident(BaseModel):
    run_identifier: Optional[str] = None
    incident_id: str
    incident_type: str
    display_title: Optional[str] = None
    alert_level: Optional[str] = None
    metadata: Optional[dict] = None
    delivery_summary: Optional[str] = None
    media_type: Optional[str] = None
    media_event_id: Optional[str] = None
    incident_time: str
    status: str
    location: Location
    last_update_time: str
    update_history: List[IncidentUpdate]
    last_updated_by: Optional[str]
    entities: Optional[List[AssociatedEntity]]
    crop: Optional[str]


class POIResult(BaseModel):
    id: int
    name: str
    entities: List[EntityCard]
    last_update_time: Optional[str]
    seconds_since_update: Optional[int] = None
    crop: Optional[str]

class POIResultCard(BaseModel):
    id: int
    name: str
    num_entities: int
    last_update_time: Optional[str]
    seconds_since_update: Optional[int] = None
    crop: Optional[str]
