"""Model-aware capability filtering for register set keys."""

from __future__ import annotations

BASE_CAMERA_KEYS: set[str] = {
    "AudioTargetState",
    "DefaultMotionStreamTimeLimit",
    "EpochBsTime",
    "MaxMissedBeaconTime",
    "MaxMotionStreamTimeLimit",
    "MaxStreamTimeLimit",
    "MaxUserStreamTimeLimit",
    "NightVisionMode",
    "PIRAction",
    "PIRStartSensitivity",
    "PIRTargetState",
    "VideoAntiFlickerRate",
    "VideoExposureCompensation",
    "VideoFlip",
    "VideoMirror",
    "VideoMotionEstimationEnable",
    "VideoMotionSensitivity",
    "VideoOutputResolution",
    "VideoTargetBitrate",
    "VideoWindowEndX",
    "VideoWindowEndY",
    "VideoWindowStartX",
    "VideoWindowStartY",
    "WifiCountryCode",
}

ULTRA_EXTRA_KEYS: set[str] = {
    "AlertBackoffTime",
    "ArloSmart",
    "Audio0EncodeFormat",
    "Audio1EncodeFormat",
    "AudioMicAGC",
    "AudioMicVolume",
    "AudioMicWNS",
    "AudioSpkrEnable",
    "ChargeNotificationLed",
    "DuskToDawnThrshVal",
    "HEVCVideoOutputResolution",
    "HEVCVideoTargetBitrate",
    "HdrControl",
    "IRCutState",
    "IRLedState",
    "JPEGOutputResolution",
    "MaxSensorRequired",
    "NightModeGrey",
    "NightModeLightSourceAlert",
    "SpotlightDurationManual",
    "SpotlightIntensityAlert",
    "SpotlightIntensityManual",
    "SpotlightModeAlert",
    "SpotlightModeManual",
    "VideoMode",
    "VideoSmartZoom",
}

FLOODLIGHT_EXTRA_KEYS: set[str] = set()

MODEL_CAPABILITIES: dict[str, set[str]] = {
    "VMC3030": BASE_CAMERA_KEYS,
    "VMC3040": BASE_CAMERA_KEYS,
    "VMC4030": BASE_CAMERA_KEYS | ULTRA_EXTRA_KEYS,
    "VMC4040": BASE_CAMERA_KEYS | ULTRA_EXTRA_KEYS,
    "VMC4050": BASE_CAMERA_KEYS | ULTRA_EXTRA_KEYS,
    "VMC5040": BASE_CAMERA_KEYS | ULTRA_EXTRA_KEYS,
    "VMC4060": BASE_CAMERA_KEYS | ULTRA_EXTRA_KEYS | FLOODLIGHT_EXTRA_KEYS,
    "VML4030": BASE_CAMERA_KEYS | ULTRA_EXTRA_KEYS,
    "VML2030": BASE_CAMERA_KEYS,
    "FB1001": BASE_CAMERA_KEYS | ULTRA_EXTRA_KEYS | FLOODLIGHT_EXTRA_KEYS,
}


def get_supported_keys(model: str, registration: dict | None = None) -> set[str]:
    """Get supported register set keys for a model.

    Falls back to BASE_CAMERA_KEYS if model is unknown.
    If the registration message includes a Capabilities array, uses that
    to augment the known set.
    """
    keys = MODEL_CAPABILITIES.get(model, BASE_CAMERA_KEYS).copy()

    if registration:
        caps = registration.get("Capabilities", [])
        if caps:
            keys.update(caps)

    return keys


def filter_register_set(values: dict, model: str, registration: dict | None = None) -> dict:
    """Filter a register set dict to only keys supported by the model."""
    supported = get_supported_keys(model, registration)
    return {k: v for k, v in values.items() if k in supported}
