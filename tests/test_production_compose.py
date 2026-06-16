import os
import shutil
import subprocess
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


def _docker_binary() -> str | None:
    return shutil.which("docker") or (
        "/Applications/Docker.app/Contents/Resources/bin/docker"
        if Path("/Applications/Docker.app/Contents/Resources/bin/docker").exists()
        else None
    )


@unittest.skipIf(_docker_binary() is None, "Docker CLI is not available")
class ProductionComposeTests(unittest.TestCase):
    def test_production_gpu_compose_renders_reference_hosted_shape(self):
        env = os.environ.copy()
        for key in (
            "API_REPLICAS",
            "HEARTHLIGHT_WEBAPP_GPU_IMAGE",
            "HEARTHLIGHT_ANOMALY_GPU_IMAGE",
            "HEARTHLIGHT_INGESTOR_GPU_IMAGE",
            "HEARTHLIGHT_ASSOCIATION_GPU_IMAGE",
            "HEARTHLIGHT_OBJECT_STORE_S3_BUCKET",
            "HEARTHLIGHT_OBJECT_STORE_S3_ENDPOINT_URL",
            "HEARTHLIGHT_OBJECT_STORE_S3_ACCESS_KEY_ID",
            "HEARTHLIGHT_OBJECT_STORE_S3_SECRET_ACCESS_KEY",
        ):
            env.pop(key, None)
        completed = subprocess.run(
            [
                _docker_binary(),
                "compose",
                "-f",
                "docker-compose.yaml",
                "-f",
                "docker-compose.production.yaml",
                "-f",
                "docker-compose.gpu.yaml",
                "config",
            ],
            cwd=REPO_ROOT,
            env=env,
            check=True,
            text=True,
            capture_output=True,
        )
        config = yaml.safe_load(completed.stdout)
        services = config["services"]

        webapp = services["webapp"]
        self.assertEqual(webapp["deploy"]["replicas"], 3)
        self.assertEqual(webapp["image"], "hearthlight-webapp:cuda")
        self.assertEqual(webapp["build"]["args"]["HEARTHLIGHT_IMAGE_VARIANT"], "cuda")
        self.assertEqual(webapp["environment"]["HEARTHLIGHT_IMAGE_VARIANT"], "cuda")
        self.assertEqual(webapp["environment"]["HEARTHLIGHT_LOCAL_STACK"], "false")
        self.assertEqual(webapp["environment"]["POSTGRES_HOST"], "pgbouncer")
        self.assertEqual(webapp["environment"]["WORKER_CONCURRENCY"], "32")
        self.assertEqual(webapp["environment"]["WORKER_POLL_SECONDS"], "0.05")
        self.assertEqual(webapp["environment"]["INLINE_INFERENCE_AFTER_PREPROCESS"], "true")
        self.assertNotIn("ports", webapp)

        anomaly = services["anomaly"]
        self.assertEqual(anomaly["image"], "hearthlight-anomaly:cuda")
        self.assertEqual(anomaly["build"]["args"]["HEARTHLIGHT_IMAGE_VARIANT"], "cuda")
        self.assertEqual(anomaly["environment"]["HEARTHLIGHT_IMAGE_VARIANT"], "cuda")
        self.assertEqual(anomaly["environment"]["POSTGRES_HOST"], "pgbouncer")
        self.assertEqual(anomaly["environment"]["WORKER_CONCURRENCY"], "32")
        self.assertEqual(anomaly["environment"]["WORKER_POLL_SECONDS"], "0.05")
        self.assertEqual(anomaly["environment"]["INLINE_INFERENCE_AFTER_PREPROCESS"], "true")
        self.assertEqual(anomaly["runtime"], "nvidia")
        self.assertIn("gpus", anomaly)

        reverse_proxy = services["reverse_proxy"]
        published_ports = reverse_proxy.get("ports") or []
        self.assertTrue(any(str(port.get("published")) == "3000" for port in published_ports))


if __name__ == "__main__":
    unittest.main()
