"""Exercise locked dependency installs against a local package mirror."""

from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from threading import Thread
import tomllib
import unittest
import zipfile


APP_ROOT = Path(__file__).resolve().parents[2]
UV = os.getenv("AGENTOPS_TEST_UV") or shutil.which("uv")
EXPORT_OPTIONS = ["--frozen", "--no-dev", "--no-emit-project", "--no-emit-package", "jockey"]


class QuietPackageHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipUnless(UV, "uv is required for dependency installation tests")
class ApiDependencyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = dict(os.environ)
        self.environment.update({
            "UV_CACHE_DIR": str(self.root / "cache"),
            "UV_PYTHON_DOWNLOADS": "never",
            "UV_HTTP_TIMEOUT": "5",
            "UV_HTTP_RETRIES": "0",
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        })
        for name in ("UV_INDEX", "UV_DEFAULT_INDEX", "UV_INDEX_URL", "UV_EXTRA_INDEX_URL", "UV_FIND_LINKS"):
            self.environment.pop(name, None)

    def run_uv(self, *arguments, success=True):
        result = subprocess.run(
            [UV, "--no-config", *map(str, arguments)],
            env=self.environment, capture_output=True, text=True, encoding="utf-8", timeout=45,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def export(self, project):
        return self.run_uv("export", "--project", project, *EXPORT_OPTIONS).stdout

    def test_production_export_preserves_versions_and_hashes(self):
        exported = self.export(APP_ROOT / "api")
        lock = tomllib.loads((APP_ROOT / "api" / "uv.lock").read_text(encoding="utf-8"))
        packages = {
            (package["name"], package["version"]): package
            for package in lock["package"]
            if "registry" in package["source"]
        }
        requirements = re.findall(
            r"^([\w.-]+)==([^\s;\\]+)(.*?)(?=^[\w.-]+==|\Z)",
            exported, re.MULTILINE | re.DOTALL,
        )
        names = set()
        for name, version, body in requirements:
            package = packages[(name, version)]
            artifacts = package.get("wheels", []) + ([package["sdist"]] if "sdist" in package else [])
            expected = {artifact["hash"] for artifact in artifacts}
            actual = set(re.findall(r"--hash=(sha256:[a-f0-9]+)", body))
            self.assertEqual(actual, expected, name)
            names.add(name)
        self.assertTrue({"botocore", "kubernetes", "psycopg-binary", "clickhouse-connect"} <= names)
        self.assertFalse({"agentops-api", "jockey", "pytest", "vcrpy"} & names)
        self.assertNotIn("https://", exported)
        self.assertNotIn("-e ", exported)

    def prepare_mirror(self):
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as wheel:
            wheel.writestr("cache_probe/__init__.py", '__version__ = "1.0.0"\n')
            wheel.writestr("cache_probe-1.0.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: cache-probe\nVersion: 1.0.0\n")
            wheel.writestr("cache_probe-1.0.0.dist-info/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
            wheel.writestr("cache_probe-1.0.0.dist-info/RECORD", "")
        wheel_bytes = content.getvalue()
        digest = hashlib.sha256(wheel_bytes).hexdigest()
        filename = "cache_probe-1.0.0-py3-none-any.whl"
        website = self.root / "mirror"
        packages = website / "packages"
        packages.mkdir(parents=True)
        artifact = packages / filename
        artifact.write_bytes(wheel_bytes)
        index = website / "simple" / "cache-probe"
        index.mkdir(parents=True)
        (index / "index.html").write_text(
            f'<a href="/packages/{filename}#sha256={digest}">{filename}</a>', encoding="utf-8",
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietPackageHandler, directory=str(website)))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop_server():
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.addCleanup(stop_server)
        project = self.root / "project"
        project.mkdir()
        (project / "pyproject.toml").write_text(
            '[project]\nname = "build-probe"\nversion = "0.1.0"\n'
            'requires-python = ">=3.12"\ndependencies = ["cache-probe==1.0.0", "jockey"]\n'
            '[tool.uv.sources]\njockey = { path = "jockey", editable = true }\n',
            encoding="utf-8",
        )
        # These unreachable URLs deliberately differ from the configured mirror.
        (project / "uv.lock").write_text(
            'version = 1\nrevision = 2\nrequires-python = ">=3.12"\n'
            '[[package]]\nname = "build-probe"\nversion = "0.1.0"\nsource = { editable = "." }\n'
            'dependencies = [{ name = "cache-probe" }, { name = "jockey" }]\n'
            '[[package]]\nname = "jockey"\nversion = "0.1.0"\nsource = { editable = "jockey" }\n'
            'dependencies = [{ name = "cache-probe" }]\n'
            '[[package]]\nname = "cache-probe"\nversion = "1.0.0"\n'
            'source = { registry = "https://unreachable.invalid/simple" }\n'
            f'wheels = [{{ url = "https://unreachable.invalid/packages/{filename}", '
            f'hash = "sha256:{digest}", size = {len(wheel_bytes)} }}]\n',
            encoding="utf-8",
        )
        requirements = self.root / "requirements.txt"
        requirements.write_text(self.export(project), encoding="utf-8")
        environment = self.root / "venv"
        self.run_uv("venv", "--python", sys.executable, environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        return artifact, requirements, python, f"http://127.0.0.1:{server.server_port}/simple/"

    def install(self, requirements, python, index, *, success=True):
        return self.run_uv(
            "pip", "install", "--python", python, "--require-hashes", "--no-deps",
            "--default-index", index, "--requirements", requirements, success=success,
        )

    def test_locked_urls_are_replaced_by_the_configured_mirror(self):
        _, requirements, python, index = self.prepare_mirror()
        self.install(requirements, python, index)
        result = subprocess.run(
            [str(python), "-c", "import cache_probe; print(cache_probe.__version__)"],
            capture_output=True, text=True, encoding="utf-8", timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1.0.0")

    def test_modified_mirror_artifact_is_rejected(self):
        artifact, requirements, python, index = self.prepare_mirror()
        with zipfile.ZipFile(artifact, "a") as wheel:
            wheel.comment = b"changed-after-locking"
        result = self.install(requirements, python, index, success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hash", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
