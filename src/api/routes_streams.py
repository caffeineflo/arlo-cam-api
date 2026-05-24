"""Stream discovery routes for go2rtc integration."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/streams")
async def list_streams(request: Request):
    go2rtc = request.app.state.go2rtc
    if not go2rtc:
        return {"streams": {}}
    return {"streams": await go2rtc.get_streams()}


@router.post("/streams/reload")
async def reload_streams(request: Request):
    go2rtc = request.app.state.go2rtc
    if not go2rtc:
        return {"result": False}
    await go2rtc.generate_config()
    reloaded = await go2rtc.reload()
    return {"result": reloaded}
