from __future__ import annotations

from installers.protocol import Installer


class InstallerRegistry:
    """Registry for concrete installers, intentionally empty by default."""

    def __init__(self) -> None:
        self._installers: dict[str, Installer] = {}

    def register(self, installer: Installer) -> None:
        installer_id = installer.installer_id
        if not installer_id:
            raise ValueError("Installer id must not be empty")
        self._installers[installer_id] = installer

    def get(self, installer_id: str) -> Installer:
        try:
            return self._installers[installer_id]
        except KeyError as exc:
            raise LookupError(f"No installer registered for {installer_id!r}") from exc
