# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
import json
import logging
from configparser import ConfigParser
from math import isnan
from threading import Thread, Event, Lock
from time import time
from collections import deque

from okopilote.devices.common import devices

from .scheduler import TemperatureScheduler

logger = logging.getLogger(__name__)


def from_file(rooms_conf_file):
    rconf = ConfigParser()
    rconf.read_dict(
        {
            "DEFAULT": {
                "label": "no label",
                "period": "10.0",
                "temperature_sensor_device": "",
                "temperature_sample_size": "6",
                "temperature_set": "16.0",
                "temperature_set_default_offset": "0",
                "window_detection": "on",
                "window_sample_size": "36",
                "window_threshold": "0.5",
                "window_duration": "300.0",
                "radiator_valve_device": "",
                "humidity_sensor_device": "",
                "data_dir": "data",
            }
        }
    )
    rconf.read_file(open(rooms_conf_file))
    rooms = {}
    for k in rconf.sections():
        conf = rconf[k]
        rooms[k] = Room(
            k,
            label=conf["label"],
            period=conf.getfloat("period"),
            temperature_sensor=devices.get_device(conf["temperature_sensor_device"]),
            temperature_sample_size=conf.getint("temperature_sample_size"),
            temperature_set=conf.getfloat("temperature_set"),
            temperature_set_default_offset=conf.getfloat(
                "temperature_set_default_offset"
            ),
            window_detection=conf.getboolean("window_detection"),
            window_sample_size=conf.getint("window_sample_size"),
            window_threshold=conf.getfloat("window_threshold"),
            window_duration=conf.getfloat("window_duration"),
            radiator_valve_device=devices.get_device(conf["radiator_valve_device"]),
            humidity_sensor_device=devices.get_device(conf["humidity_sensor_device"]),
            data_dir=conf.get("data_dir"),
        )
    return rooms


class Room(Thread):
    """
    A room representation (with sensors like temperature) which runs in a
    separate thread.
    """

    VALVE_CLOSE = 3
    VALVE_OPEN = 2
    VALVE_RELEASE = 1

    circulator_runs_pushed = None
    pushed_expiration = 1200

    @classmethod
    def push_circulator_state(cls, state):
        cls.circulator_runs_pushed = (bool(state), time())

    def __init__(
        self,
        room_id,
        label="no label",
        period=5.0,
        temperature_sensor=None,
        temperature_sample_size=6,
        temperature_set=16.0,
        temperature_set_default_offset=0.0,
        window_detection=True,
        window_sample_size=36,
        window_threshold=0.5,
        window_duration=300.0,
        radiator_valve_device=None,
        humidity_sensor_device=None,
        data_dir=None,
    ):

        super().__init__(name=room_id)
        self.room_id = room_id
        self.label = label
        self.period = round(period, 1)
        self.event = Event()
        self.errors = []
        self.conf = {}
        self.conf_file = "{}/{}.json".format(data_dir, room_id)
        self.lock_file = Lock()

        # Temperature data
        self.temp_sensor = temperature_sensor
        self.temp_sample = deque(maxlen=temperature_sample_size)
        self.temp_set = round(temperature_set, 1)
        self.temp_set_offset_default = temperature_set_default_offset
        self.temp = None
        self.temp_predict = None
        self.temp_set_lock = Lock()
        self.temp_set_offset = 0.0
        self.temp_set_offset_pushed = None
        self.temp_deviation = None
        self.temp_controlled = False
        # Window data
        self.wind_detection = window_detection
        self.wind_sample = deque(maxlen=window_sample_size)
        self.wind_threshold = round(window_threshold, 1)
        self.wind_duration = round(window_duration, 1)
        self.wind_opened = None
        self.wind_time = 0
        # Radiator valve data
        self.valve = radiator_valve_device
        self.valve_order = None
        # Heat water circulator data
        self.circulator_runs = None
        # Humidity data
        self.humid_sensor = humidity_sensor_device
        self.humid_sample = deque(maxlen=6)
        # Scheduler for temp_set
        self.sched = TemperatureScheduler(
            self,
            room_file="{}/{}_scheduler.json".format(data_dir, room_id),
            common_file="{}/common_scheduler.json".format(data_dir),
        )

        if self.conf_file:
            try:
                with self.lock_file, open(self.conf_file, "r") as f:
                    self.conf = json.load(f)
                    try:
                        if not isnan(float(self.conf["temp_set"])):
                            self.temp_set = float(self.conf["temp_set"])
                        else:
                            del self.conf["temp_set"]
                    except KeyError:
                        pass
            except FileNotFoundError:
                pass

    def _save_to_persistent(self):
        if self.conf_file:
            if not isnan(self.temp_set):
                self.conf["temp_set"] = self.temp_set
            # Dump in a string to protect the file from a JSON exception
            s = json.dumps(self.conf, indent=4)
            try:
                with self.lock_file, open(self.conf_file, "w") as f:
                    f.write(s)
            except OSError as e:
                msg = 'Failed to write to "{}": {}'.format(self.conf_file, e)
                self.errors.append(msg)
                logger.error("Room {}: {}".format(self.room_id, msg))

    def run(self):
        """
        Acquire endlessly data from sensors.
        """

        logger.debug('room "{}": start room id "{}"'.format(self.label, self.room_id))

        # Start infinite loop that acquire measures
        try:
            while not self.event.is_set():
                if self.temp_sensor:
                    self._do_stuff()
                self.event.wait(self.period)
        except Exception as e:
            if self.valve is not None:
                try:
                    self.valve.release()
                except Exception as ee:
                    self.errors.append(
                        ("Failed to release the valve before " + "crashing: {}").format(
                            ee
                        )
                    )
                    logger.exception("{}: {}".format(self.room_id, self.errors[-1]))
            self.errors.append("FATAL ERROR: {}".format(e))
            logger.exception("{}: {}".format(self.room_id, self.errors[-1]))

    def _do_stuff(self):
        errors = []
        # Acquire temperature and humidity
        (temp, humid) = (None, None)
        if self.temp_sensor is self.humid_sensor:
            if self.temp_sensor is not None:
                try:
                    (temp, humid) = self.temp_sensor.temperature_humidity()
                except Exception as e:
                    errors.append(
                        ("Failed to read temperature and humidity: " + "{}").format(e)
                    )
                    logger.error("{}: {}".format(self.room_id, errors[-1]))
        else:
            if self.temp_sensor is not None:
                try:
                    temp = self.temp_sensor.temperature()
                except Exception as e:
                    errors.append("Failed to read temperature: {}".format(e))
                    logger.error("{}: {}".format(self.room_id, errors[-1]))
            if self.humid_sensor is not None:
                try:
                    humid = self.humid_sensor.humidity()
                except Exception as e:
                    errors.append("Failed to read humidity: {}".format(e))
                    logger.error("{}: {}".format(self.room_id, errors[-1]))
        self.temp_sample.append(temp)
        self.wind_sample.append(temp)
        self.humid_sample.append(humid)

        #  Compute average temperature
        # sum_, count = 0, 0
        # for val in self.temp_sample:
        #     if val is not None:
        #         sum_ += val
        #         count += 1
        # if count >= round(0.7 * self.temp_sample.maxlen, 0):
        #     self.temp = round(sum_ / count, 1)
        # else:
        #     self.temp = None
        sample = [v for v in self.temp_sample if v is not None]
        if len(sample) >= round(0.7 * self.temp_sample.maxlen, 0):
            self.temp = round(sum(sample) / len(sample), 1)
        else:
            self.temp = None

        # Compute humidity
        try:
            self.humid = [v for v in self.humid_sample if v is not None][-1]
        except IndexError:
            pass

        # Compute predictable temperature we expect in inertie time
        # WISH LIST: compute a linear regression?
        self.temp_predict = self.temp
        # Run the scheduler for the temperature set
        try:
            self.sched.run_pending()
        except Exception as e:
            errors.append(("Failed to run scheduler: {}").format(e))
            logger.error("{}: {}".format(self.room_id, errors[-1]))
        # Compute Window state
        self.wind_opened = self._detect_opened_window()
        # Use temperature setpoint offset if not expired, or use default value
        t_set_offset = self.temp_set_offset_pushed
        if t_set_offset and t_set_offset[1] > time() - self.pushed_expiration:
            self.temp_set_offset = t_set_offset[0]
            self.temp_controlled = True
        else:
            self.temp_set_offset = self.temp_set_offset_default
            self.temp_controlled = False

        # Compute deviation from setpoint+offset to predict temperature
        temp_dev = None
        if not self.wind_opened:
            try:
                temp_dev = round(self.temp_predict - self.temp_set, 1)
                temp_dev = round(temp_dev - self.temp_set_offset, 1)
            except TypeError:
                pass
        self.temp_deviation = temp_dev

        # Read circulator state or acquire it
        circul_runs = self.circulator_runs_pushed
        if circul_runs and circul_runs[1] > (time() - self.pushed_expiration):
            self.circulator_runs = circul_runs[0]
        else:
            # TODO: get circulator state on our own
            self.circulator_runs = None

        # Take decision to open, close or release valve
        if not self.circulator_runs:
            self.valve_order = self.VALVE_RELEASE
        elif self.wind_opened:
            self.valve_order = self.VALVE_CLOSE
        elif self.temp_deviation is None:
            self.valve_order = self.VALVE_RELEASE
        elif self.temp_deviation >= 0:
            self.valve_order = self.VALVE_CLOSE
        else:
            self.valve_order = self.VALVE_OPEN

        # Apply decision
        if self.valve:
            try:
                if self.valve_order == self.VALVE_CLOSE:
                    self.valve.close()
                elif self.valve_order == self.VALVE_OPEN:
                    self.valve.open()
                else:
                    self.valve.release()
            except Exception as e:
                errors.append("Failed to manoeuvre the valve: {}".format(e))
                logger.error("{}: {}".format(self.room_id, errors[-1]))

        self.errors = errors
        # logger.debug('room {}: temp_sample=[{}], average_temp={}'.format(
        #          self.room_id, self.temp_sample, value))
        # logger.debug(('room {}: window_sample=[{}], sample_max={}, '
        #               + 'window_time_relative_to_now={}').format(
        #                   self.room_id, self.wind_sample, maxi,
        #                   int(self.wind_time - time())))

    def temperature_deviation(self, setpoint_offset=None):
        """
        Get the room temperature deviation in reference to the setpoint.
        The value may be an extrapolation from the current measures.
        """
        if setpoint_offset is not None:
            offset = setpoint_offset
            self.temp_set_offset_pushed = (setpoint_offset, time())
        else:
            offset = 0

        temp_dev = None
        if not self.wind_opened:
            try:
                temp_dev = round(self.temp_predict - self.temp_set, 1)
                temp_dev = round(temp_dev - offset, 1)
            except TypeError:
                pass
        return temp_dev

    def _detect_opened_window(self):
        """
        Return True if we know that a window has been opened recently, False
            otherwise.
        """
        if not self.wind_detection:
            return None
        else:
            sample = [v for v in self.wind_sample if v is not None]
            # Not enough data available
            if len(sample) < 2 * self.temp_sample.maxlen:
                return False
            # A window opening is detected when the temperature falls too
            # much during the sample.
            maxi = -42.0
            for t in sample:
                if maxi - t >= self.wind_threshold:
                    # Report only when the previous opening is older than
                    # window sample duration.
                    if self.wind_time < (time() - len(self.wind_sample) * self.period):
                        logger.info(
                            ('room "{}": opened window detected!').format(self.label)
                        )
                    self.wind_time = time()
                    break
                elif t > maxi:
                    maxi = t
            return time() - self.wind_time < self.wind_duration

    def set_temp_set(self, T):
        """
        Set temperature setpoint.
        Arguments:
            T: the new temperature setpoint in °C.
        """
        logger.info(
            ("room {}: temperature setpoint is set to the new " + "value: {}°C").format(
                self.room_id, T
            )
        )
        with self.temp_set_lock:
            self.temp_set = round(T, 1)
        self._save_to_persistent()

    def stop(self):
        """
        Stop thread.
        """
        logger.debug('room "{}": stop room'.format(self.label))
        self.event.set()
