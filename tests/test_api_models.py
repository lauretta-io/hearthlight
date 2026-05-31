import unittest
import importlib.util

PYDANTIC_AVAILABLE = importlib.util.find_spec("pydantic") is not None

if PYDANTIC_AVAILABLE:
    from pydantic import ValidationError
    from shared.models.APIModels import AppearanceSettings, Camera, InputSource, POISearch
    from shared.models.OperationsModels import IncidentUpdate


@unittest.skipUnless(PYDANTIC_AVAILABLE, "pydantic is not installed")
class CameraModelTests(unittest.TestCase):
    def test_camera_normalizes_tasks(self):
        camera = Camera(tasks=[" person ", "bag"], source="rtsp://example")
        self.assertEqual(camera.tasks, ["PERSON", "BAG"])

    def test_camera_rejects_empty_source(self):
        with self.assertRaises(ValidationError):
            Camera(tasks=["person"], source="   ")


@unittest.skipUnless(PYDANTIC_AVAILABLE, "pydantic is not installed")
class POISearchModelTests(unittest.TestCase):
    def test_poi_requires_images_when_not_research(self):
        with self.assertRaises(ValidationError):
            POISearch(name="Alice", research=False, images=None)

    def test_poi_allows_research_without_images(self):
        poi = POISearch(name="Alice", research=True, images=None)
        self.assertTrue(poi.research)


@unittest.skipUnless(PYDANTIC_AVAILABLE, "pydantic is not installed")
class InputSourceModelTests(unittest.TestCase):
    def test_camera_source_requires_source_value(self):
        with self.assertRaises(ValidationError):
            InputSource(
                kind="camera_url",
                label="Gate A",
                tasks=["person"],
                source_value=None,
            )

    def test_video_upload_requires_upload_id(self):
        with self.assertRaises(ValidationError):
            InputSource(
                kind="video_upload",
                label="Evidence Clip",
                tasks=["bag"],
            )

    def test_webcam_source_coerces_numeric_device_index(self):
        source = InputSource(
            kind="webcam",
            label="Desk Cam",
            tasks=["bag"],
            source_value="1",
        )
        self.assertEqual(source.source_value, 1)

    def test_video_upload_forces_frame_skip_mode(self):
        source = InputSource(
            kind="video_upload",
            label="Evidence Clip",
            tasks=["bag"],
            upload_id=7,
            frame_processing_mode="target_frame_rate",
            process_every_n_frames=3,
            target_frame_rate=2.5,
        )
        self.assertEqual(source.frame_processing_mode, "frame_skip")
        self.assertIsNone(source.target_frame_rate)
        self.assertEqual(source.effective_frame_processing_mode, "frame_skip")
        self.assertEqual(source.effective_process_every_n_frames, 3)


@unittest.skipUnless(PYDANTIC_AVAILABLE, "pydantic is not installed")
class AppearanceSettingsModelTests(unittest.TestCase):
    def test_accepts_supported_theme_key(self):
        settings = AppearanceSettings(theme_key="fidelity-dark")
        self.assertEqual(settings.theme_key, "fidelity-dark")

    def test_rejects_unsupported_theme_key(self):
        with self.assertRaises(ValidationError):
            AppearanceSettings(theme_key="unknown-theme")


@unittest.skipUnless(PYDANTIC_AVAILABLE, "pydantic is not installed")
class IncidentUpdateModelTests(unittest.TestCase):
    def test_incident_update_normalizes_status(self):
        update = IncidentUpdate(
            incident_id="UB-20260313-10",
            new_status="resolved",
            update_time=None,
        )
        self.assertEqual(update.new_status, "RESOLVED")

    def test_incident_update_rejects_bad_format(self):
        with self.assertRaises(ValidationError):
            IncidentUpdate(
                incident_id="bad-id",
                new_status="RESOLVED",
                update_time=None,
            )


if __name__ == "__main__":
    unittest.main()
