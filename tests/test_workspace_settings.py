import unittest
from unittest.mock import patch

from shared.utils import workspace_settings


class WorkspaceSettingsUtilsTests(unittest.TestCase):
    def test_parse_workspace_setting_json_returns_default_for_invalid_json(self):
        parsed = workspace_settings.parse_workspace_setting_json("not-json", default={"theme_key": "fidelity-light"})
        self.assertEqual(parsed, {"theme_key": "fidelity-light"})

    def test_get_workspace_setting_value_uses_default_when_row_missing(self):
        with patch.object(workspace_settings, "get_workspace_setting_row", return_value=None):
            value = workspace_settings.get_workspace_setting_value(
                db=object(),
                setting_key=workspace_settings.SETTING_KEY_APPEARANCE,
                default={"theme_key": "fidelity-light"},
            )

        self.assertEqual(value, {"theme_key": "fidelity-light"})


if __name__ == "__main__":
    unittest.main()
