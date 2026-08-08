"""Build a deterministic managed-release ZIP from a checked-out application."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.updater import _version, platform_target


class PackageError(RuntimeError):
    """The release package cannot be safely produced."""


APP_FILES = (
    "main.py",
    "core",
    "interfaces",
    "requirements.txt",
    "requirements-windows.txt",
    "package.json",
    "package-lock.json",
)
SKIP_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache"}


def _copy_tree(
    source: Path,
    destination: Path,
    *,
    allow_symlinks: bool = False,
    symlink_root: Path | None = None,
    active_directories: set[Path] | None = None,
) -> None:
    active = active_directories if active_directories is not None else set()
    if source.is_symlink():
        if not allow_symlinks:
            raise PackageError(f"Refusing to package symlink: {source}")
        root = (symlink_root or source.parent).resolve()
        try:
            resolved = source.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise PackageError(f"Symlink target is unavailable: {source}") from exc
        if not resolved.is_relative_to(root):
            raise PackageError(f"Symlink escapes its root: {source}")
        _copy_tree(
            resolved,
            destination,
            allow_symlinks=True,
            symlink_root=root,
            active_directories=active,
        )
        return
    if source.is_dir():
        resolved_source = source.resolve()
        if resolved_source in active:
            raise PackageError(f"Symlink re-enters an ancestor: {source}")
        active.add(resolved_source)
        destination.mkdir(parents=True, exist_ok=True)
        try:
            for child in source.iterdir():
                if child.name in SKIP_NAMES:
                    continue
                _copy_tree(
                    child,
                    destination / child.name,
                    allow_symlinks=allow_symlinks,
                    symlink_root=symlink_root,
                    active_directories=active,
                )
        finally:
            active.remove(resolved_source)
        return
    if not source.is_file():
        raise PackageError(f"Release input is not a regular file: {source}")
    if source.suffix == ".pyc":
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _copy_inputs(root: Path, destination: Path, inputs: Iterable[str]) -> None:
    for relative in inputs:
        source = root / relative
        if not source.exists():
            raise PackageError(f"Required release input is missing: {relative}")
        _copy_tree(source, destination / relative)


def _write_zip(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".partial")
    temporary.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as bundle:
            for path in sorted(source.rglob("*")):
                if path.is_symlink():
                    raise PackageError(f"Refusing to package symlink: {path}")
                if path.is_dir():
                    continue
                relative = path.relative_to(source).as_posix()
                info = zipfile.ZipInfo(relative)
                info.date_time = (1980, 1, 1, 0, 0, 0)
                mode = stat.S_IMODE(path.stat().st_mode)
                info.external_attr = (stat.S_IFREG | mode) << 16
                bundle.writestr(
                    info,
                    path.read_bytes(),
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def build_package(
    root: Path,
    version: str,
    target: str,
    output: Path,
    *,
    runtime: Path,
    browsers: Path | None = None,
    node_modules: Path | None = None,
) -> Path:
    """Build a release containing source, a copied Python runtime, and browsers."""
    try:
        _version(version)
    except Exception as exc:
        raise PackageError("Version must be a numeric semantic version") from exc
    if target != platform_target():
        raise PackageError(
            f"Release target {target} does not match the build host {platform_target()}"
        )
    if not runtime.is_dir() or runtime.is_symlink():
        raise PackageError("A copied, self-contained runtime directory is required")
    with tempfile.TemporaryDirectory(prefix="warranty-release-") as temporary:
        staging = Path(temporary)
        (staging / "release.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "version": version,
                    "target": target,
                    "data_schema_version": 1,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        _copy_inputs(root, staging / "app", APP_FILES)
        _copy_tree(
            runtime,
            staging / "runtime",
            allow_symlinks=True,
            symlink_root=runtime.resolve(),
        )
        if browsers is not None:
            if not browsers.is_dir() or browsers.is_symlink():
                raise PackageError("Browser runtime must be a regular directory")
            _copy_tree(
                browsers,
                staging / "browsers",
                allow_symlinks=True,
                symlink_root=browsers.resolve(),
            )
        if node_modules is not None:
            if not node_modules.is_dir() or node_modules.is_symlink():
                raise PackageError("node_modules directory must be a regular directory")
            _copy_tree(
                node_modules,
                staging / "app" / "node_modules",
                allow_symlinks=True,
                symlink_root=node_modules.resolve(),
            )
        _write_zip(staging, output)
    return output


def main(argv: Sequence[str] | None = None) -> int:
    """Build a managed-release ZIP from command-line arguments."""
    parser = argparse.ArgumentParser(description="Build a managed release ZIP")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--version", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--browsers", type=Path)
    parser.add_argument("--node-modules", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        build_package(
            args.root.resolve(),
            args.version,
            args.target,
            args.output.resolve(),
            runtime=args.runtime.resolve(),
            browsers=args.browsers.resolve() if args.browsers else None,
            node_modules=args.node_modules.resolve() if args.node_modules else None,
        )
    except (OSError, PackageError) as exc:
        parser.error(str(exc))
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
