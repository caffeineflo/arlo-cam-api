from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"extra": "ignore"}

    wifi_country_code: str = "US"
    video_anti_flicker_rate: int = 60
    video_quality_default: Literal[
        "low",
        "medium",
        "high",
        "subscription",
        "insane",
    ] = "insane"

    notify_on_motion_alert: bool = True
    notify_on_motion_timeout_alert: bool = False
    notify_on_audio_alert: bool = False
    notify_on_button_press_alert: bool = True
    notify_registered_and_status_update: bool = True

    motion_recording_webhook_url: str = ""
    status_update_webhook_url: str = ""
    registration_webhook_url: str = ""
    button_press_webhook_url: str = ""
    motion_timeout_webhook_url: str = ""
    audio_recording_webhook_url: str = ""

    database_path: str = "/data/arlo.db"
    snapshot_cache_ttl: int = 300
    device_offline_threshold: int = 300
    webhook_retries: int = 3
    webhook_timeout: int = 5
    log_level: str = "INFO"

    camera_port: int = Field(default=4000)
    doorbell_port: int = Field(default=4100)
    api_port: int = Field(default=5000)

    go2rtc_enabled: bool = True
    go2rtc_config_path: str = "/data/go2rtc.yaml"
    go2rtc_rtsp_port: int = 8554
    go2rtc_api_port: int = 1984
    go2rtc_api_url: str = ""
    go2rtc_api_username: str = ""
    go2rtc_api_password: str = ""
    go2rtc_require_api_auth: bool = False
    go2rtc_start_timeout: int = 90

    @model_validator(mode="after")
    def validate_go2rtc_api_credentials(self):
        if bool(self.go2rtc_api_username) != bool(self.go2rtc_api_password):
            raise ValueError("go2rtc API username and password must both be set or both be empty")
        if self.go2rtc_require_api_auth and not self.go2rtc_api_username:
            raise ValueError("go2rtc API credentials are required for this deployment")
        return self


_YAML_KEY_MAP = {
    "WifiCountryCode": "wifi_country_code",
    "VideoAntiFlickerRate": "video_anti_flicker_rate",
    "VideoQualityDefault": "video_quality_default",
    "NotifyOnMotionAlert": "notify_on_motion_alert",
    "NotifyOnMotionTimeoutAlert": "notify_on_motion_timeout_alert",
    "NotifyOnAudioAlert": "notify_on_audio_alert",
    "NotifyOnButtonPressAlert": "notify_on_button_press_alert",
    "NotifyRegisteredAndStatusUpdate": "notify_registered_and_status_update",
    "MotionRecordingWebHookUrl": "motion_recording_webhook_url",
    "StatusUpdateWebHookUrl": "status_update_webhook_url",
    "RegistrationWebHookUrl": "registration_webhook_url",
    "ButtonPressWebHookUrl": "button_press_webhook_url",
    "MotionTimeoutWebHookUrl": "motion_timeout_webhook_url",
    "AudioRecordingWebHookUrl": "audio_recording_webhook_url",
    "DatabasePath": "database_path",
    "SnapshotCacheTTL": "snapshot_cache_ttl",
    "DeviceOfflineThreshold": "device_offline_threshold",
    "WebhookRetries": "webhook_retries",
    "WebhookTimeout": "webhook_timeout",
    "LogLevel": "log_level",
    "Go2RTCEnabled": "go2rtc_enabled",
    "Go2RTCConfigPath": "go2rtc_config_path",
    "Go2RTCRTSPPort": "go2rtc_rtsp_port",
    "Go2RTCAPIPort": "go2rtc_api_port",
    "Go2RTCApiUrl": "go2rtc_api_url",
    "Go2RTCApiUsername": "go2rtc_api_username",
    "Go2RTCApiPassword": "go2rtc_api_password",
    "Go2RTCRequireApiAuth": "go2rtc_require_api_auth",
    "Go2RTCStartTimeout": "go2rtc_start_timeout",
}


def load_settings(config_path: str = "config.yaml") -> Settings:
    path = Path(config_path)
    if not path.exists():
        return Settings()

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    mapped = {}
    for yaml_key, value in raw.items():
        settings_key = _YAML_KEY_MAP.get(yaml_key, yaml_key)
        mapped[settings_key] = value

    return Settings(**mapped)
