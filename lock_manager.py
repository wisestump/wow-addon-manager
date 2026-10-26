from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from models import LockRecord, ProviderRecord


class LockFileError(RuntimeError):
    pass


class LockManager:
    """Read and atomically persist the installed-addon records."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._records = self._read()

    @property
    def records(self) -> dict[str, LockRecord]:
        return dict(self._records)

    def get(self, addon_id: str) -> LockRecord | None:
        return self._records.get(addon_id)

    def set(self, addon_id: str, record: LockRecord) -> None:
        updated = dict(self._records)
        updated[addon_id] = record
        self._write(updated)
        self._records = updated

    def delete(self, addon_id: str) -> None:
        if addon_id not in self._records:
            return
        updated = dict(self._records)
        del updated[addon_id]
        self._write(updated)
        self._records = updated

    def _read(self) -> dict[str, LockRecord]:
        if not self.path.exists():
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                raw: Any = yaml.safe_load(stream)
        except (OSError, yaml.YAMLError) as exc:
            raise LockFileError(f"Cannot read lock file {self.path}: {exc}") from exc
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            raise LockFileError("Lock file root must be a mapping")
        if raw.get("version") != 1:
            raise LockFileError("Unsupported or missing lock file version")
        raw_addons = raw.get("addons")
        if not isinstance(raw_addons, dict):
            raise LockFileError("Lock file addons must be a mapping")
        try:
            return {
                str(addon_id): LockRecord.from_dict(record, addon_id=str(addon_id))
                for addon_id, record in raw_addons.items()
            }
        except (TypeError, ValueError) as exc:
            raise LockFileError(f"Invalid lock file record: {exc}") from exc

    def _write(self, records: dict[str, LockRecord]) -> None:
        payload = {
            "version": 1,
            "addons": {addon_id: record.to_dict() for addon_id, record in records.items()},
        }
        temp_path: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self.path.parent,
                prefix=f"{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temp_path = Path(stream.name)
                yaml.safe_dump(payload, stream, sort_keys=False, allow_unicode=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self.path)
        except (OSError, yaml.YAMLError, TypeError) as exc:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise LockFileError(f"Cannot write lock file {self.path}: {exc}") from exc
