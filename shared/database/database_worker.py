from collections import defaultdict
from datetime import datetime
import json
from typing import TypeVar
import logging

from sqlalchemy.exc import SQLAlchemyError

from .database import SessionLocal
from ..models import SQLModels
from ..models.SQLModels import Base
from ..models import DataModels
from ..utils.backoff import with_exponential_backoff
from ..constants import DetectorClasses, IncidentStatus

logger = logging.getLogger(__name__)
SQLModel = TypeVar("SQLModel", bound=Base)


class DatabaseWorker:
    run_id = None

    @classmethod
    @with_exponential_backoff(max_tries=10, max_delay=10)
    def set_run_id(cls, run_identifier: str):
        with SessionLocal() as db:
            run = (
                db.query(SQLModels.Run).filter_by(run_identifier=run_identifier).first()
            )
            if not run:
                raise Exception("Run identifier not found in database")
        cls.run_id = run.id

    @classmethod
    def get_cameras(cls):
        with SessionLocal() as db:
            return (
                db.query(SQLModels.CameraRecording).filter_by(run_id=cls.run_id).all()
            )

    def __init__(self):
        self.confirmed_persons = set()
        self.confirmed_bags = set()
        self.journey_node_ids = defaultdict(lambda: defaultdict(dict))

        self.SessionLocal = SessionLocal

    # CRUD operations

    def create(self, item: SQLModel) -> SQLModel | None:
        try:
            self.db.add(item)
            self.db.commit()
            self.db.refresh(item)
            return item
        except SQLAlchemyError:
            self.db.rollback()
            logger.exception("Failed to create item in database")

    def get(self, model: type[SQLModel], id_: int) -> SQLModel | None:
        db_model = self.db.query(model).get(id_)
        return db_model

    def update(self, item: SQLModel) -> SQLModel | None:
        try:
            item.updated_at = datetime.now().isoformat()
            self.db.commit()
            self.db.refresh(item)
            return item
        except SQLAlchemyError:
            self.db.rollback()
            logger.exception("Failed to update item in database")

    def batch_update(self, items: list[SQLModel]) -> None:
        try:
            updated_at = datetime.now().isoformat()
            for item in items:
                item.updated_at = updated_at
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            logger.exception("Failed to update items in database")

    def delete(self, item: SQLModel) -> None:
        try:
            item.is_deleted = True
            current_time = datetime.now().isoformat()
            item.deleted_at = current_time
            item.updated_at = current_time
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            logger.exception("Failed to delete item in database")

    def get_persons(self):
        with self.SessionLocal() as self.db:
            db_models = self.db.query(SQLModels.Person).all()
        return db_models

    # Create functions

    def create_camera_recording(self, camera: DataModels.Camera):
        assert DatabaseWorker.run_id is not None, "run id is not set"
        if not self.get(SQLModels.Camera, camera.cam_id):
            self.create_camera(camera)
        cam_recording = SQLModels.CameraRecording(
            cam_id=camera.cam_id,
            run_id=DatabaseWorker.run_id,
            cam_recording_path=camera.recording_path,
            source_kind=camera.camera_type,
            source_template_id=camera.source_template_id,
            upload_id=camera.upload_id,
            total_frames=camera.total_frames,
            start_timestamp=camera.start_timestamp,
            start_datetime=camera.start_datetime,
            width=camera.width,
            height=camera.height,
        )
        self.create(cam_recording)

    def create_camera(self, camera: DataModels.Camera):
        camera = SQLModels.Camera(
            id=camera.cam_id,
            name=camera.name,
            tasks=camera.tasks,
            cam_ip_address=camera.source,
            camera_loc_x=camera.x_loc,
            camera_loc_y=camera.y_loc,
        )
        self.create(camera)

    def publish_run(self, run: DataModels.Run):
        run = SQLModels.Run(
            run_identifier=run.run_identifier,
            start_timestamp=run.start_timestamp,
            start_datetime=run.start_datetime,
            output_dir=run.output_dir,
        )
        run = self.create(run)
        assert run is not None, "failed to create run"
        DatabaseWorker.run_id = run.id

    def create_bag(self, id: int):
        bag = SQLModels.Bag(id=id, run_id=DatabaseWorker.run_id)
        self.create(bag)

    def create_bag_instance(self, track: DataModels.TrackInstance):
        assert track.real_id is not None

        if track.real_id not in self.confirmed_bags:
            self.create_bag(track.real_id)
            self.confirmed_bags.add(track.real_id)

        bag_instance = SQLModels.BagInstance(
            run_id=DatabaseWorker.run_id,
            bag_id=track.real_id,
            track_id=track.track_id,
            cam_id=track.cam_id,
            zone_id=track.zone_id,
            bbox=track.bbox,
            datetime=datetime.fromtimestamp(track.timestamp),
            timestamp=track.timestamp,
        )
        self.create(bag_instance)

    def create_person(self, id: int):
        person = SQLModels.Person(
            id=id,
            run_id=DatabaseWorker.run_id,
        )
        self.create(person)

    def create_person_instance(self, track: DataModels.TrackInstance):
        assert track.real_id is not None

        if track.real_id not in self.confirmed_persons:
            self.create_person(track.real_id)
            self.confirmed_persons.add(track.real_id)

        person_instance = SQLModels.PersonInstance(
            run_id=DatabaseWorker.run_id,
            person_id=track.real_id,
            track_id=track.track_id,
            cam_id=track.cam_id,
            zone_id=track.zone_id,
            bbox=track.bbox,
            feature_id=track.feature_id,
            timestamp=track.timestamp,
            datetime=datetime.fromtimestamp(track.timestamp),
            frame_id=track.frame_id,
        )
        self.create(person_instance)

    def create_incident(self, incident):
        incident_model = SQLModels.Incident(
            id=incident.id,
            run_id=DatabaseWorker.run_id,
            incident_type=incident.incident_type,
            status=incident.status,
            timestamp=incident.timestamp,
            camera_id=incident.cam_id,
            zone_id=incident.zone_id,
        )
        incident_row = self.create(incident_model)
        if incident_row is None:
            logger.error(f"Failed to create incident {incident.id}")
            return
        for entity in incident.entities.entities:
            role = incident.entities.roles[entity.id]
            if entity.clss == DetectorClasses.BAG:
                self.create_incident_bag_mapping(incident_row.id, entity.id, role)
            elif entity.clss == DetectorClasses.PERSON:
                self.create_incident_person_mapping(incident_row.id, entity.id, role)
            else:
                logger.error(f"Unknown entity class {entity.clss}")
                return

    def create_incident_person_mapping(
        self, incident_id: int, person_id: int, role: str
    ):
        mapping = SQLModels.IncidentPersonMapping(
            incident_id=incident_id,
            person_id=person_id,
            role=role,
        )
        self.create(mapping)

    def create_incident_bag_mapping(self, incident_id: int, bag_id: int, role: str):
        mapping = SQLModels.IncidentBagMapping(
            incident_id=incident_id,
            bag_id=bag_id,
            role=role,
        )
        self.create(mapping)

    def create_frame(self, frame: DataModels.Frame, frame_id: int):
        assert DatabaseWorker.run_id is not None, "run id is not set"
        frame = SQLModels.Frame(
            run_id=DatabaseWorker.run_id,
            cam_id=frame.cam_id,
            frame_id=frame_id,
            path=frame.save_path,
            timestamp=frame.timestamp,
            datetime=datetime.fromtimestamp(frame.timestamp),
        )
        self.create(frame)

    def create_journey_node(self, node: DataModels.JourneyNode):
        track_instance = node.track_instance
        assert track_instance.real_id is not None

        node_model = SQLModels.JourneyNode(
            run_id=DatabaseWorker.run_id,
            crop_bbox=track_instance.bbox,
            camera_id=node.cam_id,
            zone_id=node.zone_id,
            start_timestamp=node.start_timestamp,
            stop_timestamp=None,
        )
        node_row = self.create(node_model)
        if node_row is None:
            logger.error("Failed to create JourneyNode")
            return

        if track_instance.clss == DetectorClasses.PERSON:
            self.create_person_journey_mapping(node_row.id, track_instance.real_id)
        elif track_instance.clss == DetectorClasses.BAG:
            self.create_bag_journey_mapping(node_row.id, track_instance.real_id)
        else:
            logger.error(
                f"Unknown class in JourneyNode's track ({track_instance.clss})"
            )
            return
        return node_row.id

    def create_person_journey_mapping(self, node_id: int, person_id: int):
        person_journey_model = SQLModels.PersonJourneyMapping(
            person_id=person_id,
            journey_node_id=node_id,
        )
        self.create(person_journey_model)

    def create_bag_journey_mapping(self, node_id: int, bag_id: int):
        person_journey_model = SQLModels.BagJourneyMapping(
            bag_id=bag_id,
            journey_node_id=node_id,
        )
        self.create(person_journey_model)

    def create_person_bag_mapping(self, bag_id: int, owner_id: int):
        person_bag_model = SQLModels.PersonBagMapping(
            person_id=owner_id,
            bag_id=bag_id,
        )
        self.create(person_bag_model)

    def create_poi_result(self, result: DataModels.POIResult):
        search_row = self.get(SQLModels.POISearch, result.search_id)
        if search_row is None:
            logger.error(f"Search with id {result.search_id} not found")
            return
        result_model = SQLModels.POISearchResult(
            run_id=DatabaseWorker.run_id,
            person_ids=result.ids,
        )
        result_row = self.create(result_model)
        if result_row is None:
            logger.error("Failed to create POISearchResult")
            return

        mapping = SQLModels.POIResultMapping(
            result_id=result_row.id,
            search_id=search_row.id,
        )
        self.create(mapping)

    def create_anomaly_event(self, event: DataModels.AnomalyEvent):
        anomaly_model = SQLModels.AnomalyEvent(
            run_id=DatabaseWorker.run_id,
            source_template_id=event.source_id,
            camera_id=None,
            frame_id=event.frame_id,
            event_key=event.event_id,
            model_key=event.model_key,
            category=event.category,
            title=event.title,
            score=event.score,
            reasoning=event.reasoning,
            visible_items_json=json.dumps(event.visible_items),
            visible_activities_json=json.dumps(event.visible_activities),
            asset_refs_json=json.dumps(
                [asset.model_dump() for asset in event.asset_references]
            ),
        )
        self.create(anomaly_model)

    # Update Functions

    def resolve_incident(self, incident_id: int):
        incident = self.get(SQLModels.Incident, incident_id)
        if incident and incident.status == IncidentStatus.UNCONFIRMED:
            update_model = SQLModels.IncidentUpdate(
                incident_id=incident_id,
                run_id=DatabaseWorker.run_id,
                new_status=IncidentStatus.PENDING_RESOLVE,
                old_status=incident.status,
                updated_by="system",
            )
            update = self.create(update_model)
            if update is not None:
                incident.status = update.new_status
                incident.current_update = update_model.id
                self.update(incident)
        else:
            logger.error(f"Incident with id {incident_id} not found.")

    def end_journey_node(self, node: DataModels.JourneyNode, node_id: int):
        node_row = self.get(SQLModels.JourneyNode, node_id)
        if node_row:
            node_row.stop_timestamp = node.stop_timestamp
            self.update(node_row)
        else:
            logger.error(f"Journey node with id {node_id} not found.")

    # Publish functions

    def publish_reid_data(self, tracks: dict[str, list[DataModels.TrackInstance]]):
        with self.SessionLocal() as self.db:
            for clss in tracks:
                for track in tracks[clss]:
                    if clss == DetectorClasses.PERSON:
                        self.create_person_instance(track)
                    elif clss == DetectorClasses.BAG:
                        self.create_bag_instance(track)

    def publish_journey_data(
        self,
        new_nodes: list[DataModels.JourneyNode],
        completed_nodes: list[DataModels.JourneyNode],
    ):
        with self.SessionLocal() as self.db:
            for node in completed_nodes:
                track = node.track_instance
                node_id = self.journey_node_ids[track.clss][track.real_id].get(
                    track.cam_id
                )
                if node_id is None:
                    logger.error(
                        f"Node id not found for track {track.clss} {track.real_id} in cam {track.cam_id}"
                    )
                    continue
                self.end_journey_node(node, node_id)
                del self.journey_node_ids[track.clss][track.real_id][track.cam_id]
                if not self.journey_node_ids[track.clss][track.real_id]:
                    del self.journey_node_ids[track.clss][track.real_id]
            for node in new_nodes:
                node_id = self.create_journey_node(node)
                track = node.track_instance
                self.journey_node_ids[track.clss][track.real_id][track.cam_id] = node_id

    def publish_poi_data(self, poi_results: list[DataModels.POIResult]):
        with self.SessionLocal() as self.db:
            for poi_result in poi_results:
                self.create_poi_result(poi_result)

    def publish_bag_owner_pairs(self, pairs: list[tuple[int, int]]):
        with self.SessionLocal() as self.db:
            for bag_id, owner_id in pairs:
                self.create_person_bag_mapping(bag_id, owner_id)

    def publish_frames(self, frames: list[DataModels.Frame], frame_id: int):
        with self.SessionLocal() as self.db:
            for frame in frames:
                self.create_frame(frame, frame_id)

    def publish_incidents(self, new_incidents: list, resolved_incidents: list):
        with self.SessionLocal() as self.db:
            for incident in new_incidents:
                self.create_incident(incident)
            for incident in resolved_incidents:
                self.resolve_incident(incident.id)

    def publish_run_info(self, run: DataModels.Run):
        with self.SessionLocal() as self.db:
            self.publish_run(run)
            for camera in run.cameras:
                self.create_camera_recording(camera)

    def create_loitering_incident(self, incident) -> None:
        incident_row = SQLModels.Incident(
            run_id=DatabaseWorker.run_id,
            incident_type=incident.incident_type,
            status=incident.status,
            timestamp=incident.first_seen,
            camera_id=incident.cam_id,
            zone_id=incident.zone_id,
        )
        incident_row = self.create(incident_row)
        if incident_row is None:
            logger.error(f"Failed to create loitering incident for person {incident.person_id}")
            return
        self.create_incident_person_mapping(incident_row.id, incident.person_id, incident.role)

    def publish_loitering_incidents(self, incidents: list) -> None:
        if not incidents:
            return
        with self.SessionLocal() as self.db:
            for incident in incidents:
                self.create_loitering_incident(incident)

    def publish_anomaly_data(self, anomaly_events: list[DataModels.AnomalyEvent]):
        with self.SessionLocal() as self.db:
            for event in anomaly_events:
                self.create_anomaly_event(event)

    def check_for_resolutions(self, incidents: set | list):
        resolved_incidents = set()
        with self.SessionLocal() as self.db:
            for incident in incidents:
                db_incident = self.get(SQLModels.Incident, incident.id)
                if db_incident is not None:
                    if db_incident.status == "resolved":
                        resolved_incidents.add(incident)
        return resolved_incidents

    def publish_id_updates(self, id_updates: dict[str, dict[int, int]]):
        with self.SessionLocal() as self.db:
            person_updates = id_updates.get(DetectorClasses.PERSON, {})
            for temp_id, persistent_id in person_updates.items():
                updated_rows = []

                # Skip if no actual change
                if temp_id == persistent_id:
                    continue

                # Ensure the temporary record exists
                person = self.get(SQLModels.Person, temp_id)
                if not person:
                    logger.warning(
                        f"Person with temp_id {temp_id} not found for ID update."
                    )
                    continue

                # Create the permanent mapping record
                mapping = SQLModels.EntityIdMapping(
                    persistent_id=persistent_id,
                    temporary_id=temp_id,
                    entity_type=DetectorClasses.PERSON,
                )
                self.db.add(mapping)

                # Find all child records pointing to the temp_id and update them
                # to point to the persistent_id.
                fk_updates = self.update_person_foreign_keys(
                    temp_id, persistent_id
                )
                updated_rows.extend(fk_updates)

                # Check if the persistent_id already exists (merge vs. rename)
                if not self.get(SQLModels.Person, persistent_id):
                    # Create case: The persistent_id is new.
                    # Create a new person record with the persistent_id.
                    self.create_person(persistent_id)
                    self.confirmed_persons.add(persistent_id)
                self.delete(person)
                if temp_id in self.confirmed_persons:
                    self.confirmed_persons.remove(temp_id)

                self.batch_update(updated_rows)

            bag_updates = id_updates.get(DetectorClasses.BAG, {})
            for temp_id, persistent_id in bag_updates.items():
                updated_rows = []

                if temp_id == persistent_id:
                    continue

                bag = self.get(SQLModels.Bag, temp_id)
                if not bag:
                    logger.warning(f"Bag with temp_id {temp_id} not found for ID update.")
                    continue

                mapping = SQLModels.EntityIdMapping(
                    persistent_id=persistent_id,
                    temporary_id=temp_id,
                    entity_type=DetectorClasses.BAG,
                )
                self.db.add(mapping)

                fk_updates = self.update_bag_foreign_keys(temp_id, persistent_id)
                updated_rows.extend(fk_updates)

                if not self.get(SQLModels.Bag, persistent_id):
                    self.create_bag(persistent_id)
                    self.confirmed_bags.add(persistent_id)
                self.delete(bag)
                if temp_id in self.confirmed_bags:
                    self.confirmed_bags.remove(temp_id)

                self.batch_update(updated_rows)

    def update_person_foreign_keys(self, old_id: int, new_id: int):
        updated_rows = []
 
        person_instances = (
            self.db.query(SQLModels.PersonInstance).filter_by(person_id=old_id).all()
        )
        for person_instance in person_instances:
            person_instance.person_id = new_id
            updated_rows.append(person_instance)

        person_bag_mappings = (
            self.db.query(SQLModels.PersonBagMapping).filter_by(person_id=old_id).all()
        )
        for person_bag_mapping in person_bag_mappings:
            person_bag_mapping.person_id = new_id
            updated_rows.append(person_bag_mapping)

        person_incident_mappings = (
            self.db.query(SQLModels.IncidentPersonMapping)
            .filter_by(person_id=old_id)
            .all()
        )
        for person_incident_mapping in person_incident_mappings:
            person_incident_mapping.person_id = new_id
            updated_rows.append(person_incident_mapping)

        person_journey_mappings = (
            self.db.query(SQLModels.PersonJourneyMapping)
            .filter_by(person_id=old_id)
            .all()
        )
        for person_journey_mapping in person_journey_mappings:
            person_journey_mapping.person_id = new_id
            updated_rows.append(person_journey_mapping)

        return updated_rows

    def update_bag_foreign_keys(self, old_id: int, new_id: int):
        updated_rows = []
        bag_instances = (
            self.db.query(SQLModels.BagInstance).filter_by(bag_id=old_id).all()
        )
        for bag_instance in bag_instances:
            bag_instance.bag_id = new_id
            updated_rows.append(bag_instance)

        person_bag_mappings = (
            self.db.query(SQLModels.PersonBagMapping).filter_by(bag_id=old_id).all()
        )
        for person_bag_mapping in person_bag_mappings:
            person_bag_mapping.bag_id = new_id
            updated_rows.append(person_bag_mapping)

        bag_incident_mappings = (
            self.db.query(SQLModels.IncidentBagMapping).filter_by(bag_id=old_id).all()
        )
        for bag_incident_mapping in bag_incident_mappings:
            bag_incident_mapping.bag_id = new_id
            updated_rows.append(bag_incident_mapping)

        bag_journey_mappings = (
            self.db.query(SQLModels.BagJourneyMapping).filter_by(bag_id=old_id).all()
        )
        for bag_journey_mapping in bag_journey_mappings:
            bag_journey_mapping.bag_id = new_id
            updated_rows.append(bag_journey_mapping)

        return updated_rows
