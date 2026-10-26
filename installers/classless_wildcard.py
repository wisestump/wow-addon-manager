from __future__ import annotations

import csv
import logging
import os
import subprocess
from io import StringIO
from pathlib import Path

from models import InstallRequest, InstallerResult, RemoveRequest, UpdateRequest


class ClasslessWildcardInstaller:
    def __init__(self, python_executable: Path, logger: logging.Logger) -> None:
        self.logger = logger
        self.python_executable = python_executable

    @property
    def installer_id(self) -> str:
        return "classless_wildcard"

    def install(self, request: InstallRequest) -> InstallerResult:
        script = self._get_script(request.artifact.source_dir)
        self._assert_game_closed()
        self._ensure_pillow()
        self._run(script, ["--yes", "--locale", "ruRU", str(request.wow_path)])
        return InstallerResult(None)

    def update(self, request: UpdateRequest) -> InstallerResult:
        script = self._get_script(request.artifact.source_dir)
        self._assert_game_closed()
        self._ensure_pillow()
        self._run(script, ["--yes", "--locale", "ruRU", str(request.wow_path)])
        return InstallerResult(None)

    def remove(self, request: RemoveRequest) -> None:
        script = self._get_script(request.artifact.source_dir)
        self._assert_game_closed()
        self._run(script, ["--uninstall", "--yes", "--locale", "ruRU", str(request.wow_path)])

    def _get_script(self, source_dir: Path) -> Path:
        script = source_dir / "client-patch" / "install.py"
        addon_dir = source_dir / "client-addon" / "ClasslessWildcard"
        if not script.is_file():
            raise FileNotFoundError(f"Classless Wildcard client installer not found: {script}")
        if not addon_dir.is_dir():
            raise FileNotFoundError(f"Classless Wildcard addon not found: {addon_dir}")
        if not self.python_executable.is_file():
            raise FileNotFoundError(f"Portable Python not found: {self.python_executable}")
        return script

    def _ensure_pillow(self) -> None:
        check = subprocess.run(
            [str(self.python_executable), "-c", "import PIL"],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )
        if check.returncode == 0:
            return

        self.logger.info("Installing Pillow with the bundled Python")
        self._run_command([str(self.python_executable), "-m", "pip", "install", "Pillow"])
        check = subprocess.run(
            [str(self.python_executable), "-c", "import PIL"],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )
        if check.returncode != 0:
            detail = check.stderr.strip() or check.stdout.strip()
            raise RuntimeError(f"Pillow is unavailable in portable Python: {detail}")

    def _assert_game_closed(self) -> None:
        if os.name == "nt":
            command = ["tasklist", "/FI", "IMAGENAME eq Wow.exe", "/FO", "CSV", "/NH"]
        else:
            command = ["ps", "-A", "-o", "comm="]
        try:
            result = subprocess.run(command, capture_output=True, text=True, errors="replace", check=False)
        except OSError as exc:
            self.logger.warning("Cannot check whether World of Warcraft is running: %s", exc)
            return
        if result.returncode != 0:
            self.logger.warning(
                "Cannot check whether World of Warcraft is running: %s",
                result.stderr.strip() or f"process check exited with code {result.returncode}",
            )
            return
        if os.name == "nt":
            names = [row[0] for row in csv.reader(StringIO(result.stdout)) if row]
        else:
            names = result.stdout.splitlines()
        if any(Path(name.strip()).name.casefold() == "wow.exe" for name in names):
            raise RuntimeError("World of Warcraft is running (Wow.exe); close it before continuing")

    def _run(self, script: Path, arguments: list[str]) -> None:
        self._run_command([str(self.python_executable), str(script), *arguments], cwd=script.parent)

    def _run_command(self, command: list[str], *, cwd: Path | None = None) -> None:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )
        if result.stdout.strip():
            self.logger.info("Classless Wildcard script output:\n%s", result.stdout.rstrip())
        if result.stderr.strip():
            self.logger.warning("Classless Wildcard script errors:\n%s", result.stderr.rstrip())
        if result.returncode != 0:
            details = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
            raise RuntimeError(
                f"Classless Wildcard script exited with code {result.returncode}"
                + (f":\n{details}" if details else "")
            )

