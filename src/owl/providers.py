"""Optional creation of *remote* repositories through a git host's official API.

This only ever runs when the user explicitly calls ``owl registry create ... --provider ...``
and confirms the target. Tokens come from the environment and are never printed or stored.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from owl.models import OwlError

TOKEN_ENV = {
    "github": ("OWL_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"),
    "gitlab": ("OWL_GITLAB_TOKEN", "GITLAB_TOKEN"),
    "gitea": ("OWL_GITEA_TOKEN", "GITEA_TOKEN", "FORGEJO_TOKEN"),
}
DEFAULT_BASE = {"github": "https://api.github.com", "gitlab": "https://gitlab.com", "gitea": ""}
PROVIDERS = tuple(TOKEN_ENV)


@dataclass
class RemoteRepo:
    clone_url: str
    html_url: str
    full_name: str


def find_token(provider: str) -> str | None:
    for name in TOKEN_ENV[provider]:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _client(client: httpx.Client | None) -> httpx.Client:
    return client or httpx.Client(timeout=30.0)


def _fail(provider: str, response: httpx.Response) -> OwlError:
    try:
        detail = response.json()
        detail = detail.get("message") or detail.get("error") or detail
    except ValueError:
        detail = response.text[:200]
    hints = {
        401: "the token is invalid or expired",
        403: "the token lacks permission to create repositories",
        404: "the owner/organisation was not found or is not visible to this token",
        409: "a repository with that name already exists",
        422: "the repository name is invalid or already exists",
    }
    hint = hints.get(response.status_code, "")
    return OwlError(
        f"{provider} API error {response.status_code}: {detail}" + (f" ({hint})" if hint else "")
    )


def whoami(
    provider: str, token: str, base_url: str | None = None, client: httpx.Client | None = None
) -> str:
    """The account the token belongs to (shown to the user before anything is created)."""
    http = _client(client)
    base = (base_url or DEFAULT_BASE[provider]).rstrip("/")
    if provider == "github":
        response = http.get(f"{base}/user", headers=_headers(provider, token))
        key = "login"
    elif provider == "gitlab":
        response = http.get(f"{base}/api/v4/user", headers=_headers(provider, token))
        key = "username"
    else:
        response = http.get(f"{base}/api/v1/user", headers=_headers(provider, token))
        key = "login"
    if response.status_code >= 400:
        raise _fail(provider, response)
    return str(response.json()[key])


def _headers(provider: str, token: str) -> dict[str, str]:
    if provider == "gitlab":
        return {"PRIVATE-TOKEN": token}
    headers = {"Authorization": f"Bearer {token}" if provider == "github" else f"token {token}"}
    if provider == "github":
        headers["Accept"] = "application/vnd.github+json"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    return headers


def create_repository(
    provider: str,
    name: str,
    *,
    token: str,
    owner: str | None = None,
    private: bool = False,
    description: str = "",
    base_url: str | None = None,
    client: httpx.Client | None = None,
) -> RemoteRepo:
    """Create an empty repository. Raises :class:`OwlError` with a readable reason on failure."""
    if provider not in PROVIDERS:
        raise OwlError(f"Unknown provider '{provider}'. Supported: {', '.join(PROVIDERS)}")
    http = _client(client)
    base = (base_url or DEFAULT_BASE[provider]).rstrip("/")
    if provider == "gitea" and not base:
        raise OwlError("The gitea/forgejo provider needs --base-url, e.g. https://git.example.com")
    headers = _headers(provider, token)
    if provider == "github":
        url = f"{base}/orgs/{owner}/repos" if owner else f"{base}/user/repos"
        response = http.post(
            url,
            headers=headers,
            json={"name": name, "private": private, "description": description},
        )
        data: dict[str, Any] = response.json() if response.status_code < 400 else {}
        if response.status_code >= 400:
            raise _fail(provider, response)
        return RemoteRepo(data["clone_url"], data["html_url"], data["full_name"])
    if provider == "gitlab":
        body: dict[str, Any] = {
            "name": name,
            "path": name,
            "description": description,
            "visibility": "private" if private else "public",
        }
        if owner:
            ns = http.get(f"{base}/api/v4/namespaces", headers=headers, params={"search": owner})
            if ns.status_code >= 400:
                raise _fail(provider, ns)
            match = next(
                (n for n in ns.json() if n.get("path") == owner or n.get("full_path") == owner),
                None,
            )
            if match is None:
                raise OwlError(f"gitlab: namespace '{owner}' not found")
            body["namespace_id"] = match["id"]
        response = http.post(f"{base}/api/v4/projects", headers=headers, json=body)
        if response.status_code >= 400:
            raise _fail(provider, response)
        data = response.json()
        return RemoteRepo(data["http_url_to_repo"], data["web_url"], data["path_with_namespace"])
    url = f"{base}/api/v1/orgs/{owner}/repos" if owner else f"{base}/api/v1/user/repos"
    response = http.post(
        url, headers=headers, json={"name": name, "private": private, "description": description}
    )
    if response.status_code >= 400:
        raise _fail(provider, response)
    data = response.json()
    return RemoteRepo(data["clone_url"], data["html_url"], data["full_name"])
