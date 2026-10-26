from __future__ import annotations

from pathlib import Path
from typing import Protocol

from models import AddonSpec, ProviderArtifact, ProviderRecord


class RemoteProvider(Protocol):
    provider_type: str

    def get_addon_id(self, addon: AddonSpec) -> str:
        """Return a stable ID derived from provider identity, not from its ref."""
        ...

    def resolve(self, addon: AddonSpec) -> ProviderRecord:
        """Resolve the configured ref to a pinned provider version without downloading sources."""
        ...

    def fetch(
        self, addon: AddonSpec, destination: Path, version: ProviderRecord
    ) -> ProviderArtifact:
        """Materialize the source for an already resolved provider version."""
        ...


class ProviderError(RuntimeError):
    pass
