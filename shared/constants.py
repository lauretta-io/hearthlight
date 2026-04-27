from typing import Literal
import logging


SHORT_SLEEP = 0.01
QUEUE_TIMEOUT = 1

ORCHESTRATION_LOG_DIR = "shared/output/orchestration_logs/"

ORCHESTRATION_LOG_LEVEL = logging.INFO
PIKA_LOG_LEVEL = logging.WARNING

FRAME_UPDATE_INTERVAL = 1
FPS_INTERVAL = 10
ANOMALY_EVAL_INTERVAL = 16

STREAM_MESSAGES_PER_FRAME = 5

# fmt: off
VIDEO_EXTENSIONS = ["mp4", "mov", "wmv", "avi", "avchd", "flv", "f4v", "mkv", "webm", "ts"]
# fmt: on
VIDEO_CONTENT_TYPE_PREFIX = "video/"
VIDEO_CONTENT_TYPE_FALLBACKS = ["application/octet-stream"]


class ModuleNames:
    INGESTOR = "INGESTOR"
    REID = "REID"
    ASSOCIATION = "ASSOCIATION"
    ANOMALY = "ANOMALY"
    WEBAPP = "WEBAPP"


class Tasks:
    PERSON = "PERSON"
    GUN = "GUN"
    BAG = "BAG"
    POI = "POI"


TaskTypeStr = Literal["PERSON", "GUN", "BAG", "POI"]


class DetectorClasses:
    PERSON = Tasks.PERSON
    BAG = Tasks.BAG
    GUN = Tasks.GUN


REID_CLASSES = (
    DetectorClasses.PERSON,
    DetectorClasses.BAG,
)


class EntityType:
    PERSON = "P"
    BAG = "B"

    FULL = {PERSON: DetectorClasses.PERSON, BAG: DetectorClasses.BAG}


class IncidentType:
    GUN = "GUN"
    UNATTENDED_BAG = "UNATTENDED BAG"
    LOITERING = "LOITERING"
    ANOMALY = "ANOMALY"
    ALERT = "ALERT"

    INCIDENT_TYPE_ABBR = {
        GUN: "GUN",
        UNATTENDED_BAG: "UB",
        LOITERING: "LT",
        ANOMALY: "AN",
        ALERT: "AL",
    }

    @classmethod
    def get_abbr(cls, incident_type):
        return cls.INCIDENT_TYPE_ABBR.get(incident_type)


IncidentTypeStr = Literal[
    "GUN",
    "UNATTENDED BAG",
    "LOITERING",
    "ANOMALY",
    "ALERT",
]


class IncidentStatus:
    UNCONFIRMED = "UNCONFIRMED"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN PROGRESS"
    PENDING_RESOLVE = "PENDING RESOLUTION"
    RESOLVED = "RESOLVED"


class Role:
    GUNMAN = "GUNMAN"
    BAG = "BAG"
    OWNER = "OWNER"
    LOITERER = "LOITERER"

ANOMALY_ADDITIONAL_CONFIG = {
    "extra_messages": [{"role": "assistant", "content": [{"type": "text", "text": "/no_think"}]},],
    "extra_body": {
        "model": "OpenGVLab/InternVL_2_5_HiCo_R16", 
        "temperature": 0, 
        "max_tokens": 1024,
        "frequency_penalty": 1,
        "stop": '}\n',              # Helps reduce ending newlines/whitespace
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "anomaly_report",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "scene_summary": {"type": "string", "description": "A description of what is clearly visible in the foreground scene"},
                        "visible_items": {
                            "type": "string",
                            "description": "Comma-separated list of items from ANOMALOUS ITEMS that scored above 5 in think. Empty string if none scored above 5."
                        },
                        "visible_activities": {
                            "type": "string",
                            "description": "Comma-separated list of activities from ANOMALOUS ACTIVITIES that scored above 5 in think. Empty string if none scored above 5."
                        },
                        "think": {
                            "type": "string",
                            "description": "Score every entry in ANOMALOUS ITEMS and ANOMALOUS ACTIVITIES 0-10 based on likelihood of being present. Format: 'item:score, item:score, ...'. Score 0 means definitely not present, 10 means definitely present."
                        },
                        "confidence": {
                            "type": "number",
                            "description": "A score between 0 and 1 reflecting overall anomaly likelihood based on the scores in think. 0 means no anomaly, 1 means definite anomaly.",
                            "minimum": 0,
                            "maximum": 1
                        },
                        "anomaly_detected": {
                            "type": "boolean",
                            "description": "True if confidence is above 0.5, false otherwise."
                        },
                        "anomaly_category": {
                            "type": "string",
                            "description": "Name the anomaly category if anomaly_detected is True. Based on the visible activities and items"
                        },
                    },
                    "required": ["scene_summary", "think", "visible_items", "visible_activities", "confidence", "anomaly_detected", "anomaly_category"],
                    "additionalProperties": False,
                }
            }
        }
    }
}
