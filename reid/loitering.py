from dataclasses import dataclass

from ..shared.constants import IncidentStatus, IncidentType, Role


@dataclass
class LoiteringEntry:
    first_seen: float
    last_seen: float
    cam_id: int
    zone_id: int | None = None
    is_loitering: bool = False


@dataclass
class LoiteringIncident:
    person_id: int
    cam_id: int
    first_seen: float
    duration: float
    zone_id: int | None = None
    incident_type: str = IncidentType.LOITERING
    status: str = IncidentStatus.UNCONFIRMED
    role: str = Role.LOITERER


class LoiteringManager:
    def __init__(self, threshold: float = 300.0):
        self._entries: dict[int, LoiteringEntry] = {}
        self.threshold = threshold

    def update(self, tracks: list) -> None:
        """Upsert presence entries for each track. Call for confirmed tracks only."""
        for track in tracks:
            if track.real_id is None:
                continue
            pid = track.real_id
            if pid not in self._entries:
                self._entries[pid] = LoiteringEntry(
                    first_seen=track.timestamp,
                    last_seen=track.timestamp,
                    cam_id=track.cam_id,
                    zone_id=track.zone_id,
                )
            else:
                entry = self._entries[pid]
                entry.last_seen = track.timestamp
                entry.zone_id = track.zone_id

    def merge(self, temp_id: int, real_id: int) -> None:
        """Merge a temp entry into its resolved real entry when id_updates arrive."""
        temp_entry = self._entries.pop(temp_id, None)
        if temp_entry is None:
            return
        if real_id in self._entries:
            real_entry = self._entries[real_id]
            real_entry.first_seen = min(real_entry.first_seen, temp_entry.first_seen)
            real_entry.last_seen = max(real_entry.last_seen, temp_entry.last_seen)
        else:
            self._entries[real_id] = temp_entry

    def get_new_loiterers(self) -> list[LoiteringIncident]:
        """Return incidents for confirmed IDs that just crossed the threshold."""
        incidents = []
        for pid, entry in self._entries.items():
            if pid <= 0 or entry.is_loitering:
                continue
            duration = entry.last_seen - entry.first_seen
            if duration >= self.threshold:
                entry.is_loitering = True
                incidents.append(
                    LoiteringIncident(
                        person_id=pid,
                        cam_id=entry.cam_id,
                        first_seen=entry.first_seen,
                        duration=duration,
                        zone_id=entry.zone_id,
                    )
                )
        return incidents

    def evict_stale(self, cutoff: float) -> None:
        """Remove entries not seen since cutoff to bound memory."""
        stale = [pid for pid, e in self._entries.items() if e.last_seen < cutoff]
        for pid in stale:
            del self._entries[pid]
