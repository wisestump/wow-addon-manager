from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Sequence

from installers.classless_wildcard import ClasslessWildcardInstaller
from installers.registry import InstallerRegistry
from lock_manager import LockManager
from manifest import ManifestError, load_manifest
from providers.github import GitHubProvider
from providers.registry import ProviderRegistry
from sync_manager import SyncManager, SyncPlanError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wow-addon-manager")
    commands = parser.add_subparsers(dest="command", required=True)
    sync = commands.add_parser("sync", help="synchronize addons to the manifest")
    sync.add_argument("--manifest", default="manifest.yaml", help="path to manifest.yaml")
    sync.add_argument("--python", default=sys.executable, help="Python executable for installer scripts")
    return parser


def create_installer_registry(python_executable: Path, logger: logging.Logger) -> InstallerRegistry:
    registry = InstallerRegistry()
    registry.register(ClasslessWildcardInstaller(python_executable, logger))
    return registry


def configure_logging(directory: Path) -> logging.Logger:
    logger = logging.getLogger("wow_addon_manager")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    try:
        file_handler = RotatingFileHandler(
            directory / "wow-addon-manager.log",
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as exc:
        logger.warning("Could not open log file: %s", exc)
    return logger


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest_path = Path(args.manifest).expanduser().resolve()
    logger = configure_logging(manifest_path.parent)

    try:
        manifest = load_manifest(manifest_path)
        lock_manager = LockManager(manifest.path.with_name("manifest.lock.yaml"))
    except (ManifestError, RuntimeError) as exc:
        logger.exception("Cannot start sync: %s", exc)
        return 2

    providers = ProviderRegistry()
    providers.register(GitHubProvider())
    installers = create_installer_registry(Path(args.python).expanduser().resolve(), logger)
    try:
        report = SyncManager(manifest, lock_manager, providers, installers, logger).sync()
    except SyncPlanError as exc:
        logger.exception("Cannot plan sync: %s", exc)
        return 2

    logger.info(
        "Sync finished: installed=%d updated=%d removed=%d skipped=%d failures=%d",
        report.installed,
        report.updated,
        report.removed,
        report.skipped,
        len(report.failures),
    )
    if report.failures:
        logger.error("Some addons failed; see the log for details: %s", manifest.path.parent / "wow-addon-manager.log")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
