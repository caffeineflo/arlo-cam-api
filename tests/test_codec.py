"""Tests for the L: framing protocol codec."""

from __future__ import annotations

import asyncio
import json

import pytest

from src.protocol.codec import read_message, write_message


@pytest.mark.asyncio
async def test_read_message_basic():
    payload = {"Type": "registration", "ID": 1}
    encoded = json.dumps(payload).encode("utf-8")
    frame = f"L:{len(encoded)} ".encode("utf-8") + encoded

    reader = asyncio.StreamReader()
    reader.feed_data(frame)
    reader.feed_eof()

    result = await read_message(reader)
    assert result == payload


@pytest.mark.asyncio
async def test_read_message_empty_returns_none():
    reader = asyncio.StreamReader()
    reader.feed_eof()

    result = await read_message(reader)
    assert result is None


@pytest.mark.asyncio
async def test_write_message():
    payload = {"Type": "response", "ID": 1, "Response": "Ack"}

    class FakeWriter:
        def __init__(self):
            self.data = b""

        def write(self, data: bytes):
            self.data += data

        async def drain(self):
            pass

    writer = FakeWriter()
    await write_message(writer, payload)

    encoded = json.dumps(payload).encode("utf-8")
    expected = f"L:{len(encoded)} ".encode("utf-8") + encoded
    assert writer.data == expected


@pytest.mark.asyncio
async def test_roundtrip():
    payload = {"Type": "alert", "AlertType": "pirMotionAlert", "PIRMotion": {"zones": [1]}}
    encoded = json.dumps(payload).encode("utf-8")
    frame = f"L:{len(encoded)} ".encode("utf-8") + encoded

    reader = asyncio.StreamReader()
    reader.feed_data(frame)
    reader.feed_eof()

    result = await read_message(reader)
    assert result == payload
    assert result["AlertType"] == "pirMotionAlert"
