from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from models import AddonSpec, Manifest, ProviderConfig


class ManifestError(ValueError):
    pass


def load_manifest(path: str | Path) -> Manifest:
    manifest_path = Path(path).expanduser().resolve()
    try:
        with manifest_path.open("r", encoding="utf-8") as stream:
            raw = yaml.safe_load(stream)
    except OSError as exc:
        raise ManifestError(f"Cannot read manifest {manifest_path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ManifestError(f"Invalid YAML in {manifest_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ManifestError("Manifest root must be a YAML mapping")

    wow_value = raw.get("wow_path")
    if not isinstance(wow_value, str) or not wow_value.strip():
        raise ManifestError("wow_path must be a non-empty path")
    wow_path = Path(wow_value).expanduser()
    if not wow_path.is_absolute():
        wow_path = manifest_path.parent / wow_path
    wow_path = wow_path.resolve()

    raw_addons = raw.get("addons")
    if not isinstance(raw_addons, list):
        raise ManifestError("addons must be a YAML list (an empty list is allowed)")

    addons: list[AddonSpec] = []
    for index, raw_addon in enumerate(raw_addons):
        field = f"addons[{index}]"
        if not isinstance(raw_addon, dict):
            raise ManifestError(f"{field} must be a mapping")
        if "id" in raw_addon:
            raise ManifestError(f"{field}.id is provider-generated and must not be set in manifest.yaml")
        installer = _required_string(raw_addon, "installer", field)

        provider_raw = raw_addon.get("provider")
        if not isinstance(provider_raw, dict):
            raise ManifestError(f"{field}.provider must be a mapping")
        provider_type = _required_string(provider_raw, "type", f"{field}.provider")
        repository = _required_string(provider_raw, "repository", f"{field}.provider")
        ref = _optional_string(provider_raw.get("ref"), f"{field}.provider.ref")
        provider_path = _optional_string(provider_raw.get("path"), f"{field}.provider.path")
        if provider_path is not None:
            _validate_repo_path(provider_path, f"{field}.provider.path")

        addons.append(
            AddonSpec(
                provider=ProviderConfig(provider_type, repository, ref, provider_path),
                installer=installer,
            )
        )

    return Manifest(manifest_path, wow_path, tuple(addons))


def _required_string(data: dict[str, Any], key: str, field: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{field}.{key} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ManifestError(f"{field} must be a string or null")
    return value


def _validate_repo_path(value: str, field: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ManifestError(f"{field} must be a safe relative path within the repository")
