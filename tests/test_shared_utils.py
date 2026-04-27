import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

from shared.constants import Tasks
from shared.constants import DetectorClasses
from shared.utils.backoff import with_exponential_backoff
from shared.utils.backpressure import summarize_queue_backpressure
from shared.utils.config import get_tasks
from shared.utils.dependency_health import (
    get_unhealthy_dependencies,
    normalize_dependency_status,
)
from shared.utils.input_sources import (
    build_runtime_camera_map,
    build_upload_filename,
    coerce_source_value,
    derive_source_error,
    derive_upload_lifecycle_state,
    format_supported_video_extensions,
    probe_source_connection,
    validate_uploaded_video_file,
)
from shared.utils.logger import (
    get_bootstrap_log_dir,
    get_run_log_dir,
    set_bootstrap_logging,
)
from shared.utils.micro_batch import build_asset_reference, build_micro_batch_envelope
from shared.utils.monitoring_feed import (
    build_feed_endpoint_catalog,
    infer_run_status,
    normalize_feed_limit,
    parse_serialized_json,
)
from shared.utils.resource_monitor import collect_resource_snapshot, evaluate_admission
from shared.utils.resource_drift import build_resource_drift
from shared.utils.runtime_guard import (
    get_dead_thread_names,
    get_missing_frame_failure_reason,
    should_fail_for_missing_frames,
)
from shared.utils.security import (
    is_valid_incident_status_transition,
    resolve_safe_child_path,
    sanitize_identifier,
)
from shared.utils.timer import LoopTimer
from shared.constants import IncidentStatus
from shared.utils.system_state import derive_system_status, get_error_modules, SystemStatus
from shared.utils.docker_cli import build_docker_env, find_docker_binary
from shared.utils.threading import collect_live_thread_names
from shared.utils.time_utils import seconds_since_datetime

try:
    from association.manager_classes import IncidentManager
except ModuleNotFoundError:
    IncidentManager = None

try:
    from shared.utils.model_registry import (
        MODEL_STAGE_DETECTOR,
        MODEL_STAGE_TRACKER,
        build_model_option_catalog,
        build_model_display_name,
        build_default_bindings,
        build_runtime_binding_block,
        load_registry_bundle,
        resolve_tracker_name,
        validate_source_bindings,
    )
except ModuleNotFoundError:
    MODEL_STAGE_DETECTOR = None
    MODEL_STAGE_TRACKER = None
    build_model_option_catalog = None
    build_model_display_name = None
    build_default_bindings = None
    build_runtime_binding_block = None
    load_registry_bundle = None
    resolve_tracker_name = None
    validate_source_bindings = None


class BackoffTests(unittest.TestCase):
    def test_retries_until_success(self):
        attempts = {"count": 0}

        @with_exponential_backoff(max_tries=4, exceptions=ValueError, base_delay=0.5)
        def flaky():
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise ValueError("temporary")
            return "ok"

        with patch("shared.utils.backoff.time.sleep") as sleep, patch(
            "shared.utils.backoff.logger.warning"
        ):
            result = flaky()

        self.assertEqual(result, "ok")
        self.assertEqual(attempts["count"], 3)
        self.assertEqual(sleep.call_args_list, [((0.5,),), ((1.0,),)])

    def test_raises_after_max_retries(self):
        @with_exponential_backoff(max_tries=3, exceptions=ValueError, base_delay=0.25)
        def always_fails():
            raise ValueError("still failing")

        with patch("shared.utils.backoff.time.sleep") as sleep, patch(
            "shared.utils.backoff.logger.warning"
        ), patch("shared.utils.backoff.logger.exception"):
            with self.assertRaises(ValueError):
                always_fails()

        self.assertEqual(sleep.call_args_list, [((0.25,),), ((0.5,),)])


class TimerTests(unittest.TestCase):
    def test_time_records_elapsed_duration(self):
        timer = LoopTimer()

        with patch(
            "shared.utils.timer.time_synchronized",
            side_effect=[100.0, 101.5, 103.0, 104.0],
        ):
            timer.start()
            elapsed = timer.time("detect")
            timer.loop()

        self.assertEqual(elapsed, 1.5)
        self.assertEqual(timer.timings["detect"], 1.5)
        self.assertEqual(timer.count, 1)
        self.assertEqual(timer.total_count, 1)

    def test_report_logs_expected_summary(self):
        logger = Mock()
        timer = LoopTimer(logger=logger, task="TEST", abbrev="t")
        timer.start_time = 0.0
        timer.last_time = 2.0
        timer.count = 4
        timer.total_count = 4
        timer.timings["detect"] = 1.0
        timer.timings["fetch"] = 0.5

        timer.report(reset=False)

        logger.debug.assert_called_once()
        report = logger.debug.call_args[0][0]
        self.assertIn("t Frame ID: 4", report)
        self.assertIn("FPS: 2.0", report)
        self.assertIn("detect: 250ms", report)
        self.assertIn("fetch: 125ms", report)
        self.assertEqual(logger.debug.call_args.kwargs["extra"], {"task": "TEST"})


class ConfigTests(unittest.TestCase):
    def test_get_tasks_adds_poi_when_person_enabled(self):
        cfg = SimpleNamespace(
            input=SimpleNamespace(
                cameras={
                    "cam-1": {"tasks": [Tasks.PERSON, Tasks.BAG]},
                    "cam-2": {"tasks": [Tasks.GUN]},
                }
            )
        )

        tasks = get_tasks(cfg)

        self.assertEqual(tasks, {Tasks.PERSON, Tasks.BAG, Tasks.POI})

    def test_get_tasks_warns_on_unknown_tasks(self):
        cfg = SimpleNamespace(
            input=SimpleNamespace(
                cameras={
                    "cam-1": {"tasks": ["person", "unknown-task"]},
                    "cam-2": {},
                }
            )
        )

        with patch("shared.utils.config.logging.warning") as warning:
            tasks = get_tasks(cfg)

        self.assertEqual(tasks, {Tasks.PERSON, Tasks.POI, "UNKNOWN-TASK"})
        warning.assert_called_once_with("Unknown task %s for %s", "UNKNOWN-TASK", "camera cam-1")


class LoggerTests(unittest.TestCase):
    def test_bootstrap_logging_uses_separate_directory(self):
        cfg = SimpleNamespace(
            logging={
                "level": "INFO",
                "log_dir": "shared/output/logs/run-123",
                "bootstrap_log_dir": "shared/output/bootstrap_logs",
            }
        )

        self.assertEqual(get_run_log_dir(cfg), "shared/output/logs/run-123")
        self.assertEqual(get_bootstrap_log_dir(cfg), "shared/output/bootstrap_logs")

        with patch("shared.utils.logger.configure_logging") as configure_logging:
            set_bootstrap_logging(cfg, "INGESTOR")

        configure_logging.assert_called_once_with(
            "INFO",
            "shared/output/bootstrap_logs",
            "INGESTOR",
        )


class TimeUtilsTests(unittest.TestCase):
    def test_seconds_since_datetime_uses_elapsed_seconds(self):
        timestamp = datetime(2026, 3, 14, 12, 0, 0, tzinfo=timezone.utc)
        now = datetime(2026, 3, 14, 12, 1, 5, tzinfo=timezone.utc)

        self.assertEqual(seconds_since_datetime(timestamp, now=now), 65)

    def test_seconds_since_datetime_clamps_future_timestamps(self):
        timestamp = datetime(2026, 3, 14, 12, 2, 0, tzinfo=timezone.utc)
        now = datetime(2026, 3, 14, 12, 1, 5, tzinfo=timezone.utc)

        self.assertEqual(seconds_since_datetime(timestamp, now=now), 0)


class IncidentManagerTests(unittest.TestCase):
    @unittest.skipIf(IncidentManager is None, "association test dependencies are not installed")
    def test_confirmed_incident_is_not_auto_resolved(self):
        manager = IncidentManager(SimpleNamespace())
        incident = SimpleNamespace(
            id=101,
            resolved=False,
            status=IncidentStatus.UNCONFIRMED,
            incident_type="GUN",
            entities=SimpleNamespace(
                entities=[SimpleNamespace(id=7, clss=DetectorClasses.PERSON)],
                roles={7: "GUNMAN"},
            ),
        )

        manager.update([incident], [])
        manager.update(
            [],
            [
                SimpleNamespace(
                    incident_id=101,
                    status=IncidentStatus.CONFIRMED,
                )
            ],
        )
        incident.resolved = True

        system_resolutions = manager.update([], [])

        self.assertEqual(system_resolutions, [])
        self.assertIn(101, manager.incidents)
        self.assertEqual(manager.incidents[101].status, IncidentStatus.CONFIRMED)
        self.assertFalse(manager.incidents[101].resolved)

    @unittest.skipIf(IncidentManager is None, "association test dependencies are not installed")
    def test_unconfirmed_incident_still_auto_resolves(self):
        manager = IncidentManager(SimpleNamespace())
        incident = SimpleNamespace(
            id=202,
            resolved=False,
            status=IncidentStatus.UNCONFIRMED,
            incident_type="GUN",
            entities=SimpleNamespace(
                entities=[SimpleNamespace(id=8, clss=DetectorClasses.PERSON)],
                roles={8: "GUNMAN"},
            ),
        )

        manager.update([incident], [])
        incident.resolved = True

        system_resolutions = manager.update([], [])

        self.assertEqual([item.id for item in system_resolutions], [202])
        self.assertNotIn(202, manager.incidents)


class BackpressureTests(unittest.TestCase):
    def test_summarize_queue_backpressure_reports_warning(self):
        self.assertEqual(
            summarize_queue_backpressure(
                {"consumer": 2, "output_thread": 15},
                warn_threshold=10,
                error_threshold=25,
            ),
            {
                "state": "warning",
                "max_queue_depth": 15,
                "hottest_queue": "output_thread",
                "queue_depths": {"consumer": 2, "output_thread": 15},
            },
        )

    def test_summarize_queue_backpressure_reports_error(self):
        self.assertEqual(
            summarize_queue_backpressure(
                {"consumer": 51},
                warn_threshold=10,
                error_threshold=50,
            )["state"],
            "error",
        )


class SecurityTests(unittest.TestCase):
    def test_sanitize_identifier_strips_unsafe_characters(self):
        self.assertEqual(sanitize_identifier("../Jane Doe??"), "Jane_Doe")

    def test_sanitize_identifier_uses_fallback_for_empty_values(self):
        self.assertEqual(sanitize_identifier("///", fallback="poi"), "poi")

    def test_resolve_safe_child_path_stays_under_base_directory(self):
        path = resolve_safe_child_path("/tmp/poi_crops", "../../Alice Smith")
        expected = Path("/tmp/poi_crops/Alice_Smith").resolve()
        self.assertEqual(path, expected)

    def test_valid_incident_status_transition(self):
        self.assertTrue(
            is_valid_incident_status_transition(
                IncidentStatus.UNCONFIRMED, IncidentStatus.CONFIRMED
            )
        )

    def test_invalid_incident_status_transition(self):
        self.assertFalse(
            is_valid_incident_status_transition(
                IncidentStatus.RESOLVED, IncidentStatus.IN_PROGRESS
            )
        )


class InputSourceUtilsTests(unittest.TestCase):
    def test_build_upload_filename_preserves_extension_and_adds_suffix(self):
        filename = build_upload_filename("Lobby Camera.MP4")
        self.assertTrue(filename.endswith(".mp4"))
        stem, suffix = filename.rsplit("_", 1)
        self.assertEqual(stem, "Lobby_Camera")
        UUID(suffix.removesuffix(".mp4"))

    def test_coerce_source_value_for_webcam(self):
        self.assertEqual(coerce_source_value("webcam", "2"), 2)

    def test_build_runtime_camera_map_uses_upload_paths(self):
        source_rows = [
            SimpleNamespace(
                id=10,
                label="North Gate",
                tasks=["PERSON"],
                kind="camera_url",
                source_value="rtsp://north",
                upload_id=None,
            ),
            SimpleNamespace(
                id=11,
                label="Uploaded Clip",
                tasks=["BAG"],
                kind="video_upload",
                source_value=None,
                upload_id=7,
            ),
        ]

        camera_map = build_runtime_camera_map(source_rows, {7: "/tmp/clip.mp4"})

        self.assertEqual(camera_map[0]["source"], "rtsp://north")
        self.assertEqual(camera_map[0]["source_template_id"], 10)
        self.assertEqual(camera_map[1]["source"], "/tmp/clip.mp4")
        self.assertEqual(camera_map[1]["upload_id"], 7)

    def test_derive_upload_lifecycle_state_prioritizes_active_and_deleted(self):
        self.assertEqual(
            derive_upload_lifecycle_state(
                is_deleted=False,
                is_attached=True,
                is_enabled=True,
            ),
            "active",
        )
        self.assertEqual(
            derive_upload_lifecycle_state(
                is_deleted=True,
                is_attached=True,
                is_enabled=True,
            ),
            "deleted",
        )

    def test_derive_source_error_reports_missing_uploaded_file(self):
        self.assertEqual(
            derive_source_error(
                kind="video_upload",
                enabled=True,
                upload_id=2,
                upload_path="/tmp/missing.mp4",
                upload_exists=False,
                upload_lifecycle_state="attached",
            ),
            "uploaded media file is missing on disk",
        )

    def test_derive_source_error_ignores_non_video_sources(self):
        self.assertIsNone(
            derive_source_error(
                kind="camera_url",
                enabled=True,
                upload_id=None,
                upload_path=None,
                upload_exists=False,
                upload_lifecycle_state=None,
            )
        )

    def test_validate_uploaded_video_file_accepts_supported_extension(self):
        self.assertIsNone(validate_uploaded_video_file("clip.mp4", "video/mp4"))

    def test_validate_uploaded_video_file_rejects_unsupported_extension(self):
        error = validate_uploaded_video_file("clip.txt", "text/plain")
        self.assertEqual(
            error,
            "unsupported video type '.txt'. "
            f"Supported types: {format_supported_video_extensions()}",
        )

    def test_validate_uploaded_video_file_rejects_non_video_content_type(self):
        error = validate_uploaded_video_file("clip.mp4", "text/plain")
        self.assertEqual(
            error,
            "uploaded file content type 'text/plain' is not a video. "
            f"Supported types: {format_supported_video_extensions()}",
        )

    def test_probe_source_connection_reports_open_failure(self):
        class FakeCapture:
            def open(self, source, *_args):
                self.source = source
                return False

            def isOpened(self):
                return False

            def release(self):
                self.released = True

        error = probe_source_connection(
            "camera_url",
            "rtsp://north-gate",
            capture_factory=FakeCapture,
        )

        self.assertEqual(error, "source could not be opened")

    def test_probe_source_connection_reports_missing_frames(self):
        class FakeCapture:
            def open(self, source, *_args):
                self.source = source
                return True

            def isOpened(self):
                return True

            def read(self):
                return False, None

            def release(self):
                self.released = True

        error = probe_source_connection(
            "webcam",
            0,
            capture_factory=FakeCapture,
        )

        self.assertEqual(error, "source opened but did not yield a frame")

    def test_probe_source_connection_accepts_valid_source(self):
        class FakeCapture:
            def open(self, source, *_args):
                self.source = source
                return True

            def isOpened(self):
                return True

            def read(self):
                return True, object()

            def release(self):
                self.released = True

        error = probe_source_connection(
            "camera_url",
            "rtsp://north-gate",
            capture_factory=FakeCapture,
        )

        self.assertIsNone(error)


class ResourceMonitorTests(unittest.TestCase):
    def test_collect_resource_snapshot_works_without_psutil(self):
        with patch("shared.utils.resource_monitor.psutil", None), patch(
            "shared.utils.resource_monitor.collect_gpu_metrics", return_value=[]
        ), patch(
            "shared.utils.resource_monitor.shutil.disk_usage",
            return_value=(100, 25, 75),
        ):
            snapshot = collect_resource_snapshot({"INGESTOR": "idle"}, disk_path=".")

        self.assertEqual(snapshot["disk_percent"], 25.0)
        self.assertEqual(snapshot["module_status"]["WEBAPP"], "running")
        self.assertEqual(snapshot["module_status"]["INGESTOR"], "idle")

    def test_evaluate_admission_blocks_missing_sources(self):
        admission = evaluate_admission(
            {"cpu_percent": 10.0, "memory_percent": 10.0, "disk_percent": 10.0, "gpus": []},
            requires_gpu=False,
            enabled_source_count=0,
            module_status={"INGESTOR": "idle"},
        )
        self.assertFalse(admission["allowed"])

    def test_evaluate_admission_blocks_when_gpu_required_and_missing(self):
        admission = evaluate_admission(
            {"cpu_percent": 10.0, "memory_percent": 10.0, "disk_percent": 10.0, "gpus": []},
            requires_gpu=True,
            enabled_source_count=1,
            module_status={"INGESTOR": "idle"},
        )
        self.assertFalse(admission["allowed"])

    def test_evaluate_admission_allows_healthy_snapshot(self):
        admission = evaluate_admission(
            {
                "cpu_percent": 10.0,
                "memory_percent": 20.0,
                "disk_percent": 30.0,
                "gpus": [{"index": 0, "utilization_percent": 20.0, "memory_used_mb": 100.0, "memory_total_mb": 1000.0}],
                "dependency_status": {
                    "database": {"status": "ok", "detail": None},
                    "rabbitmq": {"status": "ok", "detail": None},
                },
            },
            requires_gpu=False,
            enabled_source_count=2,
            module_status={"INGESTOR": "running"},
        )
        self.assertTrue(admission["allowed"])

    def test_evaluate_admission_blocks_unhealthy_dependencies(self):
        admission = evaluate_admission(
            {
                "cpu_percent": 10.0,
                "memory_percent": 20.0,
                "disk_percent": 30.0,
                "gpus": [],
                "dependency_status": {
                    "database": {"status": "error", "detail": "connection refused"},
                },
            },
            requires_gpu=False,
            enabled_source_count=1,
            module_status={"INGESTOR": "running"},
        )
        self.assertFalse(admission["allowed"])
        self.assertEqual(admission["reason"], "database: connection refused")


class ResourceDriftTests(unittest.TestCase):
    def test_build_resource_drift_marks_baseline_without_previous_snapshot(self):
        drift = build_resource_drift({"cpu_percent": 10.0, "memory_percent": 20.0}, None)

        self.assertEqual(drift["state"], "baseline")
        self.assertEqual(drift["alerts"], [])

    def test_build_resource_drift_reports_memory_alert(self):
        drift = build_resource_drift(
            {
                "cpu_percent": 15.0,
                "memory_percent": 65.0,
                "disk_percent": 20.0,
                "gpus": [],
            },
            {
                "cpu_percent": 10.0,
                "memory_percent": 40.0,
                "disk_percent": 19.0,
                "gpus": [],
            },
            thresholds={"memory_percent_delta": 10.0},
        )

        self.assertEqual(drift["state"], "warning")
        self.assertIn("memory usage drift exceeds threshold", drift["alerts"])


class DependencyHealthTests(unittest.TestCase):
    def test_normalize_dependency_status_formats_healthchecks(self):
        self.assertEqual(
            normalize_dependency_status(
                {
                    "database": (True, None),
                    "rabbitmq": (False, "connection refused"),
                }
            ),
            {
                "database": {"status": "ok", "detail": None},
                "rabbitmq": {"status": "error", "detail": "connection refused"},
            },
        )

    def test_get_unhealthy_dependencies_returns_human_readable_messages(self):
        self.assertEqual(
            get_unhealthy_dependencies(
                {
                    "database": {"status": "error", "detail": "connection refused"},
                    "rabbitmq": {"status": "ok", "detail": None},
                    "ffmpeg": {"status": "error", "detail": "binary not found"},
                }
            ),
            ["database: connection refused", "ffmpeg: binary not found"],
        )


class RuntimeGuardTests(unittest.TestCase):
    def test_should_fail_for_missing_frames_after_timeout(self):
        self.assertTrue(
            should_fail_for_missing_frames(
                last_frame_received_at=10.0,
                now=26.0,
                timeout_seconds=15.0,
            )
        )

    def test_should_not_fail_for_missing_frames_without_timeout(self):
        self.assertFalse(
            should_fail_for_missing_frames(
                last_frame_received_at=10.0,
                now=24.9,
                timeout_seconds=15.0,
            )
        )

    def test_get_missing_frame_failure_reason_uses_thread_state(self):
        self.assertIn(
            "stopped unexpectedly",
            get_missing_frame_failure_reason(
                frames_thread_alive=False,
                timeout_seconds=15.0,
            ),
        )

    def test_get_dead_thread_names_returns_only_stopped_threads(self):
        stop_event = Event()

        def wait_for_stop():
            stop_event.wait()

        alive_thread = Thread(target=wait_for_stop, name="alive-thread")
        dead_thread = Thread(target=lambda: None, name="dead-thread")
        alive_thread.start()
        dead_thread.start()
        dead_thread.join(timeout=2)
        try:
            self.assertEqual(
                get_dead_thread_names(
                    {
                        "alive": alive_thread,
                        "dead": dead_thread,
                    }
                ),
                ["dead"],
            )
        finally:
            stop_event.set()
            alive_thread.join(timeout=2)
        self.assertIn(
            "15.0 seconds",
            get_missing_frame_failure_reason(
                frames_thread_alive=True,
                timeout_seconds=15.0,
            ),
        )


class SystemStateTests(unittest.TestCase):
    def test_derive_system_status_reports_error(self):
        status, reset = derive_system_status(
            SystemStatus.RUNNING,
            ["running", "error"],
        )
        self.assertEqual(status, SystemStatus.ERROR)
        self.assertFalse(reset)

    def test_derive_system_status_becomes_running_when_all_modules_running(self):
        status, reset = derive_system_status(
            SystemStatus.INITIALIZING,
            ["running", "running", "running"],
        )
        self.assertEqual(status, SystemStatus.RUNNING)
        self.assertFalse(reset)

    def test_derive_system_status_becomes_idle_when_stop_completes(self):
        status, reset = derive_system_status(
            SystemStatus.STOPPING,
            ["idle", "idle", "idle"],
        )
        self.assertEqual(status, SystemStatus.IDLE)
        self.assertTrue(reset)

    def test_get_error_modules_returns_sorted_module_names(self):
        errors = get_error_modules(
            {
                "REID": "error",
                "INGESTOR": "running",
                "ASSOCIATION": "error",
            }
        )
        self.assertEqual(errors, ["ASSOCIATION", "REID"])


class MonitoringFeedTests(unittest.TestCase):
    def test_normalize_feed_limit_clamps_bounds(self):
        self.assertEqual(normalize_feed_limit(None), 25)
        self.assertEqual(normalize_feed_limit(0), 1)
        self.assertEqual(normalize_feed_limit(999), 200)

    def test_parse_serialized_json_handles_invalid_values(self):
        self.assertEqual(parse_serialized_json('{"ok": true}'), {"ok": True})
        self.assertIsNone(parse_serialized_json("{not-json"))

    def test_infer_run_status_marks_non_current_runs_completed(self):
        self.assertEqual(
            infer_run_status(
                "run-2",
                current_run_id="run-1",
                system_status="running",
            ),
            "completed",
        )
        self.assertEqual(
            infer_run_status(
                "run-1",
                current_run_id="run-1",
                system_status="running",
            ),
            "running",
        )

    def test_build_feed_endpoint_catalog_contains_algorithm_feed(self):
        catalog = build_feed_endpoint_catalog()
        self.assertTrue(any(item["path"] == "/feeds/algorithm" for item in catalog))


class ModelRegistryTests(unittest.TestCase):
    @unittest.skipIf(load_registry_bundle is None, "omegaconf is not installed")
    def test_registry_bundle_exposes_default_stage_bindings(self):
        bundle = load_registry_bundle()

        defaults = build_default_bindings(bundle)

        self.assertIn(MODEL_STAGE_DETECTOR, defaults)
        self.assertIn(MODEL_STAGE_TRACKER, defaults)
        self.assertEqual(defaults[MODEL_STAGE_DETECTOR], "builtin_yolox_s_cpu")
        self.assertEqual(
            bundle["models"]["anomaly_stage_1"]["heuristic_presence_stage_1"]["healthcheck"]["import_path"],
            "hearthlight_model_zoo.anomaly_detectors",
        )

    @unittest.skipIf(load_registry_bundle is None, "omegaconf is not installed")
    def test_registry_bundle_falls_back_to_cpu_detector_when_gpu_is_unavailable(self):
        bundle = load_registry_bundle()

        defaults = build_default_bindings(bundle, has_gpu=False)

        self.assertEqual(defaults[MODEL_STAGE_DETECTOR], "builtin_yolox_s_cpu")

    @unittest.skipIf(build_model_display_name is None, "omegaconf is not installed")
    def test_build_model_display_name_humanizes_common_models(self):
        self.assertEqual(
            build_model_display_name(
                "detector",
                "builtin_yolox_s_cpu",
                {"artifact_ref": "yolox-s", "adapter": "yolox_detector", "runtime": {}},
            ),
            "YOLOX Small",
        )
        self.assertEqual(
            build_model_display_name(
                "tracker",
                "builtin_bytetrack",
                {
                    "artifact_ref": "bytetrack",
                    "adapter": "bytetrack_tracker",
                    "runtime": {"tracker_name": "bytetrack"},
                },
            ),
            "ByteTrack",
        )
        self.assertEqual(
            build_model_display_name(
                "reid",
                "builtin_transreid_person_hybrid_bag",
                {
                    "artifact_ref": "transreid-person-hybrid-bag",
                    "adapter": "transreid_person_hybrid_bag",
                    "runtime": {},
                },
            ),
            "TransReID Person + Hybrid Bag",
        )
        self.assertEqual(
            build_model_display_name(
                "anomaly_stage_1",
                "heuristic_presence_stage_1",
                {
                    "artifact_ref": "heuristic-presence-stage-1",
                    "adapter": "heuristic_presence_stage_1",
                    "runtime": {},
                },
            ),
            "Heuristic Presence Stage 1",
        )
        self.assertEqual(
            build_model_display_name(
                "anomaly_stage_2",
                "prompt_rules_stage_2",
                {
                    "artifact_ref": "prompt-rules-stage-2",
                    "adapter": "prompt_rules_stage_2",
                    "runtime": {},
                },
            ),
            "Prompt Rules Stage 2",
        )

    @unittest.skipIf(build_model_option_catalog is None, "omegaconf is not installed")
    def test_build_model_option_catalog_enriches_detector_classes_from_model_zoo_artifacts(self):
        catalog = build_model_option_catalog(load_registry_bundle())
        detector_stage = next(entry for entry in catalog["stages"] if entry["stage"] == "detector")
        yolox_option = next(
            option for option in detector_stage["options"] if option["model_key"] == "builtin_yolox_s_cpu"
        )
        self.assertEqual(
            yolox_option["capabilities"].get("classes"),
            ["person", "backpack", "handbag", "suitcase"],
        )

    @unittest.skipIf(load_registry_bundle is None, "omegaconf is not installed")
    def test_load_model_registries_merges_upstream_master_with_local_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "shared.utils.model_registry._load_upstream_master_catalog",
            return_value={
                "models": {
                    "tracker": {
                        "builtin_botsort": {
                            "runtime": {"tracker_name": "botsort"},
                            "artifact_ref": "botsort",
                        },
                        "builtin_bytetrack": {
                            "runtime": {"tracker_name": "bytetrack"},
                            "artifact_ref": "bytetrack-s",
                        },
                    }
                }
            },
        ):
            registry_dir = Path(temp_dir)
            for filename in (
                "detectors.yaml",
                "reid_models.yaml",
                "anomaly_stage_1_models.yaml",
                "anomaly_stage_2_models.yaml",
            ):
                (registry_dir / filename).write_text("{}\n")
            (registry_dir / "trackers.yaml").write_text(
                "builtin_local_tracker:\n"
                "  stage: tracker\n"
                "  runtime:\n"
                "    tracker_name: ocsort-tuned\n"
                "builtin_bytetrack:\n"
                "  stage: tracker\n"
                "  runtime:\n"
                "    tracker_name: bytetrack\n"
                "  artifact_ref: bytetrack\n"
            )
            from shared.utils.model_registry import load_model_registries

            merged = load_model_registries(registry_dir)

        self.assertIn("builtin_botsort", merged["tracker"])
        self.assertIn("builtin_local_tracker", merged["tracker"])
        self.assertEqual(
            merged["tracker"]["builtin_bytetrack"]["artifact_ref"],
            "bytetrack",
        )
        self.assertEqual(
            merged["tracker"]["builtin_bytetrack"]["source_path"],
            str(registry_dir / "trackers.yaml"),
        )

    @unittest.skipIf(load_registry_bundle is None, "omegaconf is not installed")
    def test_validate_source_bindings_rejects_incompatible_source_kind(self):
        bundle = load_registry_bundle()
        defaults = build_default_bindings(bundle)
        source_row = SimpleNamespace(
            id=10,
            label="Uploaded Video",
            kind="video_upload",
            tasks=["PERSON"],
            detector_model_key="builtin_yolox_s_gpu",
            tracker_model_key="builtin_bytetrack",
            reid_model_key="builtin_transreid_person_hybrid_bag",
            anomaly_stage_1_model_key="heuristic_presence_stage_1",
            anomaly_stage_2_model_key="prompt_rules_stage_2",
        )
        bundle["models"][MODEL_STAGE_TRACKER]["builtin_bytetrack"]["capabilities"] = {
            "tasks": ["PERSON"],
            "source_kinds": ["camera_url"],
        }

        errors = validate_source_bindings(bundle, source_row, defaults)

        self.assertTrue(any("tracker model builtin_bytetrack" in error for error in errors))

    @unittest.skipIf(load_registry_bundle is None, "omegaconf is not installed")
    def test_validate_source_bindings_ignores_unrelated_tasks_for_tracker_stage(self):
        bundle = load_registry_bundle()
        defaults = build_default_bindings(bundle)
        source_row = SimpleNamespace(
            id=11,
            label="Mixed Task Camera",
            kind="camera_url",
            tasks=["PERSON", "BAG", "GUN", "FARE", "TRAY"],
            detector_model_key="builtin_yolox_s_gpu",
            tracker_model_key="builtin_bytetrack",
            reid_model_key="builtin_transreid_person_hybrid_bag",
            anomaly_stage_1_model_key="heuristic_presence_stage_1",
            anomaly_stage_2_model_key="prompt_rules_stage_2",
        )
        bundle["models"][MODEL_STAGE_TRACKER]["builtin_bytetrack"]["capabilities"] = {
            "tasks": ["PERSON", "BAG"],
            "source_kinds": ["camera_url", "video_upload", "webcam"],
        }

        errors = validate_source_bindings(bundle, source_row, defaults)

        self.assertFalse(any("tracker model builtin_bytetrack" in error for error in errors))

    @unittest.skipIf(load_registry_bundle is None, "omegaconf is not installed")
    def test_build_runtime_binding_block_includes_source_overrides(self):
        bundle = load_registry_bundle()
        source_row = SimpleNamespace(
            id=42,
            detector_model_key="builtin_yolox_s_gpu",
            tracker_model_key=None,
            reid_model_key="builtin_transreid_person_hybrid_bag",
            anomaly_stage_1_model_key="heuristic_presence_stage_1",
            anomaly_stage_2_model_key="prompt_rules_stage_2",
        )

        binding_block = build_runtime_binding_block([source_row], bundle)

        self.assertEqual(binding_block["sources"]["42"]["detector"], "builtin_yolox_s_gpu")
        self.assertEqual(binding_block["sources"]["42"]["reid"], "builtin_transreid_person_hybrid_bag")


class MicroBatchTests(unittest.TestCase):
    def test_build_micro_batch_envelope_keeps_asset_references_out_of_records(self):
        asset_reference = build_asset_reference(
            uri="/tmp/frame-1.jpg",
            media_type="image/jpeg",
            producer="INGESTOR",
        )

        envelope = build_micro_batch_envelope(
            run_identifier="run-123",
            batch_type="anomalies",
            records=[{"event_id": "evt-1"}],
            asset_references=[asset_reference],
            sink_key="standalone_default",
        )

        self.assertEqual(envelope["record_count"], 1)
        self.assertEqual(envelope["records"], [{"event_id": "evt-1"}])
        self.assertEqual(envelope["asset_references"], [asset_reference])
        self.assertEqual(envelope["sink_key"], "standalone_default")


class DockerCliTests(unittest.TestCase):
    def test_find_docker_binary_prefers_path_lookup(self):
        with patch("shared.utils.docker_cli.shutil.which", return_value="/usr/local/bin/docker"):
            self.assertEqual(find_docker_binary(), "/usr/local/bin/docker")

    def test_find_docker_binary_falls_back_to_known_locations(self):
        with patch("shared.utils.docker_cli.shutil.which", return_value=None), patch(
            "shared.utils.docker_cli.Path.exists", return_value=True
        ):
            self.assertEqual(
                find_docker_binary(),
                "/Applications/Docker.app/Contents/Resources/bin/docker",
            )

    def test_build_docker_env_adds_docker_directory_to_path(self):
        original_path = "/usr/local/bin"
        with patch.dict(os.environ, {"PATH": original_path}, clear=False):
            env = build_docker_env("/Applications/Docker.app/Contents/Resources/bin/docker")

        self.assertTrue(
            env["PATH"].startswith("/Applications/Docker.app/Contents/Resources/bin")
        )
        self.assertIn(original_path, env["PATH"])


class TrackerResolutionTests(unittest.TestCase):
    @unittest.skipIf(resolve_tracker_name is None, "omegaconf is not installed")
    def test_resolve_tracker_name_prefers_registry_runtime(self):
        registration = {"runtime": {"tracker_name": "bytetrack"}}

        self.assertEqual(
            resolve_tracker_name(
                registration,
                "builtin_bytetrack",
                legacy_tracker_name="ocsort",
            ),
            "bytetrack",
        )

    @unittest.skipIf(resolve_tracker_name is None, "omegaconf is not installed")
    def test_resolve_tracker_name_maps_builtin_bytetrack_without_registry(self):
        self.assertEqual(
            resolve_tracker_name(
                None,
                "builtin_bytetrack",
                legacy_tracker_name=None,
            ),
            "bytetrack",
        )

    @unittest.skipIf(resolve_tracker_name is None, "omegaconf is not installed")
    def test_resolve_tracker_name_uses_legacy_config_when_present(self):
        self.assertEqual(
            resolve_tracker_name(
                None,
                "builtin_missing",
                legacy_tracker_name="ocsort",
            ),
            "ocsort",
        )


class ThreadingTests(unittest.TestCase):
    def test_collect_live_thread_names_finds_nested_threads(self):
        stop_event = Event()

        def wait_for_stop():
            stop_event.wait()

        worker = Thread(target=wait_for_stop, name="nested-worker")
        worker.start()
        try:
            names = collect_live_thread_names({"module": SimpleNamespace(worker=worker)})
        finally:
            stop_event.set()
            worker.join(timeout=2)

        self.assertEqual(names, ["nested-worker"])


if __name__ == "__main__":
    unittest.main()
