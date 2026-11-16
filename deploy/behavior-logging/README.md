# Headless Office behavior logging

The headless logger runs SigLIP visual matching, YOLOv8n person detection,
TransReID appearance matching, and Qwen3-VL-2B-Instruct scene and item activity
analysis. The local VLM is selected with `BEHAVIOR_VLM_MODEL`. Model revisions
are pinned in `var/behavior-logging/models/checkpoints.json` after loading.
The live VLM uses the evaluated Qwen3 checkpoint with bfloat16 inference.
The [Qwen model card](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct)
describes the upstream checkpoint.

Model Zoo is checked out at `shared/model_zoo`. The runner loads real checkpoints
directly using Transformers. The web and frontend source trees are excluded
using Git sparse checkout. Run `git sparse-checkout disable` to restore them.

## Run

The Dockerfile reuses the existing local `dhs-passenger-detection-ingestor` image
for its CUDA/PyTorch runtime. The logger image pins Transformers 5.7.0 and the
processor dependencies used in the comparison, plus a torchvision build matched
to the base image's PyTorch version.

From the repository root:

```sh
docker compose -f deploy/behavior-logging/compose.yaml build logger
docker compose -f deploy/behavior-logging/compose.yaml run --rm --entrypoint python logger \
  -c 'from ultralytics.utils.downloads import attempt_download_asset; attempt_download_asset("/models/yolov8n.pt")'
docker compose -f deploy/behavior-logging/compose.yaml run --rm logger --smoke-test
(
  cd var/behavior-logging/models
  curl -fL 'https://drive.usercontent.google.com/download?id=11p4RjmpCGGAS-876VEt7OoFrUeHTUlyO&export=download&confirm=t' \
    -o transreid_market1501.pth.tmp &&
  printf '%s  %s\n' '843055293e160da027d152e1b9cccb75e34c73e0a9714204012c0f2825f9c4e5' \
    'transreid_market1501.pth.tmp' | sha256sum -c - &&
  mv transreid_market1501.pth.tmp transreid_market1501.pth
)
docker compose -f deploy/behavior-logging/compose.yaml up -d logger
```

The smoke test uses synthetic images and writes `logs/smoke-test.json`. It is not
recorded as a camera observation. Initial startup downloads weights from their
upstream Hugging Face repositories. Later starts use the cached, pinned revisions.

## Local configuration and results

`var/behavior-logging/cameras.json` is an ignored, owner-only file containing the
three Office camera URLs. Camera credentials are never printed in logger output.
Do not commit this configuration. The logger does not alter camera records or
server networking.

The logger uses the existing Hearthlight ingestor's YOLOv8n detector choice for
person detection. The setup command caches its weights on the local model volume.
Scene logging can run if the detector is unavailable. Check
`person_detector_ready` and `person_analysis_completed` in the cycle status.

The logger samples **16 frames at 2 FPS** from each camera. The first and last
frames span 7.5 seconds. Change `BEHAVIOR_SAMPLE_FRAMES` and `BEHAVIOR_SAMPLE_FPS`
in the Compose environment to adjust coverage. The 30-second interval is a
minimum cycle target. Acquisition and inference can extend the cycle. Each
camera is sampled sequentially, and gaps remain between its samples.
`sample_started_at`, `sampled_at`, `sample_frame_count`, and `sample_fps` identify
sample timing in the logs. Frame offsets are relative to the sampled sequence.
Temporary frames are deleted after sampling. Camera frames remain in memory
for inference and are released afterward.

Under `var/behavior-logging/logs/`:

- `status.json`: loading, ready, logging, waiting for cameras, or inference failed
- `observations.jsonl`: successful model descriptions of actual camera samples
- `scenes.jsonl`: one record for each captured sample, including the JSON input
  track catalog, raw VLM output, scene description, model revision, and status.
- `person-behaviors.jsonl`: individual behavior descriptions linked to
  `scene_id`, `behavior_id`, `track_id`, and resolved `person_id`.
- `people.jsonl`: person track observations with frame indices, boxes in
  sampled-image pixels, behavior descriptions and analysis status. Join to scene
  observations on `scene_id` / `sample_id`.
- `activities.jsonl`: validated item activity events with person and track IDs,
  action, item description, frame range, evidence text, model revision, and
  possession observation. Join through `sample_id` and `track_id`.
- `person-activities.sqlite3`: authoritative scene and person history, item
  events in `activities`, and last observed item associations in `person_items`.
  JSONL publication follows the database commit. History survives restarts and
  has no automatic retention limit.
- `person_interactions` in that database: immutable item-handling, object-use,
  and person-interaction evidence. `person_state_evidence` exposes clear,
  attributed observations, including incoming interactions for the counterpart.
- `operations.jsonl`: startup, input availability, and inference failures
- `person-snapshots/`: cropped JPEG representatives for identified people.
  Files are isolated per person/camera; only the current and previous committed
  representatives are kept per association. These are not a video archive.
- `person-clips/`: MP4 clips of the actual sampled frames when an identified
  person is visible, plus a preview JPEG. Each clip is shared by the people in
  that camera sample. Encoding uses one CPU thread and adds no VLM work. Clips
  retain the configured sample FPS, so they are sampled footage rather than a
  continuous recording. `BEHAVIOR_CLIP_RETENTION_HOURS` defaults to 0, preserving
  clips until manually deleted. Set a positive value only for an approved expiry
  period. Camera/scene references remain in SQLite after a video expires.
  This deployment uses the user's selected 120-hour (five-day) retention period.
- `smoke-test.json`: results for synthetic input only

Each `track_id` is scoped to one sample. Tracks use unambiguous bounding-box
overlap between adjacent frames. Occlusion, fast movement, and people crossing
can fragment tracks or produce incorrect links. Single-frame tracks can receive
visible-behavior descriptions. Their Re-ID may remain unresolved. Track IDs expire at the end of the sample and are independent
across cameras.

The [TransReID Market-1501 checkpoint](https://github.com/damo-cv/TransReID#trained-models-and-logs-size-256)
uses body appearance to assign a separate `person_id` across all Office cameras.
IDs and embeddings persist across container restarts in the owner-only
`logs/person-gallery.sqlite3` database. The gallery expires an ID after 24 hours
without a match and prunes expired embeddings during sample processing. Existing
JSONL entries retain their recorded IDs under the normal log rotation policy.
The logger emits a null `person_id` for tracks with fewer than two usable crops,
competing matches, or unavailable Re-ID. Check `person_reid_ready` in cycle
status.

The logger assigns IDs as each clip arrives. For close cosine matches, it
reranks candidates using k-reciprocal neighbors, blending 70% weighted Jaccard
distance with 30% cosine distance. Its shared window covers up to 96 assigned
track embeddings from the last five minutes across all Office cameras. The
window persists across container restarts, and older matches can still use the
24-hour ID gallery. Reranking requires recent evidence for a contender and
retains the cosine threshold and one-ID-per-clip rule. Existing log entries
keep their assigned IDs. Check `person_reid_mode` in cycle status.

Appearance matches can split or merge people incorrectly, especially
when clothing, viewpoint, or lighting changes. Existing log entries lack the
image crops needed to assign an ID retroactively.

## Linked scene and person history

Detection and Re-ID run before the joint VLM request. Every sampled frame is
annotated with numbered person boxes. The input JSON identifies each track,
its resolved person ID, and the original frame indices, time offsets, and boxes
where that person was detected. Re-ID uses the original images.

The VLM returns a `scene_description` and a `persons` list. Each person report
contains the supplied `track_id`, a visible-behavior `description`, and optional
item `events`. Server-side code resolves the returned track IDs through the
input catalog. Unknown track IDs are rejected, duplicates invalidate the
colliding report, and an omitted person receives an explicit `omitted` row.
Valid descriptions with invalid item events receive `partial` status and create
no item possession update. Unresolved identities have a null `person_id`.

The database provides these tables and views.

- `scene_descriptions` stores one scene row per captured sample, keyed by
  `scene_id` (the sample ID), with camera, time, model, description, status and
  a JSON payload containing the request and raw response. Failed inference and
  invalid responses also produce rows with their explicit statuses.
- `persons` stores resolved person IDs and first/last observation timestamps.
- `scene_persons` links every detected track to its scene and resolved person ID,
  with frame-by-frame detections in `detections_json`.
- `person_behaviors` stores each track's individual description and status,
  keyed by `behavior_id` and linked to its scene and person ID.
- `person_scene_history` lists the scenes in which a given person appears.
- `person_behavior_history` combines each person's behavior with the scene
  description, camera and observation time.

All scene rows, identity links, behavior rows and item events for a sample commit
in one SQLite transaction. Retrying the same sample ID preserves the original
record without duplicates. Legacy item events continue to be available in
`activities`. The linked scene/person tables start with joint inference.

Example queries for an identified person follow.

```sql
SELECT observed_at, camera_name, scene_id, scene_description, analysis_status
FROM person_scene_history
WHERE person_id = 'PERSON_ID'
ORDER BY observed_at;

SELECT observed_at, camera_name, behavior_description, scene_description,
       analysis_status, scene_id, track_id
FROM person_behavior_history
WHERE person_id = 'PERSON_ID'
ORDER BY observed_at;
```

The `history.py` command reads this database in read-only mode and returns JSON.
It supports `scenes`, `behaviors`, and `persons` collections, with `--person-id`,
`--scene-id`, `--camera-id`, `--since`, `--until`, `--limit`, and `--offset` filters.
Results are ordered newest first. The default limit is 20, and `next_offset`
indicates another page. Freeze an `--until` bound while paging an active history
to keep new samples outside the result set. Time filters accept ISO-8601 values,
including offsets. A timestamp without an offset is interpreted as UTC.
`--since` is inclusive and `--until` is exclusive.

```sh
# Latest saved scenes.
docker exec hearthlight-behavior-logger-1 python /opt/behavior/history.py scenes --limit 3

# Discover person IDs with stored history.
docker exec hearthlight-behavior-logger-1 python /opt/behavior/history.py persons

# Retrieve a person's behaviors together with their scene descriptions.
docker exec hearthlight-behavior-logger-1 python /opt/behavior/history.py behaviors --person-id PERSON_ID

# Retrieve the scenes in which that person was detected.
docker exec hearthlight-behavior-logger-1 python /opt/behavior/history.py scenes --person-id PERSON_ID

# Run directly on the host with its database path.
python deploy/behavior-logging/history.py scenes --limit 1 \
  --db var/behavior-logging/logs/person-activities.sqlite3
```

The database resides on the Compose bind mount at
`var/behavior-logging/logs/person-activities.sqlite3`, so replacing or restarting
the logger container reuses its committed history. Retrieval opens the existing
file with SQLite `mode=ro`. Querying a missing file returns an error.

The history follows the sampled clips. The sampling gaps described above apply
to this timeline. Scene descriptions are observations of their own sample.

## Item activity and possession observations

Item events refer to the original frame indices of the specified person track.
Reported actions include pickup, holding, carrying, putting down, placing into
or removing from a bag, giving, and receiving. Transitions require distinct
valid frame indices and different input frames. These checks reject structurally
unsupported outputs. Every `people.jsonl` row records `activity_status` and the
raw joint VLM response so invalid results can be investigated.

A clear VLM attribution and a resolved `person_id` are required to update a
person's item association. The resulting `possession_status` is
`observed_with_person`, `observed_in_bag`, `observed_released`, or `unclear`.
Frame references and `start_offset_seconds` / `end_offset_seconds` connect the
event to the sampled sequence. The local database keeps the most recent state,
its observation time, and whether a subsequent valid sample observed the item.
Read the timestamps when assessing how recent an association is.

An `item_id` groups matching item descriptions for one person. Its scope is
`person_and_description`. Appearance changes can split a group, and identical
items can share a group. Physical item identity across people requires further
object tracking. A give event records the observed release by the target person.
A receive event records the receiving person's separate association.

JSONL logs rotate at 10 MB with four backups per log. Activity and possession
records are VLM estimates and can be incorrect. The item activity database and
JSONL logs provide the underlying observations for review. Model output cannot
establish ownership, intent, or a crime.

The status `waiting_for_cameras` means models are ready but no camera samples
could be analyzed. It does not mean behavior logging has succeeded.

```sh
cat var/behavior-logging/logs/status.json
tail -f var/behavior-logging/logs/operations.jsonl
tail -f var/behavior-logging/logs/observations.jsonl
docker compose -f deploy/behavior-logging/compose.yaml stop logger
```


## Delos person synchronization

The ReID gallery database now keeps durable `identity_births` records. Gallery TTL
expiry does not remove these records. Actual detected track frames are saved to
`track_observations` before the VLM runs. Delos reads these records through a
read-only mount and automatically creates its own person and internal source-ID
mapping, then links scene, behavior and activity evidence to that person.
Delos applies its one-hour provisional-person qualification policy independently
of the ReID gallery TTL. Births and tracking records are replayable and are not
rotated with JSONL logs.

## Rebuild and recover

See [recovery/README.md](recovery/README.md) for pinned model download references,
checksums, source dependencies and sanitized static configuration.
