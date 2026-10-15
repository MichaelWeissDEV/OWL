"""The OWL HTTP server (``owl serve``). Requires the ``server`` extra."""

from __future__ import annotations

import html
import secrets
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from owl import __version__
from owl.models import InvalidSkill, OwlError, SearchQuery, Skill
from owl.stores.base import FACET_KINDS, SkillStore

API = "/api/v1"


def create_app(store: SkillStore, token: str | None = None, private: bool = False) -> FastAPI:
    """Create the API application.

    *token* protects every write (and every read when *private* is set). Without a token
    the server is read-only.
    """
    app = FastAPI(title="OWL skill server", version=__version__)

    def _check(authorization: str | None) -> bool:
        if not token or not authorization:
            return False
        scheme, _, supplied = authorization.partition(" ")
        return scheme.lower() == "bearer" and secrets.compare_digest(
            supplied.encode(), token.encode()
        )

    def require_read(authorization: Annotated[str | None, Header()] = None) -> None:
        if private and not _check(authorization):
            raise HTTPException(401, "Authentication required")

    def require_write(authorization: Annotated[str | None, Header()] = None) -> None:
        if not token:
            raise HTTPException(403, "This server is read-only (no write token configured)")
        if not _check(authorization):
            raise HTTPException(401, "Invalid or missing token")

    read = [Depends(require_read)]
    write = [Depends(require_write)]

    @app.exception_handler(OwlError)
    async def _owl_error(_request: Any, exc: OwlError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.get("/", response_class=HTMLResponse, dependencies=read)
    def index(q: str = "", author: str | None = None, tag: str | None = None) -> str:
        """A small read-only web page for browsing the server in a browser."""
        query = SearchQuery(text=q, author=author or None, tags=[tag] if tag else [], limit=200)
        rows = "".join(
            "<tr><td><code>{ref}</code></td><td>{ver}</td><td>{desc}</td><td>{tags}</td></tr>".format(
                ref=html.escape(s.ref),
                ver=html.escape(s.version),
                desc=html.escape(s.description[:200]),
                tags=html.escape(", ".join(s.tags)),
            )
            for s in store.search(query)
        )
        return (
            "<!doctype html><meta charset=utf-8><title>OWL skill server</title>"
            "<style>body{font:15px system-ui;margin:2rem auto;max-width:60rem;padding:0 1rem}"
            "td,th{padding:.3rem .6rem;border-bottom:1px solid #8884;text-align:left}"
            "input{padding:.3rem}</style>"
            f"<h1>OWL skill server</h1><p>{store.count()} skills &middot; "
            '<a href="/docs">API docs</a></p>'
            '<form><input name=q placeholder="search" value="'
            f'{html.escape(q, quote=True)}"> <button>Search</button></form>'
            "<table><tr><th>Skill<th>Version<th>Description<th>Tags</tr>"
            f"{rows}</table>"
        )

    @app.get(f"{API}/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(f"{API}/info", dependencies=read)
    def info() -> dict[str, Any]:
        return {
            "name": "owl",
            "version": __version__,
            "skills": store.count(),
            "writable": bool(token),
            "private": private,
        }

    @app.get(f"{API}/skills", dependencies=read)
    def search(
        q: str = "",
        author: str | None = None,
        tag: Annotated[list[str] | None, Query()] = None,
        topic: Annotated[list[str] | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[dict[str, Any]]:
        query = SearchQuery(
            text=q, author=author, tags=tag or [], topics=topic or [], limit=limit, offset=offset
        )
        return [s.to_dict() for s in store.search(query)]

    @app.get(f"{API}/skills/{{author}}/{{name}}", dependencies=read)
    def get_skill(author: str, name: str) -> dict[str, Any]:
        skill = store.get(author, name)
        if skill is None:
            raise HTTPException(404, "Skill not found")
        return skill.to_dict()

    @app.put(f"{API}/skills/{{author}}/{{name}}", dependencies=write)
    def put_skill(author: str, name: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            skill = Skill.from_dict(body)
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(422, f"Malformed skill: {exc}") from exc
        if (skill.author, skill.name) != (author.lower(), name):
            raise HTTPException(422, "Skill author/name does not match the URL")
        try:
            return store.upsert(skill).to_dict()
        except InvalidSkill as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.delete(f"{API}/skills/{{author}}/{{name}}", dependencies=write)
    def delete_skill(author: str, name: str) -> dict[str, bool]:
        if not store.delete(author, name):
            raise HTTPException(404, "Skill not found")
        return {"deleted": True}

    @app.get(f"{API}/facets/{{kind}}", dependencies=read)
    def facets(kind: str) -> list[dict[str, Any]]:
        if kind not in FACET_KINDS:
            raise HTTPException(404, f"Unknown facet '{kind}'")
        return [{"value": v, "count": n} for v, n in store.facets(kind)]

    return app


def serve(store: SkillStore, host: str, port: int, token: str | None, private: bool) -> None:
    import uvicorn

    uvicorn.run(create_app(store, token, private), host=host, port=port, log_level="info")
