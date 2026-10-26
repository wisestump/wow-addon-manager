from __future__ import annotations

import argparse
import logging
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Sequence

from models import AddonSpec, ProviderConfig
from providers.github import GitHubProvider


def update_manager_source(repository: str) -> str:
    """Download the complete manager source and replace the bootstrap files."""
    source_dir = Path(__file__).resolve().parent
    source_dir.parent.mkdir(parents=True, exist_ok=True)

    temporary_root = Path(tempfile.mkdtemp(prefix="wow-manager-update-"))
    stage = source_dir.parent / f".{source_dir.name}.new-{uuid.uuid4().hex}"
    backup = source_dir.parent / f".{source_dir.name}.backup-{uuid.uuid4().hex}"
    previous_source_moved = False
    try:
        addon = AddonSpec(
            provider=ProviderConfig(type="github", repository=repository),
            installer="source",
        )
        provider = GitHubProvider()
        version = provider.resolve(addon)
        artifact = provider.fetch(addon, temporary_root, version)
        downloaded_source = artifact.source_dir
        if not (downloaded_source / "cli.py").is_file():
            raise RuntimeError("Manager archive must contain cli.py at its repository root")

        shutil.copytree(
            downloaded_source,
            stage,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )

        if source_dir.exists():
            source_dir.replace(backup)
            previous_source_moved = True
        try:
            stage.replace(source_dir)
        except Exception:
            if previous_source_moved and backup.exists():
                backup.replace(source_dir)
                previous_source_moved = False
            raise

        if previous_source_moved:
            try:
                shutil.rmtree(backup)
            except OSError:
                logging.warning("Could not remove previous manager source at %s", backup)
            previous_source_moved = False
        return artifact.provider.commit_sha
    finally:
        if previous_source_moved and backup.exists() and not source_dir.exists():
            backup.replace(source_dir)
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        shutil.rmtree(temporary_root, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wow-addon-manager-bootstrap")
    parser.add_argument("--repository", required=True, help="GitHub repository in owner/repo format")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    try:
        commit_sha = update_manager_source(args.repository)
    except Exception:
        logging.exception("Manager self-update failed")
        return 1
    logging.info("Updated manager source to %s", commit_sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
