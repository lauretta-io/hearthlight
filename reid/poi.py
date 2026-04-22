import queue
import logging

from ..shared.constants import STREAM_MESSAGES_PER_FRAME
from ..shared.models.DataModels import POIResult, POISearch
from ..shared.rabbit_messenger import POISearchConsumer

logger = logging.getLogger(__name__)


class POIManager:
    def __init__(self, cfg, reid_module, id_offset: int):
        self.queries = {}
        self.reid_module = reid_module
        self.consumer = POISearchConsumer()

        self.match_threshold = cfg.poi.match_threshold
        self.max_matches = cfg.poi.max_matches
        self.id_offset = id_offset

    def update(self):
        new_queries = self.get_new_queries()
        return [
            POIResult(ids=self.search(query), search_id=query.search_id)
            for query in new_queries
        ]

    def get_new_queries(self) -> list[POISearch]:
        new_queries = []
        for _ in range(STREAM_MESSAGES_PER_FRAME):
            try:
                message = self.consumer.queue.get_nowait()
                if message.search_id in self.queries:
                    if message.feature is not None:
                        logger.error(
                            f"Duplicate POI query with name {message.name}",
                            extra={"task": "POI Manager"},
                        )
                        continue
                    poi_query = self.queries[message.search_id]
                else:
                    if message.feature is None:
                        logger.error(
                            f"POI query with search_id {message.search_id} has no feature",
                            extra={"task": "POI Manager"},
                        )
                        continue
                    poi_query = message
                    self.queries[message.search_id] = poi_query
                new_queries.append(poi_query)
            except queue.Empty:
                break
        return new_queries

    def iter_reid_modules(self):
        if isinstance(self.reid_module, dict):
            return self.reid_module.values()
        return [self.reid_module]

    def search(self, query) -> list[int]:
        all_candidate_ids = []
        for reid_module in self.iter_reid_modules():
            if hasattr(reid_module, "search"):
                candidate_ids = reid_module.search(
                    query.feature,
                    self.max_matches,
                    self.match_threshold,
                )
                all_candidate_ids.extend(candidate_ids)
                continue
            candidate_ids = reid_module.strategy.vectors.get_nearest_ids(
                query.feature,
                self.max_matches,
                self.match_threshold,
            )
            all_candidate_ids.extend(id + self.id_offset for id in candidate_ids)

        deduped = []
        seen = set()
        for candidate_id in all_candidate_ids:
            if candidate_id in seen:
                continue
            seen.add(candidate_id)
            deduped.append(candidate_id)
            if len(deduped) >= self.max_matches:
                break
        return deduped
