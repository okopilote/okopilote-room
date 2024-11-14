import json
import logging
import re
from datetime import date
from schedule import Scheduler
from time import time
from threading import Lock

logger = logging.getLogger(__name__)

weekdays = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


class RoomSchedulerError:
    pass


class TemperatureScheduler:

    def __init__(self, room, room_file, common_file):
        self.room = room
        self.room_file = room_file
        self.common_file = common_file
        self.last_set = (None, None)
        self.lock = Lock()
        self.onetime_sched = {}
        self.weekly_enabled = True
        self.weekly_new = False
        self.weekly_sched = Scheduler()
        self.weekly_suspended = False
        self.weekly_temp = None
        # Minimal and default configuration
        self.hourly_presets = {"get_up": "08:00", "bedtime": "21:00"}
        self.temp_presets = {"here": 18.0, "away": 16.0, "sleeping": 17.0}
        self.daily_presets = {"at_home": [("get_up", "here"), ("bedtime", "sleeping")]}
        self.weekly_scheduling = {
            "monday": None,
            "tuesday": None,
            "wednesday": None,
            "thursday": None,
            "friday": None,
            "saturday": None,
            "sunday": None,
        }
        # Load common file
        FileNotFoundError = Exception
        try:
            with open(self.common_file, "r") as f:
                conf = json.load(f)
                self.daily_presets.update(conf["daily_presets"])
        except FileNotFoundError:
            pass
        # Load room file
        try:
            with open(self.room_file, "r") as f:
                conf = json.load(f)
                self.temp_presets.update(conf["temp_presets"])
                self.hourly_presets.update(conf["hourly_presets"])
                self.onetime_sched.update(conf["onetime_scheduling"])
                self.weekly_enabled = conf["enable_weekly_scheduling"]
                for k in self.weekly_scheduling:
                    self.weekly_scheduling[k] = conf["weekly_scheduling"][k]
        except FileNotFoundError:
            pass
        for k, v in self.weekly_scheduling.items():
            if v:
                self.schedule_daily_preset(day=k, preset=v, persistent=False)

        # Check config correctness
        for t in self.temp_presets.values():
            self._parse_temp(t)
        for h in self.hourly_presets.values():
            self._parse_hour(h)
        for d in self.daily_presets.values():
            d["label"]
            for h, t in d["hour-temp"].items():
                self._parse_hour(h)
                self._parse_temp(t)
        if self.onetime_sched:
            self.onetime_sched["at"]
            if self.onetime_sched["action"] == "set":
                self.onetime_sched["temp"]
            elif not self.onetime_sched["action"] == "resume_weekly":
                raise ValueError("Incorrect value for onetime schedule action")

        # Get the last weekly temperature set
        if self.weekly_sched.jobs:
            self.weekly_temp = sorted(self.weekly_sched.jobs)[-1].job_func.args[0]

    def _save_to_persistent(self):
        # Save to common file
        conf = {"daily_presets": self.daily_presets}
        # Dump into a string to protect the file from a JSON error
        s = json.dumps(conf, indent=4)
        try:
            with open(self.common_file, "w") as f:
                f.write(s)
        except OSError as e:
            msg = "Unable to save configuration on disk: {}".format(e)
            logger.error("Room {}: {}".format(self.room.room_id, msg))
            raise RoomSchedulerError(msg)
        # Save to room file
        conf = {
            "onetime_scheduling": self.onetime_sched,
            "enable_weekly_scheduling": self.weekly_enabled,
            "weekly_scheduling": self.weekly_scheduling,
            "hourly_presets": self.hourly_presets,
            "temp_presets": self.temp_presets,
        }
        s = json.dumps(conf, indent=4)
        try:
            with open(self.room_file, "w") as f:
                f.write(s)
        except OSError as e:
            msg = "Unable to save configuration on disk: {}".format(e)
            logger.error("Room {}: {}".format(self.room.room_id, msg))

    def _parse_hour(self, hour):
        h = hour
        try:
            h = self.hourly_presets[hour]
        except KeyError:
            pass
        if re.match("[0-9][0-9]:[0-9][0-9]$", h):
            return h
        else:
            raise ValueError("Not an hour preset nor an hour syntax: {}".format(hour))

    def _parse_temp(self, temp):
        if temp is not None:
            t = temp
            try:
                t = self.temp_presets[t]
            except KeyError:
                pass
            try:
                return float(t)
            except ValueError:
                raise ValueError(
                    "Not a temperature preset nor a float: {}".format(temp)
                )

    def _job_temp(self, temp):
        self.weekly_temp = temp
        self.weekly_new = True

    def current_mode(self):
        with self.lock:
            if self.onetime_sched and (
                self.weekly_suspended
                or not self.weekly_enabled
                or not self.weekly_sched.jobs
                or self.onetime_sched["at"] <= self.weekly_sched.next_run.timestamp()
            ):
                return "Onetime"
            elif self.weekly_enabled:
                weekday_name = weekdays[date.today().weekday()]
                preset = self.weekly_scheduling[weekday_name]
                if preset is not None:
                    return self.daily_presets[preset]["label"]

    def disable_weekly(self):
        with self.lock:
            self.weekly_enabled = False
            self._save_to_persistent()

    def enable_weekly(self):
        with self.lock:
            self.weekly_enabled = True
            self._save_to_persistent()

    def next_schedule(self):
        with self.lock:
            if self.weekly_sched.next_run:
                next_w_sched = self.weekly_sched.next_run.timestamp()
            else:
                next_w_sched = None
            if self.onetime_sched:
                if self.onetime_sched["suspend_at"] and (
                    not next_w_sched or self.onetime_sched["suspend_at"] <= next_w_sched
                ):
                    return {
                        "mode": "onetime",
                        "preset_l": None,
                        "time": self.onetime_sched["suspend_at"],
                        "action": "suspend_weekly",
                        "temp": None,
                    }
                elif not next_w_sched or self.onetime_sched["at"] <= next_w_sched:
                    return {
                        "mode": "onetime",
                        "preset_l": None,
                        "time": self.onetime_sched["at"],
                        "action": self.onetime_sched["action"],
                        "temp": self.onetime_sched.get("temp"),
                    }

            if self.weekly_enabled and not self.weekly_suspended and next_w_sched:
                next_job = sorted(self.weekly_sched.jobs)[0]
                day = list(next_job.tags)[0]
                preset = self.weekly_scheduling[day]
                return {
                    "mode": "weekly",
                    "preset_l": self.daily_presets[preset]["label"],
                    "time": next_w_sched,
                    "action": "set",
                    "temp": next_job.job_func.args[0],
                }
            else:
                return None

    def run_pending(self):
        with self.lock:
            self.weekly_new = False
            self.weekly_sched.run_pending()
            temp = None
            # Get one time temperature set, if any
            if self.onetime_sched and self.onetime_sched["at"] <= time():
                if self.onetime_sched["action"] == "set":
                    temp = self.onetime_sched["temp"]
                elif self.onetime_sched["action"] == "resume_weekly":
                    temp = self.weekly_temp
                self.onetime_sched = {}
                self._save_to_persistent()
            # Suspend or not weekly temperature set
            if (
                self.onetime_sched
                and self.onetime_sched["suspend"]
                and (
                    not self.onetime_sched["suspend_at"]
                    or self.onetime_sched["suspend_at"] <= time()
                )
            ):
                self.weekly_suspended = True
            else:
                self.weekly_suspended = False
        # Fall back to weekly scheduling
        if (
            temp is None
            and self.weekly_enabled
            and not self.weekly_suspended
            and self.weekly_new
        ):
            temp = self.weekly_temp
        # Apply the new temperature set
        if temp is not None:
            parsed_temp = self._parse_temp(temp)
            self.room.set_temp_set(parsed_temp)
            self.last_set = (parsed_temp, time())

    def schedule_daily_preset(self, day, preset, persistent=True):
        with self.lock:
            self.weekly_sched.clear(day)
            for h, t in self.daily_presets[preset]["hour-temp"].items():
                job = getattr(self.weekly_sched.every(), day)
                job.at(self._parse_hour(h)).do(self._job_temp, t).tag(day)
            self.weekly_scheduling[day] = preset
            if persistent:
                self._save_to_persistent()

    def schedule_onetime_temp(
        self, time, temp, suspend_weekly_sched=False, suspend_at=None
    ):
        parsed_temp = self._parse_temp(temp)
        with self.lock:
            self.onetime_sched = {
                "at": time,
                "action": "set",
                "temp": parsed_temp,
                "suspend": suspend_weekly_sched,
                "suspend_at": suspend_at,
            }
            self._save_to_persistent()

    def schedule_weekly_resumption(self, time, suspend_at=None):
        with self.lock:
            self.onetime_sched = {
                "at": time,
                "action": "resume_weekly",
                "suspend": True,
                "suspend_at": suspend_at,
            }
            self._save_to_persistent()


if __name__ in ["__main__", "__console__"]:

    class Room:
        def __init__(self):
            self.temp_set = 12.0
            self.errors = []
            self.room_id = "Bebe2"

        def set_temp_set(self, x):
            self.temp_set = x
            print("---->>> NEW SET: {}".format(x))

    r = Room()
    s = TemperatureScheduler(
        r, "../data/bebe2_scheduler.json", "../data/common_scheduler.json"
    )

    def d(obj):
        for k, v in vars(obj).items():
            print(k, ":", v)
