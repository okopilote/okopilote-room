from configparser import ConfigParser

from okopilote.devices.common import devices
from . import room
from .api import API


class App:
    rooms = {}
    conf = None
    config_file = ""

    @classmethod
    def _init_config(cls):
        cls.conf = ConfigParser()
        cls.conf.read_dict(
            {
                "common": {
                    "rooms_conf_file": "rooms.conf",
                    "devices_conf_file": "devices.conf",
                },
                "api": {
                    "listen_addr": "127.0.0.1",
                    "listen_port": "8882",
                },
            }
        )
        cls.conf.read_file(open(cls.config_file))
        devices.config_file(cls.conf["common"]["devices_conf_file"])

    @classmethod
    def _init_rooms(cls, old_rooms=None):
        cls.rooms = room.from_file(cls.conf["common"]["rooms_conf_file"])
        for k, v in cls.rooms.items():
            try:
                v.temp_set = old_rooms[k].temp_set
            except (TypeError, KeyError):
                pass
            v.start()

    @classmethod
    def restart(cls):
        for r in cls.rooms.values():
            r.stop()
        cls._init_config()
        cls._init_rooms(cls.rooms)

    @classmethod
    def start(cls, config_file):
        cls.config_file = config_file
        cls._init_config()
        cls._init_rooms()
        myapi = API(
            cls,
            addr=cls.conf["api"]["listen_addr"],
            port=cls.conf["api"]["listen_port"],
        )
        myapi.start()
        for r in cls.rooms.values():
            r.stop()
