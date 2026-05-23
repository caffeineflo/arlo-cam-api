"""Snapshot receive/serve routes with in-memory cache."""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import Response

router = APIRouter()


class SnapshotCache:
    def __init__(self, ttl: int = 300):
        self._cache: dict[str, tuple[bytes, float]] = {}
        self._ttl = ttl

    def store(self, identifier: str, data: bytes) -> None:
        self._cache[identifier] = (data, time.time())

    def get(self, identifier: str) -> bytes | None:
        entry = self._cache.get(identifier)
        if not entry:
            return None
        data, stored_at = entry
        if time.time() - stored_at > self._ttl:
            del self._cache[identifier]
            return None
        return data


@router.post("/snapshot/{identifier}/")
@router.post("/snapshot/{identifier}")
async def receive_snapshot(identifier: str, request: Request):
    cache: SnapshotCache = request.app.state.snapshot_cache
    content_type = request.headers.get("content-type", "")

    if "multipart" in content_type:
        form = await request.form()
        for field_name in form:
            upload: UploadFile = form[field_name]
            data = await upload.read()
            cache.store(identifier, data)
            return {"result": True}
    else:
        data = await request.body()
        if data:
            cache.store(identifier, data)
            return {"result": True}

    raise HTTPException(400, "No snapshot data received")


@router.get("/snapshot/{identifier}")
async def get_snapshot(identifier: str, request: Request):
    cache: SnapshotCache = request.app.state.snapshot_cache
    data = cache.get(identifier)
    if not data:
        raise HTTPException(404, "Snapshot not found")
    return Response(content=data, media_type="image/jpeg")
