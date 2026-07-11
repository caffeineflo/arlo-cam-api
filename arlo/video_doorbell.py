import copy

import arlo.messages
from arlo.camera import Camera
from arlo.messages import Message

DEVICE_PREFIXES = ["AVD"]


class VideoDoorbell(Camera):
    @property
    def port(self):
        return 4000

    def send_initial_register_set(
        self, wifi_country_code, video_anti_flicker_rate=None, video_quality_default="default"
    ):
        register_set = Message(copy.deepcopy(arlo.messages.REGISTER_SET_INITIAL_VID_DOORBELL))
        self.send_message(register_set, 4100)

        register_set = Message(copy.deepcopy(arlo.messages.REGISTER_SET_INITIAL_2_VID_DOORBELL))
        register_set["SetValues"]["WifiCountryCode"] = wifi_country_code
        register_set["SetValues"]["VideoAntiFlickerRate"] = video_anti_flicker_rate
        self.send_message(register_set)

        if video_quality_default == "default":
            video_quality_default = "1536sq"

        self.set_quality({"quality": video_quality_default})

    def set_quality(self, args):
        quality = args["quality"].lower()
        if quality == "720sq":
            ra_params = Message(copy.deepcopy(arlo.messages.RA_PARAMS_VID_DOORBELL))
            register_set = Message(copy.deepcopy(arlo.messages.REGISTER_SET_720SQ))
        elif quality == "1080sq":
            ra_params = Message(copy.deepcopy(arlo.messages.RA_PARAMS_VID_DOORBELL))
            register_set = Message(copy.deepcopy(arlo.messages.REGISTER_SET_1080SQ))
        elif quality == "1536sq":
            ra_params = Message(copy.deepcopy(arlo.messages.RA_PARAMS_VID_DOORBELL))
            register_set = Message(copy.deepcopy(arlo.messages.REGISTER_SET_1536SQ))
        else:
            return False

        return self.send_message(ra_params) and self.send_message(register_set)

    def arm(self, args):
        register_set = Message(copy.deepcopy(arlo.messages.REGISTER_SET))

        pir_target_state = args["PIRTargetState"]
        pir_start_sensitivity = args.get("PIRStartSensitivity") or 80

        register_set["SetValues"] = {
            "PIRTargetState": pir_target_state,
            "PIRStartSensitivity": pir_start_sensitivity,
        }

        return self.send_message(register_set)
