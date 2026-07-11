"""Register set templates for initial camera configuration."""

from __future__ import annotations

import time

INITIAL_REGISTER_SET_CAMERA: dict[str, object] = {
    "PIRTargetState": "Armed",
    "PIRStartSensitivity": 80,
    "PIRAction": "Stream",
    "VideoMotionEstimationEnable": False,
    "VideoMotionSensitivity": 80,
    "AudioTargetState": "Disarmed",
    "DefaultMotionStreamTimeLimit": 10,
    "MaxMissedBeaconTime": 30,
    "MaxStreamTimeLimit": 180,
    "MaxUserStreamTimeLimit": 30,
    "MaxMotionStreamTimeLimit": 30,
    "VideoAntiFlickerRate": 60,
    "VideoExposureCompensation": 0,
    "VideoFlip": False,
    "VideoMirror": False,
    "VideoWindowStartX": 0,
    "VideoWindowStartY": 0,
    "VideoWindowEndX": 1280,
    "VideoWindowEndY": 720,
    "NightVisionMode": True,
    "VideoOutputResolution": "1080p",
    "VideoTargetBitrate": 1000,
    "WifiCountryCode": "US",
}

INITIAL_REGISTER_SET_ULTRA: dict[str, object] = {
    **INITIAL_REGISTER_SET_CAMERA,
    "AlertBackoffTime": 0,
    "ArloSmart": True,
    "Audio0EncodeFormat": 0,
    "Audio1EncodeFormat": 1,
    "AudioMicAGC": 0,
    "AudioMicVolume": 4,
    "AudioMicWNS": 0,
    "AudioSpkrEnable": True,
    "ChargeNotificationLed": 1,
    "DefaultMotionStreamTimeLimit": 28,
    "DuskToDawnThrshVal": 26,
    "HdrControl": "auto",
    "HEVCVideoOutputResolution": "2160p",
    "HEVCVideoTargetBitrate": 3000,
    "IRCutState": "engaged",
    "IRLedState": "off",
    "JPEGOutputResolution": "",
    "MaxSensorRequired": True,
    "NightModeGrey": 0,
    "NightModeLightSourceAlert": 1,
    "PIRAction": "Stream+Spotlight",
    "PIRStartSensitivity": 95,
    "PIRTargetState": "Armed",
    "SpotlightDurationManual": 300,
    "SpotlightIntensityAlert": 12593,
    "SpotlightIntensityManual": 12593,
    "SpotlightModeAlert": 0,
    "SpotlightModeManual": 0,
    "VideoMode": "superWide",
    "VideoOutputResolution": "1080p",
    "VideoSmartZoom": "off",
    "VideoTargetBitrate": 1250,
}

INITIAL_REGISTER_SET_FLOODLIGHT: dict[str, object] = {
    **INITIAL_REGISTER_SET_ULTRA,
    "SpotlightIntensityAlert": 25700,
    "SpotlightIntensityManual": 25700,
}

INITIAL_REGISTER_SET_VIDEO_DOORBELL: dict[str, object] = {
    "CallEnableLED": True,
    "LEDPirStatus": True,
    "SilentMode": False,
    "StreamingLedEnabled": True,
    "TradChimePlayDur": 0,
    "TraditionalChime": False,
}

INITIAL_REGISTER_SET_VIDEO_DOORBELL_2: dict[str, object] = {
    "AlertBackoffTime": 0,
    "ArloSmart": True,
    "Audio0EncodeFormat": 0,
    "Audio1EncodeFormat": 1,
    "HdrControl": "auto",
    "MaxMissedBeaconTime": 10,
    "MaxStreamTimeLimit": 1800,
    "NightVisionMode": True,
    "PIRAction": "Snapshot",
    "PIRStartSensitivity": 80,
    "PIRTargetState": "Armed",
    "VideoAntiFlickerRate": 60,
    "VideoExposureCompensation": 0,
    "VideoFlip": False,
    "VideoMirror": False,
    "VideoMotionEstimationEnable": True,
    "VideoMotionSensitivity": 80,
    "VideoOutputResolution": "1536sq",
    "VideoTargetBitrate": 750,
    "WifiCountryCode": "US",
}

INITIAL_REGISTER_SET_AUDIO_DOORBELL: dict[str, object] = {
    "PIRTargetState": "Armed",
    "PIRStartSensitivity": 80,
    "AudioTargetState": "Armed",
    "AudioStartSensitivity": 2,
    "MaxMissedBeaconTime": 10,
}


def build_register_set_message(msg_id: int, set_values: dict) -> dict:
    return {"Type": "registerSet", "ID": msg_id, "SetValues": set_values}


def build_ra_params_message(msg_id: int, params: dict) -> dict:
    return {"Type": "raParams", "ID": msg_id, "Params": params}


def build_status_request_message(msg_id: int) -> dict:
    return {"Type": "statusRequest", "ID": msg_id}


def build_snapshot_message(msg_id: int, url: str) -> dict:
    return {"Type": "fullSnapshot", "ID": msg_id, "DestinationURL": url}


def build_user_stream_active_message(msg_id: int, active: bool) -> dict:
    return {"Type": "registerSet", "ID": msg_id, "SetValues": {"UserStreamActive": 1 if active else 0}}


def build_epoch_time_message(msg_id: int) -> dict:
    return {"Type": "registerSet", "ID": msg_id, "SetValues": {"EpochBsTime": int(time.time())}}


def build_ack_message(msg_id: int) -> dict:
    return {"Type": "response", "ID": msg_id, "Response": "Ack"}
