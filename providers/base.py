from __future__ import annotations

from pathlib import Path
from typing import Protocol

from models import AddonSpec, ProviderArtifact


class RemoteProvider(Protocol):
    provider_type: str

    def get_addon_id(self, addon: AddonSpec) -> str:
        """Return a stable ID derived from provider identity, not from its ref."""
        ...

    def fetch(self, addon: AddonSpec, destination: Path) -> ProviderArtifact:
        """Resolve the remote ref and materialize its source under destination."""
        ...


class ProviderError(RuntimeError):
    pass
