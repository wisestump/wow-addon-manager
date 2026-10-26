from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProviderConfig:
    type: str
    repository: str
    ref: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class AddonSpec:
    provider: ProviderConfig
    installer: str


@dataclass(frozen=True)
class Manifest:
    path: Path
    wow_path: Path
    addons: tuple[AddonSpec, ...]


@dataclass(frozen=True)
class ProviderRecord:
    type: str
    repository: str
    ref: str | None
    path: str | None
    commit_sha: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "repository": self.repository,
            "ref": self.ref,
            "path": self.path,
            "commit_sha": self.commit_sha,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, field: str) -> ProviderRecord:
        if not isinstance(data, dict):
            raise ValueError(f"{field} must be a mapping")
        provider_type = _required_string(data, "type", field)
        repository = _required_string(data, "repository", field)
        commit_sha = _required_string(data, "commit_sha", field)
        ref = _optional_string(data.get("ref"), f"{field}.ref")
        path = _optional_string(data.get("path"), f"{field}.path")
        return cls(provider_type, repository, ref, path, commit_sha)


@dataclass(frozen=True)
class LockRecord:
    installer: str
    provider: ProviderRecord
    installer_data: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "installer": self.installer,
            "provider": self.provider.to_dict(),
            "installer_data": self.installer_data,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, addon_id: str) -> LockRecord:
        field = f"addons.{addon_id}"
        if not isinstance(data, dict):
            raise ValueError(f"{field} must be a mapping")
        installer = _required_string(data, "installer", field)
        if "installer_data" not in data:
            raise ValueError(f"{field}.installer_data is required")
        provider = ProviderRecord.from_dict(data.get("provider"), field=f"{field}.provider")
        return cls(installer, provider, data["installer_data"])


@dataclass(frozen=True)
class ProviderArtifact:
    addon_id: str
    provider: ProviderRecord
    source_dir: Path


@dataclass(frozen=True)
class InstallerResult:
    installer_data: Any


@dataclass(frozen=True)
class InstallRequest:
    addon_id: str
    addon: AddonSpec
    wow_path: Path
    artifact: ProviderArtifact


@dataclass(frozen=True)
class UpdateRequest:
    addon_id: str
    addon: AddonSpec
    wow_path: Path
    artifact: ProviderArtifact
    previous: LockRecord


@dataclass(frozen=True)
class RemoveRequest:
    addon_id: str
    wow_path: Path
    previous: LockRecord


@dataclass(frozen=True)
class SyncReport:
    installed: int = 0
    updated: int = 0
    removed: int = 0
    skipped: int = 0
    failures: tuple[str, ...] = ()


def _required_string(data: dict[str, Any], key: str, field: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}.{key} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string or null")
    return value
