"""Quality presets for video bitrate and resolution."""

from __future__ import annotations

QUALITY_REGISTER_SETS: dict[str, dict] = {
    "low": {
        "VideoOutputResolution": "720p",
        "VideoTargetBitrate": 400,
    },
    "medium": {
        "VideoOutputResolution": "1080p",
        "VideoTargetBitrate": 600,
    },
    "high": {
        "VideoOutputResolution": "1080p",
        "VideoTargetBitrate": 1250,
    },
    "subscription": {
        "VideoOutputResolution": "1080p",
        "VideoTargetBitrate": 1250,
    },
    "insane": {
        "VideoOutputResolution": "1080p",
        "VideoTargetBitrate": 2000,
    },
}

RA_PARAMS: dict[str, dict] = {
    "low": {
        "1080p": {"minbps": 102400, "maxbps": 532480, "minQP": 24, "maxQP": 38, "vbr": True, "targetbps": 409600, "cbrbps": 409600},
        "4K": {"minbps": 307200, "maxbps": 2048000, "minQP": 26, "maxQP": 38, "vbr": True, "targetbps": 1024000, "cbrbps": 1024000},
        "360p": {"minbps": 51200, "maxbps": 307200, "minQP": 24, "maxQP": 38, "vbr": True, "targetbps": 102400, "cbrbps": 102400},
        "480p": {"minbps": 51200, "maxbps": 409600, "minQP": 24, "maxQP": 38, "vbr": True, "targetbps": 307200, "cbrbps": 307200},
        "720p": {"minbps": 51200, "maxbps": 532480, "minQP": 24, "maxQP": 38, "vbr": True, "targetbps": 409600, "cbrbps": 409600},
    },
    "medium": {
        "1080p": {"minbps": 102400, "maxbps": 640000, "minQP": 24, "maxQP": 38, "vbr": True, "targetbps": 512000, "cbrbps": 512000},
        "4K": {"minbps": 307200, "maxbps": 3072000, "minQP": 26, "maxQP": 38, "vbr": True, "targetbps": 1536000, "cbrbps": 2048000},
        "360p": {"minbps": 51200, "maxbps": 409600, "minQP": 24, "maxQP": 38, "vbr": True, "targetbps": 204800, "cbrbps": 204800},
        "480p": {"minbps": 51200, "maxbps": 409600, "minQP": 24, "maxQP": 38, "vbr": True, "targetbps": 409600, "cbrbps": 409600},
        "720p": {"minbps": 51200, "maxbps": 599040, "minQP": 24, "maxQP": 38, "vbr": True, "targetbps": 460800, "cbrbps": 460800},
    },
    "high": {
        "1080p": {"minbps": 102400, "maxbps": 819200, "minQP": 35, "maxQP": 40, "vbr": True, "targetbps": 614400, "cbrbps": 614400},
        "4K": {"minbps": 307200, "maxbps": 5120000, "minQP": 26, "maxQP": 38, "vbr": True, "targetbps": 3072000, "cbrbps": 3072000},
        "360p": {"minbps": 51200, "maxbps": 512000, "minQP": 24, "maxQP": 38, "vbr": True, "targetbps": 409600, "cbrbps": 409600},
        "480p": {"minbps": 51200, "maxbps": 614400, "minQP": 24, "maxQP": 38, "vbr": True, "targetbps": 512000, "cbrbps": 512000},
        "720p": {"minbps": 51200, "maxbps": 665600, "minQP": 24, "maxQP": 38, "vbr": True, "targetbps": 512000, "cbrbps": 512000},
    },
    "subscription": {
        "1080p": {"minbps": 102400, "maxbps": 1228800, "minQP": 24, "maxQP": 38, "vbr": True, "targetbps": 1024000, "cbrbps": 1024000},
        "4K": {"minbps": 307200, "maxbps": 8192000, "minQP": 22, "maxQP": 35, "vbr": True, "targetbps": 6144000, "cbrbps": 6144000},
        "360p": {"minbps": 51200, "maxbps": 512000, "minQP": 24, "maxQP": 38, "vbr": True, "targetbps": 409600, "cbrbps": 409600},
        "480p": {"minbps": 51200, "maxbps": 614400, "minQP": 24, "maxQP": 38, "vbr": True, "targetbps": 512000, "cbrbps": 512000},
        "720p": {"minbps": 51200, "maxbps": 1024000, "minQP": 24, "maxQP": 38, "vbr": True, "targetbps": 768000, "cbrbps": 768000},
    },
    "insane": {
        "1080p": {"minbps": 204800, "maxbps": 2097152, "minQP": 12, "maxQP": 24, "vbr": True, "targetbps": 2048000, "cbrbps": 2048000},
        "4K": {"minbps": 614400, "maxbps": 10240000, "minQP": 1, "maxQP": 1, "vbr": False, "targetbps": 10240000, "cbrbps": 10240000},
        "360p": {"minbps": 51200, "maxbps": 512000, "minQP": 24, "maxQP": 38, "vbr": True, "targetbps": 409600, "cbrbps": 409600},
        "480p": {"minbps": 51200, "maxbps": 614400, "minQP": 24, "maxQP": 38, "vbr": True, "targetbps": 512000, "cbrbps": 512000},
        "720p": {"minbps": 51200, "maxbps": 1024000, "minQP": 24, "maxQP": 38, "vbr": True, "targetbps": 768000, "cbrbps": 768000},
    },
}
