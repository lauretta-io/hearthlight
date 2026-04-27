from sqlalchemy import func
import logging

from .object_classes import Person, Bag
from shared.database.database import SessionLocal
from shared.models.SQLModels import Incident as SQLIncident
from shared.constants import Role, IncidentType, IncidentStatus, IncidentTypeStr

logger = logging.getLogger(__name__)


class IncidentEntities:
    def __init__(self, entities: list[Person | Bag], roles: list[str]):
        self.entities = entities
        self.roles = {entity.id: role for entity, role in zip(entities, roles)}

    def __getitem__(self, id: int):
        return self.entities[id]

    def __setitem__(self, id: int, value):
        self.entities[id] = value


class Incident:
    _id = None

    @classmethod
    def initialize_id_counter(cls):
        if cls._id is not None:
            return
        try:
            with SessionLocal() as db:
                cls._id = db.query(func.max(SQLIncident.id)).scalar() or 0
        except Exception as exc:
            logger.exception("Failed to initialize incident id counter")
            raise RuntimeError("failed to initialize incident id counter") from exc

    def __init__(
        self,
        incident_type: IncidentTypeStr,
        entities: list[Person | Bag],
        roles: list[str],
    ):
        Incident.initialize_id_counter()
        assert Incident._id is not None
        Incident._id += 1
        self.id = Incident._id
        self.incident_type = incident_type
        self.resolved = False
        self.status = IncidentStatus.UNCONFIRMED
        self.entities = IncidentEntities(entities, roles)

    def resolve(self):
        self.resolved = True


class GunIncident(Incident):
    def __init__(self, person: Person):
        super().__init__(IncidentType.GUN, [person], [Role.GUNMAN])

        self.cam_id = person.data.last_cam_id
        self.zone_id = person.data.zone_ids[self.cam_id]
        self.timestamp = person.data.last_timestamp

    def resolve(self):
        self.resolved = True
        assert isinstance(self.entities.entities[0], Person)
        self.entities.entities[0].gun_threat = 0


class UnattendedBag(Incident):
    def __init__(self, bag: Bag):
        entities = [bag] + list(bag.owners)
        roles = [Role.BAG] + [Role.OWNER] * len(bag.owners)

        super().__init__(IncidentType.UNATTENDED_BAG, entities, roles)  # type: ignore

        self.cam_id = bag.data.last_cam_id
        self.zone_id = bag.data.zone_ids[self.cam_id]
        self.timestamp = bag.last_time_attended

    def resolve(self):
        self.resolved = True
        bag = self.entities.entities[0]
        assert isinstance(bag, Bag)
        bag.last_time_attended = bag.data.last_timestamp
        bag.unattended = False
