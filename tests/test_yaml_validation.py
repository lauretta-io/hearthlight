import unittest
from pathlib import Path

from scripts.validate_yaml_files import (
    REPO_ROOT,
    classify_yaml_parser,
    validate_repo_yaml,
)


class YamlValidationTests(unittest.TestCase):
    def test_github_workflow_uses_general_yaml_parser(self):
        workflow_path = REPO_ROOT / ".github" / "workflows" / "macos-dmg.yml"
        self.assertEqual(classify_yaml_parser(workflow_path), "pyyaml")

    def test_repo_yaml_validation_has_no_owned_failures(self):
        failures = validate_repo_yaml()
        self.assertEqual(failures, [])

    def test_node_modules_yaml_is_excluded(self):
        vendored_workflow = REPO_ROOT / "frontend" / "node_modules" / "@ungap" / "structured-clone" / ".github" / "workflows" / "node.js.yml"
        self.assertTrue(vendored_workflow.exists())
        failure_paths = {failure.path for failure in validate_repo_yaml()}
        self.assertNotIn(vendored_workflow, failure_paths)


if __name__ == "__main__":
    unittest.main()
