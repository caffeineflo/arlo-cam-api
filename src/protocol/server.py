"""Asyncio TCP server for camera connections."""

from __future__ import annotations

import asyncio

import structlog

from src.protocol.connection import ConnectionHandler

logger = structlog.get_logger()


async def start_tcp_server(handler: ConnectionHandler, port: int, name: str) -> asyncio.Server:
    server = await asyncio.start_server(handler.handle, "0.0.0.0", port)
    logger.info("tcp_server_started", port=port, name=name)
    return server
