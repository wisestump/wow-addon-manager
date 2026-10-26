from __future__ import annotations

from providers.base import RemoteProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, RemoteProvider] = {}

    def register(self, provider: RemoteProvider) -> None:
        self._providers[provider.provider_type] = provider

    def get(self, provider_type: str) -> RemoteProvider:
        try:
            return self._providers[provider_type]
        except KeyError as exc:
            raise LookupError(f"No provider registered for {provider_type!r}") from exc
