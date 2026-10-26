from __future__ import annotations

import json
import os
import shutil
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from models import AddonSpec, ProviderArtifact, ProviderRecord
from providers.base import ProviderError


class GitHubProvider:
    provider_type = "github"
    api_root = "https://api.github.com"

    def __init__(self, *, timeout: float = 60.0) -> None:
        self.timeout = timeout

    def get_addon_id(self, addon: AddonSpec) -> str:
        owner, repository = self._split_repository(addon.provider.repository)
        base = f"{owner.casefold()}/{repository.casefold()}"
        if addon.provider.path:
            path = PurePosixPath(addon.provider.path).as_posix()
            escaped_path = urllib.parse.quote(path, safe="/-._~")
            return f"github:{base}:{escaped_path}"
        return f"github:{base}"

    def resolve(self, addon: AddonSpec) -> ProviderRecord:
        config = addon.provider
        owner, repository = self._split_repository(config.repository)
        ref = config.ref or self._default_branch(owner, repository)
        commit_sha = self._resolve_commit(owner, repository, ref)
        return ProviderRecord(
            type=self.provider_type,
            repository=config.repository,
            ref=config.ref,
            path=config.path,
            commit_sha=commit_sha,
        )

    def fetch(
        self, addon: AddonSpec, destination: Path, version: ProviderRecord
    ) -> ProviderArtifact:
        config = addon.provider
        if (
            version.type != self.provider_type
            or version.repository != config.repository
            or version.path != config.path
        ):
            raise ProviderError("Resolved GitHub version does not match addon provider configuration")

        owner, repository = self._split_repository(version.repository)
        archive_root = self._download_archive(owner, repository, version.commit_sha, destination)

        if version.path:
            source_dir = self._select_subdirectory(archive_root, version.path)
        else:
            source_dir = archive_root

        return ProviderArtifact(
            addon_id=self.get_addon_id(addon),
            provider=version,
            source_dir=source_dir,
        )

    def _split_repository(self, value: str) -> tuple[str, str]:
        parts = value.strip("/").split("/")
        if len(parts) != 2 or any(not part or part in {".", ".."} for part in parts):
            raise ProviderError("GitHub repository must use the owner/repository format")
        if any(any(ch in part for ch in "?#\\") for part in parts):
            raise ProviderError("Invalid character in GitHub repository name")
        return parts[0], parts[1].removesuffix(".git")

    def _default_branch(self, owner: str, repository: str) -> str:
        data = self._get_json(f"/repos/{self._quote(owner)}/{self._quote(repository)}")
        branch = data.get("default_branch")
        if not isinstance(branch, str) or not branch:
            raise ProviderError("GitHub did not return a repository default branch")
        return branch

    def _resolve_commit(self, owner: str, repository: str, ref: str) -> str:
        encoded_ref = urllib.parse.quote(ref, safe="")
        data = self._get_json(
            f"/repos/{self._quote(owner)}/{self._quote(repository)}/commits/{encoded_ref}"
        )
        sha = data.get("sha")
        if not isinstance(sha, str) or not sha:
            raise ProviderError(f"GitHub did not resolve ref {ref!r} to a commit SHA")
        return sha

    def _download_archive(
        self, owner: str, repository: str, commit_sha: str, destination: Path
    ) -> Path:
        destination.mkdir(parents=True, exist_ok=True)
        archive_path = destination / "source.zip"
        url = (
            f"{self.api_root}/repos/{self._quote(owner)}/{self._quote(repository)}"
            f"/zipball/{self._quote(commit_sha, safe='')}"
        )
        request = self._request(url, accept="application/vnd.github+json")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                with archive_path.open("wb") as output:
                    shutil.copyfileobj(response, output)
        except (OSError, urllib.error.URLError) as exc:
            raise ProviderError(f"Cannot download GitHub archive for {owner}/{repository}: {exc}") from exc

        extracted_root = destination / "repo"
        extracted_root.mkdir()
        try:
            with zipfile.ZipFile(archive_path) as archive:
                self._extract_safely(archive, extracted_root)
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            raise ProviderError(f"Cannot unpack GitHub source archive: {exc}") from exc
        finally:
            archive_path.unlink(missing_ok=True)

        roots = [path for path in extracted_root.iterdir() if path.is_dir()]
        if len(roots) != 1:
            raise ProviderError("Unexpected GitHub archive layout: expected one repository root folder")
        return roots[0]

    def _get_json(self, endpoint: str) -> dict[str, Any]:
        request = self._request(f"{self.api_root}{endpoint}", accept="application/vnd.github+json")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(f"GitHub API returned HTTP {exc.code}: {detail}") from exc
        except (OSError, urllib.error.URLError) as exc:
            raise ProviderError(f"GitHub API request failed: {exc}") from exc
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ProviderError("GitHub API returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ProviderError("GitHub API returned an unexpected response")
        return data

    def _request(self, url: str, *, accept: str) -> urllib.request.Request:
        headers = {
            "Accept": accept,
            "User-Agent": "wow-addon-manager/0.1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return urllib.request.Request(url, headers=headers)

    @staticmethod
    def _quote(value: str, *, safe: str = "") -> str:
        return urllib.parse.quote(value, safe=safe)

    @staticmethod
    def _extract_safely(archive: zipfile.ZipFile, destination: Path) -> None:
        base = destination.resolve()
        for member in archive.infolist():
            name = PurePosixPath(member.filename)
            if name.is_absolute() or ".." in name.parts:
                raise ProviderError("GitHub archive contains an unsafe path")
            target = (destination / Path(*name.parts)).resolve()
            if target != base and base not in target.parents:
                raise ProviderError("GitHub archive path escapes extraction directory")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)

    @staticmethod
    def _select_subdirectory(archive_root: Path, repo_path: str) -> Path:
        relative = PurePosixPath(repo_path)
        if relative.is_absolute() or ".." in relative.parts or "\\" in repo_path:
            raise ProviderError("provider.path must be a safe relative repository path")
        selected = archive_root.joinpath(*relative.parts).resolve()
        base = archive_root.resolve()
        if selected != base and base not in selected.parents:
            raise ProviderError("provider.path escapes the repository")
        if not selected.is_dir():
            raise ProviderError(f"provider.path does not name a directory: {repo_path}")
        return selected
