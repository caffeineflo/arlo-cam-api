from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    serial_number TEXT PRIMARY KEY,
    ip TEXT,
    hostname TEXT,
    friendly_name TEXT,
    registration TEXT,
    status TEXT,
    last_seen REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS desired_state (
    serial_number TEXT PRIMARY KEY,
    register_set_values TEXT NOT NULL DEFAULT '{}',
    quality_preset TEXT,
    power_mode TEXT,
    updated_at REAL NOT NULL
);
"""


class Database:
    def __init__(self, path: str):
        self._path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._migrate_devices()
        await self._migrate_desired_state()
        await self._db.commit()

    async def _migrate_devices(self) -> None:
        cursor = await self._db.execute("PRAGMA table_info(devices)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "last_seen" not in columns:
            await self._db.execute("ALTER TABLE devices ADD COLUMN last_seen REAL NOT NULL DEFAULT 0")

    async def _migrate_desired_state(self) -> None:
        from src.devices.camera import (
            BATTERY_MOTION_STREAM_LIMIT_SECONDS,
            BATTERY_STREAM_LIMIT_SECONDS,
            BATTERY_USER_STREAM_LIMIT_SECONDS,
        )

        cursor = await self._db.execute("PRAGMA table_info(desired_state)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "power_mode" not in columns:
            await self._db.execute("ALTER TABLE desired_state ADD COLUMN power_mode TEXT")
        cursor = await self._db.execute("SELECT serial_number, register_set_values, power_mode FROM desired_state")
        for serial_number, raw_values, power_mode in await cursor.fetchall():
            values = json.loads(raw_values or "{}")
            changed = values.pop("UserStreamActive", None) is not None
            if power_mode != "external":
                battery_maximums = {
                    "DefaultMotionStreamTimeLimit": BATTERY_MOTION_STREAM_LIMIT_SECONDS,
                    "MaxUserStreamTimeLimit": BATTERY_USER_STREAM_LIMIT_SECONDS,
                    "MaxStreamTimeLimit": BATTERY_STREAM_LIMIT_SECONDS,
                    "MaxMotionStreamTimeLimit": BATTERY_MOTION_STREAM_LIMIT_SECONDS,
                }
                for name, maximum in battery_maximums.items():
                    if name not in values:
                        continue
                    value = values[name]
                    if type(value) is not int or value < 1 or value > maximum:
                        values[name] = maximum
                        changed = True
            if changed:
                await self._db.execute(
                    "UPDATE desired_state SET register_set_values=? WHERE serial_number=?",
                    (json.dumps(values), serial_number),
                )

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def upsert_device(
        self,
        serial_number: str,
        ip: str,
        hostname: str,
        friendly_name: str,
        registration: dict | None = None,
        status: dict | None = None,
        last_seen: float = 0,
    ) -> None:
        await self._db.execute(
            """INSERT INTO devices (
                   serial_number, ip, hostname, friendly_name, registration, status, last_seen
               )
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(serial_number) DO UPDATE SET
                 ip=excluded.ip,
                 hostname=excluded.hostname,
                 registration=COALESCE(excluded.registration, devices.registration),
                 status=COALESCE(excluded.status, devices.status),
                 last_seen=CASE
                   WHEN excluded.last_seen > 0 THEN excluded.last_seen
                   ELSE devices.last_seen
                 END""",
            (
                serial_number,
                ip,
                hostname,
                friendly_name,
                json.dumps(registration) if registration else None,
                json.dumps(status) if status else None,
                last_seen,
            ),
        )
        await self._db.commit()

    async def update_status(
        self,
        serial_number: str,
        status: dict,
        last_seen: float | None = None,
    ) -> None:
        if last_seen is None:
            await self._db.execute(
                "UPDATE devices SET status=? WHERE serial_number=?",
                (json.dumps(status), serial_number),
            )
        else:
            await self._db.execute(
                "UPDATE devices SET status=?, last_seen=? WHERE serial_number=?",
                (json.dumps(status), last_seen, serial_number),
            )
        await self._db.commit()

    async def update_last_seen(self, serial_number: str, last_seen: float) -> None:
        await self._db.execute(
            "UPDATE devices SET last_seen=? WHERE serial_number=?",
            (last_seen, serial_number),
        )
        await self._db.commit()

    async def update_friendly_name(self, serial_number: str, name: str) -> None:
        await self._db.execute(
            "UPDATE devices SET friendly_name=? WHERE serial_number=?",
            (name, serial_number),
        )
        await self._db.commit()

    async def get_device(self, serial_number: str) -> dict | None:
        cursor = await self._db.execute("SELECT * FROM devices WHERE serial_number=?", (serial_number,))
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    async def get_all_devices(self) -> list[dict]:
        cursor = await self._db.execute("SELECT * FROM devices")
        rows = await cursor.fetchall()
        return [self._row_to_dict(r) for r in rows]

    async def delete_device(self, serial_number: str) -> bool:
        await self._db.execute("DELETE FROM desired_state WHERE serial_number=?", (serial_number,))
        cursor = await self._db.execute("DELETE FROM devices WHERE serial_number=?", (serial_number,))
        await self._db.commit()
        return cursor.rowcount > 0

    async def get_desired_state(self, serial_number: str) -> dict | None:
        cursor = await self._db.execute("SELECT * FROM desired_state WHERE serial_number=?", (serial_number,))
        row = await cursor.fetchone()
        if not row:
            return None
        return dict(row)

    async def upsert_desired_state(
        self,
        serial_number: str,
        register_set_values: dict,
        quality_preset: str | None = None,
        power_mode: str | None = None,
    ) -> None:
        import time

        await self._db.execute(
            """INSERT INTO desired_state (
                   serial_number, register_set_values, quality_preset, power_mode, updated_at
               )
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(serial_number) DO UPDATE SET
                 register_set_values=excluded.register_set_values,
                 quality_preset=COALESCE(excluded.quality_preset, desired_state.quality_preset),
                 power_mode=COALESCE(excluded.power_mode, desired_state.power_mode),
                 updated_at=excluded.updated_at""",
            (
                serial_number,
                json.dumps(register_set_values),
                quality_preset,
                power_mode,
                time.time(),
            ),
        )
        await self._db.commit()

    @staticmethod
    def _row_to_dict(row: aiosqlite.Row) -> dict:
        d = dict(row)
        if d.get("registration") and isinstance(d["registration"], str):
            d["registration"] = json.loads(d["registration"])
        if d.get("status") and isinstance(d["status"], str):
            d["status"] = json.loads(d["status"])
        return d
