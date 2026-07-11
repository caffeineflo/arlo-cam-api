from arlo.audio_doorbell import DEVICE_PREFIXES as AUD_DBELL_PFIXES
from arlo.audio_doorbell import AudioDoorbell
from arlo.camera import DEVICE_PREFIXES as CAM_PFIXES
from arlo.camera import Camera
from arlo.video_doorbell import DEVICE_PREFIXES as VID_DBELL_PFIXES
from arlo.video_doorbell import VideoDoorbell


class DeviceFactory:
    @staticmethod
    def create_device(ip, registration):
        model_number = registration["SystemModelNumber"]
        if model_number.startswith(tuple(CAM_PFIXES)):
            device = Camera(ip, registration)
        elif model_number.startswith(tuple(AUD_DBELL_PFIXES)):
            device = AudioDoorbell(ip, registration)
        elif model_number.startswith(tuple(VID_DBELL_PFIXES)):
            device = VideoDoorbell(ip, registration)
        else:
            return None

        device.status = {}
        device.friendly_name = registration["SystemSerialNumber"]
        return device
