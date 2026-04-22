from collections import defaultdict

from ..shared.models.DataModels import JourneyNode


class JourneyTracker:
    def __init__(self, cfg):
        # {clss: {real_id: {cam_id: JourneyNode}}
        self.active_nodes = defaultdict(lambda: defaultdict(dict))
        # {clss: {real_id: {cam_id: last_time_seen}}
        self.last_seen = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        self.completed_nodes = []
        self.time_to_end = cfg.journey.time_to_end
        self.create_on_zone = cfg.journey.create_on_zone

    def update(self, track) -> JourneyNode | None:
        cam_id = track.cam_id
        self.last_seen[track.clss][track.real_id][cam_id] = track.timestamp
        new_node = None
        track_nodes = self.active_nodes[track.clss][track.real_id]
        if cam_id in track_nodes:
            active_node = track_nodes[cam_id]
            if active_node.zone_id != track.zone_id and self.create_on_zone:
                self.completed_nodes.append(active_node)
                new_node = self.create_node(track)
                track_nodes[cam_id] = new_node
            else:
                active_node.stop_timestamp = track.timestamp
        else:
            new_node = self.create_node(track)
            track_nodes[cam_id] = new_node

        return new_node

    def create_node(self, track) -> JourneyNode:
        return JourneyNode(
            track_instance=track,
            start_timestamp=track.timestamp,
            stop_timestamp=track.timestamp,
            cam_id=track.cam_id,
            zone_id=track.zone_id,
        )

    def get_finished_nodes(self, frame_info) -> list[JourneyNode]:
        to_delete = []
        for clss in self.last_seen:
            for real_id in self.last_seen[clss]:
                for cam_id in self.last_seen[clss][real_id]:
                    timestamp = frame_info.get_frame(cam_id).timestamp
                    if timestamp - self.last_seen[clss][real_id][cam_id] > self.time_to_end:
                        self.completed_nodes.append(self.active_nodes[clss][real_id][cam_id])
                        to_delete.append((clss, real_id, cam_id))
        for clss, real_id, cam_id in to_delete:
            del self.last_seen[clss][real_id][cam_id]
            del self.active_nodes[clss][real_id][cam_id]
            if not self.active_nodes[clss][real_id]:
                del self.last_seen[clss][real_id]
                del self.active_nodes[clss][real_id]
        completed_nodes = self.completed_nodes
        self.completed_nodes = []
        return completed_nodes
