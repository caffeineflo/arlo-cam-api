import copy
import select
import socket
import sqlite3
import threading

import yaml

import api.api
import arlo.messages
from arlo.device_db import DeviceDB
from arlo.device_factory import DeviceFactory
from arlo.messages import Message
from arlo.socket import ArloSocket
from helpers.safe_print import s_print
from helpers.webhook_manager import WebHookManager

with open(r"config.yaml") as file:
    config = yaml.load(file, Loader=yaml.FullLoader)

webhook_manager = WebHookManager(config)

with sqlite3.connect("arlo.db") as conn:
    c = conn.cursor()
    tables = c.execute("SELECT tbl_name FROM sqlite_schema WHERE type='table' AND tbl_name='camera'").fetchall()
    if tables != []:
        c.execute("DROP INDEX IF EXISTS idx_device_serialnumber")
        c.execute("DROP INDEX IF EXISTS idx_device_ip")
        c.execute("DROP INDEX IF EXISTS idx_device_friendlyname")
        c.execute("DROP INDEX IF EXISTS idx_device_hostname")
        c.execute("ALTER TABLE camera RENAME TO devices")

    c.execute(
        "CREATE TABLE IF NOT EXISTS devices "
        "(ip text, serialnumber text, hostname text, status text, register_set text, friendlyname text)"
    )
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_device_serialnumber ON devices (serialnumber)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_device_ip ON devices (ip)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_device_friendlyname ON devices (friendlyname)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_device_hostname ON devices (hostname)")
    conn.commit()


WIFI_COUNTRY_CODE = config.get("WifiCountryCode", "US")
VIDEO_ANTI_FLICKER_RATE = config.get("VideoAntiFlickerRate", 60)
VIDEO_QUALITY_DEFAULT = config.get("VideoQualityDefault", "default")
NOTIFY_ON_MOTION_ALERT = config.get("NotifyOnMotionAlert", True)
NOTIFY_ON_MOTION_TIMEOUT_ALERT = config.get("NotifyOnMotionTimeoutAlert", False)
NOTIFY_ON_AUDIO_ALERT = config.get("NotifyOnAudioAlert", False)
NOTIFY_ON_BUTTON_PRESS_ALERT = config.get("NotifyOnButtonPressAlert", True)
NOTIFY_REGISTERD_AND_STATUS_UPDATE = config.get("NotifyRegisteredAndStatusUpdate", True)


class ConnectionThread(threading.Thread):
    def __init__(self, connection, ip, port):
        threading.Thread.__init__(self)
        self.connection = ArloSocket(connection)
        self.ip = ip
        self.port = port

    def run(self):
        while True:
            msg = self.connection.receive()
            if msg is not None:
                ack = Message(copy.deepcopy(arlo.messages.RESPONSE))
                ack["ID"] = msg["ID"]
                s_print(f">[{self.ip}][{msg['ID']}] Ack")
                self.connection.send(ack)

                if msg["Type"] == "registration":
                    device = DeviceDB.from_db_serial(msg["SystemSerialNumber"])
                    if device is None:
                        device = DeviceFactory.create_device(self.ip, msg)
                    else:
                        device.ip = self.ip
                        device.registration = msg
                    DeviceDB.persist(device)
                    s_print(
                        f"<[{self.ip}][{msg['ID']}] Registration from {msg['SystemSerialNumber']} - {device.hostname}"
                    )

                    device.send_initial_register_set(WIFI_COUNTRY_CODE, VIDEO_ANTI_FLICKER_RATE, VIDEO_QUALITY_DEFAULT)
                    if NOTIFY_REGISTERD_AND_STATUS_UPDATE:
                        webhook_manager.registration_received(
                            device.ip, device.friendly_name, device.hostname, device.serial_number, device.registration
                        )
                elif msg["Type"] == "status":
                    s_print(f"<[{self.ip}][{msg['ID']}] Status from {msg['SystemSerialNumber']}")
                    device = DeviceDB.from_db_serial(msg["SystemSerialNumber"])
                    device.ip = self.ip
                    device.status = msg
                    DeviceDB.persist(device)
                    if NOTIFY_REGISTERD_AND_STATUS_UPDATE:
                        webhook_manager.status_received(
                            device.ip, device.friendly_name, device.hostname, device.serial_number, device.status
                        )
                    device.send_epoch_bs_time()
                elif msg["Type"] == "alert":
                    device = DeviceDB.from_db_ip(self.ip)
                    alert_type = msg["AlertType"]
                    s_print(f"<[{self.ip}][{msg['ID']}] {msg['AlertType']}")
                    if alert_type == "pirMotionAlert":
                        if NOTIFY_ON_MOTION_ALERT:
                            webhook_manager.motion_detected(
                                device.ip,
                                device.friendly_name,
                                device.hostname,
                                device.serial_number,
                                msg["PIRMotion"].get("zones", []),
                                "",
                            )
                    elif alert_type == "audioAlert":
                        if NOTIFY_ON_AUDIO_ALERT:
                            # TODO: implement this
                            ...
                    elif alert_type == "buttonPressAlert":
                        if NOTIFY_ON_BUTTON_PRESS_ALERT:
                            webhook_manager.button_pressed(
                                device.ip,
                                device.friendly_name,
                                device.hostname,
                                device.serial_number,
                                msg["ButtonPress"]["Triggered"],
                            )
                    elif alert_type == "motionTimeoutAlert":
                        if NOTIFY_ON_MOTION_TIMEOUT_ALERT:
                            webhook_manager.motion_timeout(
                                device.ip, device.friendly_name, device.hostname, device.serial_number
                            )
                    else:
                        s_print(f"<[{self.ip}][{msg['ID']}] Unknown alert type")
                        s_print(msg)
                elif msg["Type"] == "logMessage":
                    s_print(f"<[{self.ip}][{msg['ID']}] {msg['LogString']}")
                else:
                    s_print(f"<[{self.ip}][{msg['ID']}] Unknown message")
                    s_print(msg)
                self.connection.close()
                break


class ServerThread(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)

    def run(self):
        threads = []
        servers = []

        for port in [4000, 4100]:
            server_address = ("", port)
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(server_address)
            server.listen(12)
            servers.append(server)

        while True:
            try:
                # Wait for any of the listening servers to get a client
                # connection attempt
                readable, _, _ = select.select(servers, [], [])
                ready_server = readable[0]

                connection, (ip, port) = ready_server.accept()

                new_thread = ConnectionThread(connection, ip, port)
                threads.append(new_thread)
                new_thread.start()
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(e)

        for t in threads:
            t.join()


server_thread = ServerThread()
server_thread.start()
flask_thread = api.api.get_thread()
server_thread.join()
flask_thread.join()
