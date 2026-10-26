from __future__ import annotations

from typing import Protocol

from models import InstallRequest, InstallerResult, RemoveRequest, UpdateRequest


class Installer(Protocol):
    """Contract for transactional addon operations; no installer is implemented yet."""

    @property
    def installer_id(self) -> str:
        ...

    def install(self, request: InstallRequest) -> InstallerResult:
        """Install an addon and return installer-owned state for the lock file."""
        ...

    def update(self, request: UpdateRequest) -> InstallerResult:
        """Update an addon transactionally and return its new installer-owned state."""
        ...

    def remove(self, request: RemoveRequest) -> None:
        """Remove only the files tracked in the previous installer-owned state."""
        ...
