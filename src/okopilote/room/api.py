import json
from bottle import Bottle, JSONPlugin, abort, request, response

# from bottle import static_file, view

from .room import Room


class API:

    def __init__(self, app, addr="0.0.0.0", port="8882"):
        self.app = app
        self.addr = addr
        self.port = port

    def start(self):
        mybottle = Bottle()

        def id_to_rooms(rooms_id):
            if rooms_id == "all":
                return self.app.rooms
            else:
                return {rooms_id: self.app.rooms[rooms_id]}

        @mybottle.hook("after_request")
        def enable_CORS():
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = (
                "Origin, X-Requested-With, Content-Type, Accept"
            )

        @mybottle.route("/", method="OPTIONS")
        @mybottle.route("/<any:path>", method="OPTIONS")
        def enable_OPTIONS_method(any=None):
            pass

        @mybottle.get("/api/rooms/<room_id>")
        def api_room(room_id):
            rooms = id_to_rooms(room_id)
            data = {}
            for id_, r in rooms.items():
                data[id_] = {
                    k: v
                    for k, v in vars(r).items()
                    if k
                    in [
                        "errors",
                        "label",
                        "room_id",
                        "temp",
                        "temp_controlled",
                        "temp_set",
                        "temp_set_offset",
                        "valve_order",
                        "wind_opened",
                    ]
                }
                data[id_]["is_alive"] = r.is_alive()
                try:
                    data[id_]["sched_curr_mode"] = r.sched.current_mode()
                except Exception as e:
                    data[id_]["errors"].append(e)
            return data

        @mybottle.post("/api/rooms/<room_id>/controller_sync")
        def api_room_controller_sync(room_id):
            rooms = id_to_rooms(room_id)
            data = {id_: {} for id_ in rooms}
            for k, v in request.json.items():
                if k == "temp_set_offset":
                    for id_, r in rooms.items():
                        data[id_]["temp_deviation"] = r.temperature_deviation(float(v))
                elif k == "circulator_runs":
                    Room.push_circulator_state(bool(v))
                else:
                    abort('unknown key: "{}={}"'.format(k, v))
            return data

        @mybottle.get("/api/rooms/<room_id>/dump")
        def api_room_dump(room_id):
            rooms = id_to_rooms(room_id)
            data = {}
            data["all"] = {
                k: v
                for k, v in vars(Room).items()
                if k[0] != "_" and not isinstance(v, type(lambda: None))
            }
            for id_, r in rooms.items():
                data[id_] = {k: v for k, v in vars(r).items() if k[0] != "_"}
                data[id_]["is_alive"] = r.is_alive()
                data[id_]["sched"] = {
                    k: v for k, v in vars(r.sched).items() if k[0] != "_"
                }
                data[id_]["sched"]["next_schedule"] = r.sched.next_schedule()
                data[id_]["sched"]["weekly_sched"] = r.sched.weekly_sched.jobs
            return data

        @mybottle.get("/api/rooms/<room_id>/sched")
        def api_room_sched(room_id):
            rooms = id_to_rooms(room_id)
            data = {}
            for id_, r in rooms.items():
                data[id_] = {
                    k: v
                    for k, v in vars(r.sched).items()
                    if k
                    in [
                        "weekly_enabled",
                        "weekly_scheduling",
                        "onetime_sched",
                        "temp_presets",
                        "daily_presets",
                        "hourly_presets",
                    ]
                }
                data[id_]["next_schedule"] = r.sched.next_schedule()
            return data

        @mybottle.get("/api/rooms/<room_id>/sched/weekly/enable")
        def api_room_sched_weekly_enable(room_id):
            rooms = id_to_rooms(room_id)
            data = {}
            for id_, r in rooms.items():
                r.sched.enable_weekly()
                data[id_] = {"weekly_enabled": r.sched.weekly_enabled}
            return data

        @mybottle.get("/api/rooms/<room_id>/sched/weekly/disable")
        def api_room_sched_weekly_disable(room_id):
            rooms = id_to_rooms(room_id)
            data = {}
            for id_, r in rooms.items():
                r.sched.disable_weekly()
                data[id_] = {"weekly_enabled": r.sched.weekly_enabled}
            return data

        @mybottle.get("/api/rooms/all/restart")
        def api_room_restart():
            self.app.restart()
            return {"success": "For sure"}

        @mybottle.get("/api/rooms/all/stop")
        def api_room_stop():
            for r in self.app.rooms.values():
                r.stop()
            return {"success": "For sure"}

        @mybottle.put("/api/rooms/<room_id>/temp_set")
        def api_room_temp_set_put(room_id):
            room = self.app.rooms[room_id]
            value = float(request.json["value"])
            room.set_temp_set(value)
            return {"temp_set": room.temp_set}

        # @mybottle.route("/")
        # @view("index")
        # def index():
        #     # return {'rooms_component_tpl': component_rooms('all')}
        #     return static_file("ui.html", root="./views/static")
        #
        # @mybottle.route("/static/<filepath:path>")
        # def get_static_file(filepath):
        #     return static_file(filepath, root="./views/static")

        mybottle.install(
            JSONPlugin(json_dumps=lambda body: json.dumps(body, default=str))
        )
        mybottle.run(host=self.addr, port=self.port, quiet=False)
