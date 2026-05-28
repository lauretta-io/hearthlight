import io
import json
import unittest
from unittest.mock import patch
from urllib import error as urllib_error

from shared.utils.govee_connector import (
    build_govee_capability_options,
    discover_govee_devices,
    send_govee_device_control,
    test_govee_api_key,
)


class _FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")
        self.status = 200

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class GoveeConnectorTests(unittest.TestCase):
    def test_build_govee_capability_options_filters_supported_light_actions(self):
        capabilities = [
            {
                "type": "devices.capabilities.on_off",
                "instance": "powerSwitch",
                "parameters": {
                    "options": [{"name": "on", "value": 1}, {"name": "off", "value": 0}],
                },
            },
            {
                "type": "devices.capabilities.range",
                "instance": "brightness",
                "parameters": {"range": {"min": 1, "max": 100, "precision": 1}},
            },
            {
                "type": "devices.capabilities.color_setting",
                "instance": "colorRgb",
                "parameters": {"range": {"min": 0, "max": 16777215, "precision": 1}},
            },
            {
                "type": "devices.capabilities.dynamic_scene",
                "instance": "lightScene",
                "parameters": {"options": [{"name": "Party", "value": 3055}]},
            },
            {
                "type": "devices.capabilities.toggle",
                "instance": "oscillationToggle",
                "parameters": {"options": [{"name": "on", "value": 1}]},
            },
        ]

        options = build_govee_capability_options(capabilities)

        self.assertEqual([entry["label"] for entry in options], ["Power", "Brightness", "RGB Color", "Scene"])

    @patch("shared.utils.govee_connector.urllib_request.urlopen")
    def test_discover_govee_devices_returns_light_capable_devices(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse(
            {
                "code": 200,
                "message": "success",
                "data": [
                    {
                        "sku": "H6000",
                        "device": "AA:BB",
                        "deviceName": "Desk Light",
                        "type": "devices.types.light",
                        "capabilities": [
                            {
                                "type": "devices.capabilities.on_off",
                                "instance": "powerSwitch",
                                "parameters": {
                                    "options": [{"name": "on", "value": 1}, {"name": "off", "value": 0}],
                                },
                            }
                        ],
                    },
                    {
                        "sku": "H7000",
                        "device": "CC:DD",
                        "deviceName": "Non Light",
                        "type": "devices.types.socket",
                        "capabilities": [],
                    },
                ],
            }
        )

        devices = discover_govee_devices("key")

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["device_name"], "Desk Light")
        self.assertEqual(devices[0]["capability_options"][0]["instance"], "powerSwitch")

    @patch("shared.utils.govee_connector.urllib_request.urlopen")
    def test_test_govee_api_key_handles_empty_device_list(self, mock_urlopen):
        mock_urlopen.side_effect = [
            _FakeResponse({"code": 200, "message": "success", "data": []}),
            _FakeResponse({"code": 200, "message": "success", "data": []}),
        ]

        result = test_govee_api_key("key")

        self.assertTrue(result["valid"])
        self.assertEqual(result["device_count"], 0)
        self.assertEqual(result["light_device_count"], 0)
        self.assertIn("no bound devices", result["message"].lower())

    @patch("shared.utils.govee_connector.urllib_request.urlopen")
    def test_send_govee_device_control_posts_expected_payload(self, mock_urlopen):
        captured = {}

        def _fake_urlopen(req, timeout=0):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.header_items())
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            return _FakeResponse({"code": 200, "message": "success", "data": {}})

        mock_urlopen.side_effect = _fake_urlopen

        send_govee_device_control(
            api_key="test-key",
            sku="H6000",
            device="AA:BB",
            capability_type="devices.capabilities.on_off",
            instance="powerSwitch",
            value=1,
        )

        self.assertTrue(captured["url"].endswith("/device/control"))
        self.assertEqual(captured["payload"]["payload"]["sku"], "H6000")
        self.assertEqual(captured["payload"]["payload"]["device"], "AA:BB")
        self.assertEqual(captured["payload"]["payload"]["capability"]["instance"], "powerSwitch")
        self.assertEqual(captured["payload"]["payload"]["capability"]["value"], 1)

    @patch("shared.utils.govee_connector.urllib_request.urlopen")
    def test_discover_govee_devices_raises_readable_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib_error.HTTPError(
            url="https://openapi.api.govee.com/router/api/v1/user/devices",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b'{"message":"invalid key"}'),
        )

        with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
            discover_govee_devices("bad-key")


if __name__ == "__main__":
    unittest.main()
