import tempfile
import unittest
from pathlib import Path

from tools.release_audit import audit


class ReleaseAuditTests(unittest.TestCase):
    def test_accepts_a_clean_source_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "main.py").write_text("print('safe')\n", encoding="utf-8")
            self.assertEqual(audit(root), [])

    def test_rejects_runtime_data_and_sensitive_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "warranty_cache.db").write_text("data", encoding="utf-8")
            local_path = "/" + "Users" + "/example/private"
            (root / "config.py").write_text(f"path = '{local_path}'\n", encoding="utf-8")
            failures = audit(root)

        self.assertTrue(any("prohibited file type" in failure for failure in failures))
        self.assertTrue(any("local absolute path" in failure for failure in failures))

    def test_rejects_runtime_configuration_and_realistic_warranty_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "printer_binding.json").write_text("{}", encoding="utf-8")
            realistic_serial = "MXL" + "1234567"
            (root / "fixture.py").write_text(
                f"serial_number = '{realistic_serial}'\n",
                encoding="utf-8",
            )

            failures = audit(root)

        self.assertTrue(any("runtime configuration file" in failure for failure in failures))
        self.assertTrue(any("non-synthetic warranty identifier" in failure for failure in failures))

    def test_accepts_explicitly_synthetic_warranty_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "fixture.py").write_text(
                "serial_number = 'MXLTEST001'\n",
                encoding="utf-8",
            )

            failures = audit(root)

        self.assertEqual(failures, [])

    def test_rejects_unapproved_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "unknown.bin").write_bytes(b"\xff\x00\x80")

            failures = audit(root)

        self.assertTrue(any("non-text file" in failure for failure in failures))

    def test_ignores_installed_node_modules_but_audits_lockfile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dependency = root / "node_modules" / "example" / "readme.md"
            dependency.parent.mkdir(parents=True)
            dependency_path = "/" + "Users" + "/vendor/build"
            dependency.write_text(
                f"local path: {dependency_path}\n",
                encoding="utf-8",
            )
            lockfile_path = "/" + "Users" + "/operator/private"
            (root / "package-lock.json").write_text(
                f'{{"path": "{lockfile_path}"}}\n',
                encoding="utf-8",
            )

            failures = audit(root)

        self.assertEqual(len(failures), 1)
        self.assertIn("package-lock.json", failures[0])

    def test_rejects_unpinned_workflow_action(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workflow = root / ".github" / "workflows" / "test.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """name: Test
on: push
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
""",
                encoding="utf-8",
            )

            failures = audit(root)

        self.assertEqual(failures, ["unpinned workflow action: .github/workflows/test.yml"])

    def test_rejects_unpinned_workflow_action_with_quoted_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workflow = root / ".github" / "workflows" / "test.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """name: Test
on: push
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - "uses": actions/checkout@v4
""",
                encoding="utf-8",
            )

            failures = audit(root)

        self.assertEqual(failures, ["unpinned workflow action: .github/workflows/test.yml"])

    def test_handles_recursive_workflow_yaml_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workflow = root / ".github" / "workflows" / "test.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """name: Test
on: push
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - &step
        uses: actions/checkout@v4
        recursive: *step
""",
                encoding="utf-8",
            )

            failures = audit(root)

        self.assertEqual(failures, ["unpinned workflow action: .github/workflows/test.yml"])

    def test_accepts_sha_pinned_actions_and_digest_pinned_docker_images(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workflow = root / ".github" / "workflows" / "test.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """name: Test
on: push
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
      - uses: docker://rhysd/actionlint@sha256:9d36088643581e728c969f35141f88139fec77280b2be23c1f66f8e40e1025e7
""",
                encoding="utf-8",
            )

            failures = audit(root)

        self.assertEqual(failures, [])
