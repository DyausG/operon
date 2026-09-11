"""Build the Python 3.12/arm64 AgentCore CodeZip without contacting AWS."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import re
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_name("package_manifest.json")
BUILD = ROOT / "agentcore_app" / "build"
PACKAGE = BUILD / "package"
ARCHIVE = BUILD / "operon_reasoner.zip"
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".env", ".pem", ".key", ".pyc"}
IDENTITY_DEPENDENCIES = ("pydantic", "pydantic-core", "strands-agents")
IDENTITY_SOURCES = ("core/reasoning/identity.py", "core/reasoning/protocol.py",
                    "core/agents/contracts.py", "core/reliability/promotion.py")


def load_manifest() -> dict:
    data = json.loads(MANIFEST.read_text())
    if data["python_runtime"] != "PYTHON_3_12" or data["python_platform"] != "aarch64-manylinux2014":
        raise RuntimeError("package manifest must target Python 3.12 aarch64-manylinux2014")
    if not set(IDENTITY_SOURCES).issubset(data["sources"]):
        raise RuntimeError("package manifest omits runtime identity source")
    return data


def locked_versions(path: Path) -> dict[str, str]:
    return {match.group(1).lower(): match.group(2) for match in re.finditer(
        r"(?m)^([A-Za-z0-9_.-]+)==([^ ;\\]+)", path.read_text())}


def validate_identity_dependencies(requirements: Path) -> None:
    runtime = locked_versions(requirements)
    application = {item["name"].lower(): item["version"] for item in tomllib.loads(
        (ROOT / "uv.lock").read_text())["package"] if item["name"].lower() in IDENTITY_DEPENDENCIES}
    mismatch = {name: (application.get(name), runtime.get(name)) for name in IDENTITY_DEPENDENCIES
                if application.get(name) != runtime.get(name)}
    if mismatch:
        raise RuntimeError("runtime identity dependency drift: " + ", ".join(
            f"{name} application={versions[0]} runtime={versions[1]}" for name, versions in mismatch.items()))


def validate_entry_point(path: Path, manifest: dict) -> None:
    command = manifest["entry_point"][0]
    declarations = [item.read_text() for item in path.glob("*.dist-info/entry_points.txt")]
    if not any(re.search(rf"(?m)^{re.escape(command)}\s*=", text) for text in declarations):
        raise RuntimeError(f"packaged console entry point is absent: {command}")


def source_mapping(manifest: dict) -> list[tuple[Path, Path]]:
    result = []
    for relative in manifest["sources"]:
        source = ROOT / relative
        if not source.is_file():
            raise FileNotFoundError(f"required runtime source is absent: {relative}")
        target = Path("main.py") if relative == "agentcore_app/main.py" else Path(relative)
        result.append((source, target))
    return result


def validate_tree(path: Path) -> list[str]:
    names = sorted(item.relative_to(path).as_posix() for item in path.rglob("*") if item.is_file())
    public_ca_bundles = {"botocore/cacert.pem", "certifi/cacert.pem", "grpc/_cython/_credentials/roots.pem"}
    bad = [name for name in names if (Path(name).suffix.lower() in FORBIDDEN_SUFFIXES and
                                      name not in public_ca_bundles) or
           "__pycache__" in Path(name).parts or name.startswith(("data/", "tests/", ".git/"))]
    if bad:
        raise RuntimeError("forbidden files entered runtime package: " + ", ".join(bad))
    return names


def build(*, dependencies: bool = True) -> Path:
    manifest = load_manifest()
    if shutil.which("uv") is None:
        raise RuntimeError("uv is required to build the AgentCore package")
    if BUILD.exists():
        shutil.rmtree(BUILD)
    PACKAGE.mkdir(parents=True)
    for source, relative in source_mapping(manifest):
        target = PACKAGE / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    if dependencies:
        requirements = ROOT / "agentcore_app" / "requirements.txt"
        if not requirements.is_file():
            raise FileNotFoundError("agentcore_app/requirements.txt is required")
        validate_identity_dependencies(requirements)
        command = ["uv", "pip", "install", "--python-platform", manifest["python_platform"],
                   "--python-version", "3.12", "--target", str(PACKAGE), "--only-binary=:all:",
                   "--no-compile", "--require-hashes", "--requirement", str(requirements)]
        completed = subprocess.run(command, cwd=ROOT)
        if completed.returncode:
            raise RuntimeError(f"dependency packaging failed with exit code {completed.returncode}")
        validate_entry_point(PACKAGE, manifest)
    for source, relative in source_mapping(manifest):
        if (PACKAGE / relative).read_bytes() != source.read_bytes():
            raise RuntimeError(f"packaged runtime source differs from application source: {relative}")
    names = validate_tree(PACKAGE)
    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in names:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (PACKAGE / name).read_bytes(), compresslevel=9)
    digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    print(f"package={ARCHIVE}\nfiles={len(names)}\nbytes={ARCHIVE.stat().st_size}\nsha256={digest}")
    return ARCHIVE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources-only", action="store_true", help="skip wheel resolution (validation/tests only)")
    args = parser.parse_args(argv)
    build(dependencies=not args.sources_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
