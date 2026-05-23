"""
Arlo camera protocol codec.

Wire format: L:<length> <json_payload>
Example: L:42 {"Type":"registration","ID":1,...}
"""

from __future__ import annotations

import json
from asyncio import StreamReader, StreamWriter

HEADER_PREFIX = b"L:"
CHUNK_SIZE = 4096


async def read_message(reader: StreamReader) -> dict | None:
    header = b""
    while not header.endswith(b" "):
        byte = await reader.read(1)
        if not byte:
            return None
        header += byte

    header_str = header.decode("utf-8").strip()
    if not header_str.startswith("L:"):
        return None

    length = int(header_str[2:])
    payload = b""
    while len(payload) < length:
        chunk = await reader.read(min(CHUNK_SIZE, length - len(payload)))
        if not chunk:
            return None
        payload += chunk

    return json.loads(payload.decode("utf-8"))


async def write_message(writer: StreamWriter, message: dict) -> None:
    payload = json.dumps(message).encode("utf-8")
    header = f"L:{len(payload)} ".encode("utf-8")
    writer.write(header + payload)
    await writer.drain()


def encode_message(message: dict) -> bytes:
    payload = json.dumps(message).encode("utf-8")
    header = f"L:{len(payload)} ".encode("utf-8")
    return header + payload
