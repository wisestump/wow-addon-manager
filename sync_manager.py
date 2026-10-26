from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from installers.protocol import Installer
from installers.registry import InstallerRegistry
from lock_manager import LockManager
from manifest import Manifest
from models import (
    AddonSpec,
    InstallRequest,
    InstallerResult,
    LockRecord,
    ProviderArtifact,
    ProviderConfig,
    ProviderRecord,
    RemoveRequest,
    SyncReport,
    UpdateRequest,
)
from providers.base import RemoteProvider
from providers.registry import ProviderRegistry


@dataclass
class _Counts:
    installed: int = 0
    updated: int = 0
    removed: int = 0
    skipped: int = 0


class SyncManager:
    def __init__(
        self,
        manifest: Manifest,
        lock_manager: LockManager,
        provider_registry: ProviderRegistry,
        installer_registry: InstallerRegistry,
        logger: logging.Logger,
    ) -> None:
        self.manifest = manifest
        self.lock_manager = lock_manager
        self.provider_registry = provider_registry
        self.installer_registry = installer_registry
        self.logger = logger

    def sync(self) -> SyncReport:
        counts = _Counts()
        failures: list[str] = []
        plans = self._identify_addons()
        desired_ids = {addon_id for _, _, addon_id in plans}

        self._remove_obsolete(desired_ids, counts, failures)
        self._sync_manifest_addons(plans, counts, failures)

        return SyncReport(
            installed=counts.installed,
            updated=counts.updated,
            removed=counts.removed,
            skipped=counts.skipped,
            failures=tuple(failures),
        )

    def _identify_addons(self) -> list[tuple[AddonSpec, RemoteProvider, str]]:
        plans: list[tuple[AddonSpec, RemoteProvider, str]] = []
        desired_ids: set[str] = set()

        # Resolve all provider identities before doing filesystem work, so duplicate IDs
        # or provider configuration errors cannot accidentally prune existing lock rows.
        for addon in self.manifest.addons:
            try:
                provider = self.provider_registry.get(addon.provider.type)
                addon_id = provider.get_addon_id(addon)
            except Exception as exc:
                raise SyncPlanError(f"Cannot identify addon from provider config: {exc}") from exc
            if addon_id in desired_ids:
                raise SyncPlanError(f"Multiple manifest entries resolve to addon ID {addon_id!r}")
            desired_ids.add(addon_id)
            plans.append((addon, provider, addon_id))
        return plans

    def _remove_obsolete(self, desired_ids: set[str], counts: _Counts, failures: list[str]) -> None:
        for addon_id, previous in self.lock_manager.records.items():
            if addon_id in desired_ids:
                continue
            try:
                self._remove_one(addon_id, previous)
                counts.removed += 1
            except Exception as exc:
                self._record_failure(addon_id, exc, failures)

    def _remove_one(self, addon_id: str, previous: LockRecord) -> None:
        installer = self.installer_registry.get(previous.installer)
        provider = self.provider_registry.get(previous.provider.type)
        addon = AddonSpec(
            provider=ProviderConfig(
                type=previous.provider.type,
                repository=previous.provider.repository,
                ref=previous.provider.commit_sha,
                path=previous.provider.path,
            ),
            installer=previous.installer,
        )
        with tempfile.TemporaryDirectory(prefix="wow-addon-manager-remove-") as workspace:
            artifact = self._fetch_artifact(
                addon,
                provider,
                addon_id,
                previous.provider,
                Path(workspace),
            )
            installer.remove(
                RemoveRequest(
                    addon_id=addon_id,
                    wow_path=self.manifest.wow_path,
                    previous=previous,
                    artifact=artifact,
                )
            )
        self.lock_manager.delete(addon_id)
        self.logger.info("Removed addon %s", addon_id)

    def _sync_manifest_addons(
        self,
        plans: list[tuple[AddonSpec, RemoteProvider, str]],
        counts: _Counts,
        failures: list[str],
    ) -> None:
        for addon, provider, addon_id in plans:
            try:
                self._sync_one(addon, provider, addon_id, counts)
            except Exception as exc:
                self._record_failure(addon_id, exc, failures)

    def _sync_one(
        self,
        addon: AddonSpec,
        provider: RemoteProvider,
        addon_id: str,
        counts: _Counts,
    ) -> None:
        installer = self.installer_registry.get(addon.installer)
        previous = self.lock_manager.get(addon_id)
        version = provider.resolve(addon)
        if previous is not None and previous.provider.commit_sha == version.commit_sha:
            counts.skipped += 1
            self.logger.info("Skipped addon %s at unchanged SHA %s", addon_id, version.commit_sha)
            return

        with tempfile.TemporaryDirectory(prefix="wow-addon-manager-") as workspace:
            artifact = self._fetch_artifact(addon, provider, addon_id, version, Path(workspace))
            self._sync_addon(addon_id, addon, installer, artifact, previous, counts)

    @staticmethod
    def _fetch_artifact(
        addon: AddonSpec,
        provider: RemoteProvider,
        addon_id: str,
        version: ProviderRecord,
        destination: Path,
    ) -> ProviderArtifact:
        artifact = provider.fetch(addon, destination, version)
        if artifact.addon_id != addon_id:
            raise SyncPlanError(
                f"Provider returned inconsistent addon ID {artifact.addon_id!r}; expected {addon_id!r}"
            )
        if artifact.provider != version:
            raise SyncPlanError("Provider returned an artifact for a different resolved version")
        return artifact

    def _sync_addon(
        self,
        addon_id: str,
        addon: AddonSpec,
        installer: Installer,
        artifact: ProviderArtifact,
        previous: LockRecord | None,
        counts: _Counts,
    ) -> None:
        # The registry provides installers that satisfy the Installer protocol.
        if previous is None:
            result = installer.install(
                InstallRequest(addon_id=addon_id, addon=addon, wow_path=self.manifest.wow_path, artifact=artifact)
            )
            self.lock_manager.set(addon_id, self._new_lock_record(addon, artifact, result))
            counts.installed += 1
            self.logger.info("Installed addon %s at %s", addon_id, artifact.provider.commit_sha)
            return

        result = installer.update(
            UpdateRequest(
                addon_id=addon_id,
                addon=addon,
                wow_path=self.manifest.wow_path,
                artifact=artifact,
                previous=previous,
            )
        )
        self.lock_manager.set(addon_id, self._new_lock_record(addon, artifact, result))
        counts.updated += 1
        self.logger.info("Updated addon %s to %s", addon_id, artifact.provider.commit_sha)

    @staticmethod
    def _new_lock_record(addon: AddonSpec, artifact: ProviderArtifact, result: InstallerResult) -> LockRecord:
        return LockRecord(
            installer=addon.installer,
            provider=artifact.provider,
            installer_data=result.installer_data,
        )

    def _record_failure(self, addon_id: str, exc: Exception, failures: list[str]) -> None:
        failures.append(addon_id)
        self.logger.exception("Failed to sync addon %s: %s", addon_id, exc)


class SyncPlanError(RuntimeError):
    """The manifest cannot be mapped safely to provider-generated addon IDs."""
