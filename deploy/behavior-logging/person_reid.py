"""Appearance-based person IDs for the Office camera group."""

from collections import Counter, defaultdict
from pathlib import Path
import json
import sqlite3
from time import time
from uuid import uuid4

import numpy as np

from rerank import reciprocal_distances
from feature_bank import FeatureBank


def unit_vector(vector):
    vector = np.asarray(vector, dtype=np.float32)
    norm = np.linalg.norm(vector)
    if not np.isfinite(norm) or norm <= 0:
        return None
    return vector / norm


class TransReID:
    key = "transreid-market1501"

    def __init__(self, device, weights):
        import sys

        import torch
        from torchvision.transforms import Compose, InterpolationMode, Normalize, Resize, ToTensor

        upstream = Path("/opt/transreid")
        sys.path.insert(0, str(upstream))
        from config import cfg as defaults
        from model import make_model

        config = defaults.clone()
        config.merge_from_file(str(upstream / "configs/Market/vit_transreid_stride.yml"))
        config.MODEL.PRETRAIN_CHOICE = "none"
        state = torch.load(weights, map_location="cpu", weights_only=True)
        state = {name.removeprefix("module."): tensor for name, tensor in state.items()}
        self.model = make_model(config, state["classifier.weight"].shape[0],
                                state["base.sie_embed"].shape[0], 0)
        self.model.load_state_dict(state)
        self.dtype = torch.float16 if device == "cuda" else torch.float32
        self.device = device
        self.model.to(device=device, dtype=self.dtype).eval()
        self.transform = Compose([
            Resize(config.INPUT.SIZE_TEST, interpolation=InterpolationMode.BICUBIC),
            ToTensor(),
            Normalize(config.INPUT.PIXEL_MEAN, config.INPUT.PIXEL_STD),
        ])

    def embed(self, crops):
        import torch

        usable = [crop for crop in crops if crop.width >= 24 and crop.height >= 48]
        if len(usable) < 2:
            return None
        batch = torch.stack([self.transform(crop) for crop in usable]).to(self.device, self.dtype)
        # Use the same training-camera embedding for every Office camera.
        camera_labels = torch.zeros(len(usable), dtype=torch.long, device=self.device)
        with torch.inference_mode():
            embeddings = self.model(batch, cam_label=camera_labels).float()
            embeddings = torch.nn.functional.normalize(embeddings, dim=1)
        return unit_vector(embeddings.mean(dim=0).cpu().numpy())


class PersonGallery:
    def __init__(self, path, model_key, threshold=0.82, margin=0.05, ttl_seconds=86400,
                 window_seconds=300, window_size=96, prototype_limit=8, relaxed_threshold=.76):
        self.model_key = model_key
        self.threshold = threshold
        self.margin = margin
        self.ttl_seconds = ttl_seconds
        self.window_seconds = window_seconds
        self.window_size = window_size
        path.touch(mode=0o600, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA busy_timeout=1000")
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS people (
                person_id TEXT PRIMARY KEY, model_key TEXT NOT NULL,
                embedding BLOB NOT NULL, last_seen REAL NOT NULL
            )""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS recent_observations (
                person_id TEXT NOT NULL REFERENCES people(person_id) ON DELETE CASCADE,
                embedding BLOB NOT NULL, seen_at REAL NOT NULL
            )""")
            # Durable identity births survive gallery TTL expiry and allow downstream
            # consumers to create people independently of slow VLM inference.
            self.db.execute("""CREATE TABLE IF NOT EXISTS identity_births (
                person_id TEXT PRIMARY KEY, model_key TEXT NOT NULL, created_at REAL NOT NULL
            )""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS track_observations (
                sample_id TEXT NOT NULL, track_id INTEGER NOT NULL, person_id TEXT NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(sample_id, track_id)
            )""")
            self.db.execute("""INSERT OR IGNORE INTO identity_births
                SELECT person_id, model_key, last_seen FROM people""")
        self.db.execute("PRAGMA foreign_keys = ON")
        self.bank = FeatureBank(self.db, limit=prototype_limit, relaxed_threshold=relaxed_threshold, model_key=self.model_key)

    def record_tracks(self, sample, tracks, person_ids):
        """Persist actual detections before the VLM is called, independently of it."""
        with self.db:
            for track_id, (track, person_id) in enumerate(zip(tracks, person_ids, strict=True), 1):
                if person_id is None:
                    continue
                payload = {**sample, "person_id": person_id, "track_id": track_id,
                           "scene_id": sample["sample_id"], "description": None,
                           "analysis_status": "tracking_only",
                           "detections": [{"frame_index": index,
                                           "offset_seconds": index / sample["sample_fps"],
                                           "box_xyxy": list(box)} for index, box in track]}
                self.db.execute("INSERT OR IGNORE INTO track_observations VALUES (?, ?, ?, ?)",
                                (sample["sample_id"], track_id, person_id, json.dumps(payload)))

    def _candidates(self, queries, gallery, recent):
        recent_vectors = defaultdict(list)
        for person_id, vector in recent:
            recent_vectors[person_id].append(vector)

        if hasattr(self,"bank"):
            for person_id,vector,_,_,_ in self.bank.vectors(set(gallery)):
                recent_vectors[person_id].append(vector)
        rankings = []
        for query in queries:
            scores = {person_id: float(query @ vector) for person_id, vector in gallery.items()}
            for person_id, vectors in recent_vectors.items():
                scores[person_id] = max(scores[person_id], float(np.max(np.asarray(vectors) @ query)))
            rankings.append(sorted(((score, person_id) for person_id, score in scores.items()), reverse=True))

        # Only close, plausible matches need reranking. Keep the existing cosine
        # gate, including for any candidate promoted by neighborhood evidence.
        contests = []
        for ranked in rankings:
            if ranked and ranked[0][0] >= self.threshold:
                best = ranked[0][0]
                contests.append([person_id for score, person_id in ranked if best - score < self.margin])
            else:
                contests.append([])
        contenders = {person_id for contest in contests if 1 < len(contest) <= 4 for person_id in contest}
        distances = None
        columns = defaultdict(list)
        if contenders.intersection(recent_vectors):
            if hasattr(self,"bank"):
                bank_context=[(p,v) for p,v,_,_,_ in self.bank.vectors(contenders)]
                recent=list(recent)[:max(0,96-len(bank_context))]+bank_context
            context = list(recent) + [(person_id, gallery[person_id]) for person_id in sorted(contenders)]
            for column, (person_id, _) in enumerate(context):
                columns[person_id].append(column)
            distances = reciprocal_distances(np.stack([*queries, *(vector for _, vector in context)]), len(queries))

        decisions = []
        for index, (ranked, contest) in enumerate(zip(rankings, contests)):
            if not contest:
                decisions.append((None, False, True))
                continue
            if len(contest) == 1:
                decisions.append((contest[0], True, False))
                continue
            winner = contest[0]
            accepted = False
            if distances is not None and len(contest) <= 4 and any(person_id in recent_vectors for person_id in contest):
                refined = sorted((float(distances[index, columns[person_id]].min()), person_id) for person_id in contest)
                winner = refined[0][1]
                scores = {person_id: score for score, person_id in ranked[:len(contest)]}
                tied = any(abs(scores[winner] - scores[other]) < 1e-6
                           for other in contest if other != winner)
                accepted = (not tied and scores[winner] >= self.threshold
                            and refined[1][0] - refined[0][0] >= 0.04)
            decisions.append((winner, accepted, False))
        return decisions

    def assign(self, embeddings, observed_at=None, tracks=None, qualities=None, track_keys=None):
        now = time()
        if qualities is not None:embeddings=[e if qualities[i]>=.3 else None for i,e in enumerate(embeddings)]
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute("DELETE FROM people WHERE last_seen < ?", (now - self.ttl_seconds,))
            self.db.execute("DELETE FROM person_features WHERE person_id NOT IN (SELECT person_id FROM people)")
            gallery = {
                person_id: np.frombuffer(blob, dtype=np.float32)
                for person_id, blob in self.db.execute(
                    "SELECT person_id, embedding FROM people WHERE model_key = ?", (self.model_key,)
                )
            }
            self.db.execute("DELETE FROM recent_observations WHERE seen_at < ?", (now - self.window_seconds,))
            recent = [
                (person_id, np.frombuffer(blob, dtype=np.float32))
                for person_id, blob in self.db.execute("""
                    SELECT r.person_id, r.embedding FROM recent_observations r
                    JOIN people p ON p.person_id = r.person_id WHERE p.model_key = ?
                    ORDER BY r.rowid DESC LIMIT ?
                """, (self.model_key, self.window_size))
            ]
            queries = [embedding for embedding in embeddings if embedding is not None]
            decisions = self._candidates(queries, gallery, recent)
            refined=[]
            for vector,(candidate,accepted,create) in zip(queries,decisions):
                relaxed=self.bank.relaxed_candidate(vector,set(gallery)) if create else None
                refined.append((relaxed,True,False) if relaxed else (candidate,accepted,create))
            decisions=refined
            claims = Counter(person_id for person_id, _, _ in decisions if person_id is not None)
            decision_list=list(decisions)
            by_index=dict(zip([i for i,e in enumerate(embeddings) if e is not None],decision_list))
            decisions = iter(decision_list)
            assignments = []
            for index, embedding in enumerate(embeddings):
                if embedding is None:
                    assignments.append(None)
                    continue
                candidate, accepted, create = next(decisions)
                person_id = None
                if create:
                    person_id = uuid4().hex
                    self.db.execute("INSERT INTO identity_births VALUES (?, ?, ?)",
                                    (person_id, self.model_key, now if observed_at is None else observed_at))
                elif accepted:
                    if claims[candidate] == 1:
                        person_id = candidate
                    elif tracks is not None:
                        involved=[i for i,e in enumerate(embeddings) if e is not None]
                        # Non-overlapping fragments may reuse an ID; simultaneous people may not.
                        own={frame for frame,_ in tracks[index]}
                        competitors=[{frame for frame,_ in tracks[i]} for i in involved if i!=index and by_index[i][0]==candidate]
                        if not any(own.intersection(other) for other in competitors):person_id=candidate

                if person_id is not None:
                    strong=person_id not in gallery or float(embedding@gallery[person_id])>=self.threshold or any(float(embedding@v)>=self.threshold for p,v,_,_,_ in self.bank.vectors({person_id}))
                    centroid = embedding
                    if person_id in gallery:
                        centroid = unit_vector(0.9 * gallery[person_id] + 0.1 * embedding) if strong else gallery[person_id]
                    self.db.execute("""INSERT INTO people VALUES (?, ?, ?, ?)
                        ON CONFLICT(person_id) DO UPDATE SET embedding=excluded.embedding, last_seen=excluded.last_seen
                    """, (person_id, self.model_key, centroid.tobytes(), now))
                    # Relaxed assignments cannot drift the feature bank or neighborhood.
                    if strong:
                        self.bank.observe(person_id,embedding,qualities[index] if qualities else .5,now,track_keys[index] if track_keys else uuid4().hex)
                        self.db.execute("INSERT INTO recent_observations VALUES (?, ?, ?)",(person_id, embedding.tobytes(), now))
                assignments.append(person_id)
            self.db.execute("""DELETE FROM recent_observations WHERE rowid IN (
                SELECT r.rowid FROM recent_observations r JOIN people p ON p.person_id = r.person_id
                WHERE p.model_key = ? ORDER BY r.rowid DESC LIMIT -1 OFFSET ?
            )""", (self.model_key, self.window_size))
            return assignments
