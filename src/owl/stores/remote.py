"""Client side of the OWL server API."""

from __future__ import annotations

from urllib.parse import quote

import httpx

from owl.models import OwlError, SearchQuery, Skill, SkillSummary
from owl.stores.base import SkillStore

API = "/api/v1"
MAX_PAGE = 500


class RemoteStore(SkillStore):
    """A :class:`SkillStore` backed by a running ``owl serve`` instance.

    Pass *client* to inject a pre-configured :class:`httpx.Client` (used by the tests to
    talk to an in-process app).
    """

    def __init__(
        self,
        url: str = "",
        token: str | None = None,
        label: str = "remote",
        client: httpx.Client | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.label = label
        self.url = url.rstrip("/")
        self.token = token
        self._owns_client = client is None
        self.client = client or httpx.Client(base_url=self.url, timeout=timeout)

    # -- plumbing --------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            response = self.client.request(method, API + path, headers=headers, **kwargs)  # type: ignore[arg-type]
        except httpx.HTTPError as exc:
            raise OwlError(f"Remote '{self.label}' is unreachable ({self.url}): {exc}") from exc
        if response.status_code >= 400 and response.status_code != 404:
            try:
                detail = response.json().get("detail", "")
            except ValueError:
                detail = response.text[:200]
            hint = " - check the token" if response.status_code == 401 else ""
            raise OwlError(
                f"Remote '{self.label}' returned HTTP {response.status_code}: {detail}{hint}"
            )
        return response

    @staticmethod
    def _path(author: str, name: str) -> str:
        return f"/skills/{quote(author.lower(), safe='')}/{quote(name, safe='')}"

    # -- SkillStore ------------------------------------------------------------------

    def info(self) -> dict:
        return self._request("GET", "/info").json()

    def upsert(self, skill: Skill) -> Skill:
        response = self._request("PUT", self._path(skill.author, skill.name), json=skill.to_dict())
        return Skill.from_dict(response.json())

    def get(self, author: str, name: str) -> Skill | None:
        response = self._request("GET", self._path(author, name))
        if response.status_code == 404:
            return None
        return Skill.from_dict(response.json())

    def delete(self, author: str, name: str) -> bool:
        return self._request("DELETE", self._path(author, name)).status_code != 404

    def search(self, query: SearchQuery) -> list[SkillSummary]:
        results: list[SkillSummary] = []
        offset = query.offset
        while len(results) < query.limit:
            limit = min(MAX_PAGE, query.limit - len(results))
            params: dict[str, object] = {"q": query.text, "limit": limit, "offset": offset}
            if query.author:
                params["author"] = query.author
            if query.tags:
                params["tag"] = query.tags
            if query.topics:
                params["topic"] = query.topics
            page = self._request("GET", "/skills", params=params).json()
            results.extend(SkillSummary.from_dict(item, source=self.label) for item in page)
            if len(page) < limit:
                break
            offset += limit
        return results

    def facets(self, kind: str) -> list[tuple[str, int]]:
        data = self._request("GET", f"/facets/{kind}").json()
        return [(item["value"], int(item["count"])) for item in data]

    def close(self) -> None:
        if self._owns_client:
            self.client.close()
