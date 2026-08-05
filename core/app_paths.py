"""Cross-platform locations for mutable application data and legacy migration."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional


APP_DIRECTORY_NAME = "WarrantyLabelPrinter"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class AppPaths:
    data_dir: Path
    cache_path: Path
    profile_path: Path
    binding_path: Path
    labels_dir: Path
    logs_dir: Path


def _default_data_dir(
    platform_name: str, environment: Mapping[str, str], home: Path
) -> Path:
    override = environment.get("WARRANTY_LABEL_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if platform_name == "win32":
        local_app_data = environment.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / APP_DIRECTORY_NAME
        return home / "AppData" / "Local" / APP_DIRECTORY_NAME
    if platform_name == "darwin":
        return home / "Library" / "Application Support" / APP_DIRECTORY_NAME
    xdg_data_home = environment.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / APP_DIRECTORY_NAME
    return home / ".local" / "share" / APP_DIRECTORY_NAME


def get_app_paths(
    *,
    platform_name: Optional[str] = None,
    environment: Optional[Mapping[str, str]] = None,
    home: Optional[Path] = None,
    create: bool = True,
    migrate: bool = True,
) -> AppPaths:
    """Resolve writable paths without depending on the current working directory."""
    env = environment if environment is not None else os.environ
    actual_platform = platform_name or sys.platform
    actual_home = home or Path.home()
    data_dir = _default_data_dir(actual_platform, env, actual_home)
    paths = AppPaths(
        data_dir=data_dir,
        cache_path=data_dir / "warranty_cache.db",
        profile_path=data_dir / "tsc_profile.json",
        binding_path=data_dir / "printer_binding.json",
        labels_dir=data_dir / "labels",
        logs_dir=data_dir / "logs",
    )
    if create:
        paths.data_dir.mkdir(parents=True, exist_ok=True)
        paths.labels_dir.mkdir(parents=True, exist_ok=True)
        paths.logs_dir.mkdir(parents=True, exist_ok=True)
    if migrate:
        legacy_cache = PROJECT_ROOT / ".warranty_cache.db"
        cache_copied = _copy_legacy_file(legacy_cache, paths.cache_path)
        if cache_copied:
            _copy_legacy_file(
                Path(f"{legacy_cache}-wal"), Path(f"{paths.cache_path}-wal")
            )
            _copy_legacy_file(
                Path(f"{legacy_cache}-shm"), Path(f"{paths.cache_path}-shm")
            )
        _copy_legacy_file(PROJECT_ROOT / ".tsc_profile.json", paths.profile_path)
    return paths


def _copy_legacy_file(source: Path, destination: Path) -> bool:
    """Copy a legacy file once; never delete or overwrite operator data."""
    if destination.exists() or not source.is_file():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source, destination)
        return True
    except OSError:
        # A read-only legacy checkout must not prevent safe file-mode startup.
        return False
