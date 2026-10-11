"""Tests der neuen Steuerung (Zustand, Event-Stream, Queue, API v2).
Keine echte Bridge: Fixtures im CLIP-v2-Format, Uhr und Senden injiziert."""
import copy
import json
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import hue_api_v2 as api  # noqa: E402
from hue_queue import CommandQueue, merge  # noqa: E402
from hue_state import HueState, build_view, diff_views, xy_to_hex, mirek_to_hex  # noqa: E402
from hue_v2 import parse_sse  # noqa: E402


def light(lid, dev, name, on, bri, xy=None, mirek=None, color=True, ct=True):
    l = {"id": lid, "type": "light", "owner": {"rid": dev, "rtype": "device"},
         "metadata": {"name": name, "archetype": "classic_bulb"},
         "on": {"on": on}, "dimming": {"brightness": bri},
         "effects": {"status": "no_effect",
                     "effect_values": ["no_effect", "candle"] + (["fire", "prism"] if color else [])},
         "signaling": {"signal_values": ["no_signal", "on_off"] + (["on_off_color"] if color else [])}}
    if color:
        l["color"] = {"xy": xy or {"x": 0.45, "y": 0.41},
                      "gamut": {"red": {"x": .69, "y": .31}, "green": {"x": .17, "y": .7},
                                "blue": {"x": .15, "y": .05}}, "gamut_type": "C"}
    if ct:
        l["color_temperature"] = {"mirek": mirek, "mirek_valid": mirek is not None,
                                  "mirek_schema": {"mirek_minimum": 153, "mirek_maximum": 500}}
    return l


def fixture():
    res = {
        "light": {
            "L1": light("L1", "D1", "Wohnzimmer Decke", True, 80.0, mirek=366),
            "L2": light("L2", "D2", "Wohnzimmer Stehlampe", True, 40.0, xy={"x": .6, "y": .3}),
            "L3": light("L3", "D3", "Wohnzimmer Regal", False, 57.0),
            "L4": light("L4", "D4", "Schlafzimmer Tisch", False, 57.0, color=False, ct=False),
            "L5": light("L5", "D5", "Flur Decke", True, 100.0, mirek=250),
        },
        "room": {
            "R1": {"id": "R1", "type": "room", "metadata": {"name": ".Wohnzimmer", "archetype": "living_room"},
                   "children": [{"rid": d, "rtype": "device"} for d in ("D1", "D2", "D3")],
                   "services": [{"rid": "G1", "rtype": "grouped_light"}]},
            "R2": {"id": "R2", "type": "room", "metadata": {"name": "Schlafzimmer", "archetype": "bedroom"},
                   "children": [{"rid": "D4", "rtype": "device"}],
                   "services": [{"rid": "G2", "rtype": "grouped_light"}]},
        },
        "zone": {
            "Z1": {"id": "Z1", "type": "zone", "metadata": {"name": "Abends", "archetype": "other"},
                   "children": [{"rid": "L1", "rtype": "light"}, {"rid": "L5", "rtype": "light"}],
                   "services": [{"rid": "G3", "rtype": "grouped_light"}]},
        },
        "grouped_light": {
            "G1": {"id": "G1", "type": "grouped_light", "owner": {"rid": "R1", "rtype": "room"},
                   "on": {"on": True}, "dimming": {"brightness": 57.0}},
            "G2": {"id": "G2", "type": "grouped_light", "owner": {"rid": "R2", "rtype": "room"},
                   "on": {"on": False}},
            "G3": {"id": "G3", "type": "grouped_light", "owner": {"rid": "Z1", "rtype": "zone"},
                   "on": {"on": True}},
            "G0": {"id": "G0", "type": "grouped_light", "owner": {"rid": "B", "rtype": "bridge_home"},
                   "on": {"on": True}},
        },
        "scene": {
            "S1": {"id": "S1", "type": "scene", "metadata": {"name": "Neon"},
                   "group": {"rid": "R1", "rtype": "room"}, "status": {"active": "inactive"},
                   "actions": [{"target": {"rid": "L1", "rtype": "light"},
                                "action": {"color": {"xy": {"x": .2, "y": .1}}}}]},
        },
        "device": {},
        "zigbee_connectivity": {
            "C4": {"id": "C4", "type": "zigbee_connectivity", "owner": {"rid": "D4", "rtype": "device"},
                   "status": "connectivity_issue"},
        },
    }
    return res


# ---------------------------------------------------------------- Ansicht

def test_room_brightness_is_mean_of_lights_that_are_ON_not_last_command():
    v = build_view(fixture())
    r = v["rooms"]["R1"]
    # L1 80 + L2 40 an, L3 aus (57) zaehlt nicht; grouped_light sagt 57 (= letzter Befehl)
    assert r["brightness"] == 60.0
    assert r["on_count"] == 2
    assert r["on"] is True


def test_room_name_drops_sort_dot_and_lights_map_via_devices():
    v = build_view(fixture())
    assert v["rooms"]["R1"]["name"] == "Wohnzimmer"
    assert set(v["rooms"]["R1"]["lights"]) == {"L1", "L2", "L3"}
    assert v["lights"]["L4"]["room"] == "R2"


def test_off_room_has_no_brightness_and_no_colour():
    r = build_view(fixture())["rooms"]["R2"]
    assert (r["on"], r["brightness"], r["hex"], r["on_count"]) == (False, None, None, 0)


def test_zone_members_come_from_light_children():
    z = build_view(fixture())["rooms"]["Z1"]
    assert z["kind"] == "zone" and set(z["lights"]) == {"L1", "L5"}


def test_light_mode_ct_vs_xy_and_white_only():
    v = build_view(fixture())["lights"]
    assert v["L1"]["mode"] == "ct" and v["L1"]["mirek"] == 366
    assert v["L2"]["mode"] == "xy" and v["L2"]["mirek"] is None
    assert v["L4"]["color"] is False and v["L4"]["ct"] is False and v["L4"]["mode"] is None


def test_unreachable_light_is_flagged():
    v = build_view(fixture())["lights"]
    assert v["L4"]["reachable"] is False
    assert v["L1"]["reachable"] is True


def test_scene_colours_and_room():
    s = build_view(fixture())["scenes"]["S1"]
    assert s["room"] == "R1" and len(s["colors"]) == 1 and s["active"] is False


def test_home_group_found():
    assert build_view(fixture())["home"]["group"] == "G0"


def test_colour_helpers():
    assert xy_to_hex(0.6915, 0.3083).startswith("#ff")       # tiefes Rot
    warm, cold = mirek_to_hex(500), mirek_to_hex(153)
    assert int(warm[5:7], 16) < int(cold[5:7], 16)           # warm hat weniger Blau


# ---------------------------------------------------------------- Events

class FakeBridge:
    def __init__(self, res, batches=(), fail_after=False):
        self.res, self.batches, self.fail_after = res, list(batches), fail_after
        self.syncs = 0
        self.puts = []

    def get(self, rtype=None):
        self.syncs += 1
        return [item for part in self.res.values() for item in part.values()]

    def events(self):
        for b in self.batches:
            yield b
        if self.fail_after:
            raise ConnectionError("weg")

    def put(self, t, i, b):
        self.puts.append((t, i, b))


def test_event_produces_delta_with_light_and_its_room_only():
    st = HueState(FakeBridge(fixture()))
    st.full_sync()
    q = st.subscribe()
    st.apply_events([{"kind": "update", "item": {"id": "L2", "type": "light",
                                                 "dimming": {"brightness": 100.0}}}])
    msg = q.get_nowait()
    assert msg["type"] == "delta"
    assert set(msg["data"]["lights"]) == {"L2"}
    assert msg["data"]["rooms"]["R1"]["brightness"] == 90.0
    assert "R2" not in msg["data"]["rooms"]


def test_unchanged_event_sends_nothing():
    st = HueState(FakeBridge(fixture()))
    st.full_sync()
    q = st.subscribe()
    st.apply_events([{"kind": "update", "item": {"id": "L1", "type": "light",
                                                 "dimming": {"brightness": 80.0}}}])
    assert q.empty()


def test_delete_event_reports_removal():
    st = HueState(FakeBridge(fixture()))
    st.full_sync()
    q = st.subscribe()
    st.apply_events([{"kind": "delete", "item": {"id": "S1", "type": "scene"}}])
    assert q.get_nowait()["data"]["removed"]["scenes"] == ["S1"]


def test_reconnect_does_a_full_resync():
    fb = FakeBridge(fixture(), fail_after=True)
    st = HueState(fb, retry_min=0.01)
    t = threading.Thread(target=st.run, daemon=True)
    t.start()
    deadline = threading.Event()
    while fb.syncs < 3 and not deadline.wait(0.01):
        pass
    st.stop()
    t.join(1)
    assert fb.syncs >= 3
    assert any(e["where"] == "stream" for e in st.status()["errors"])


def test_stuck_subscriber_is_dropped_not_blocking():
    st = HueState(FakeBridge(fixture()))
    q = st.subscribe()
    for _ in range(600):
        st.publish({"type": "status", "data": {}})
    assert q not in st.subs


def test_parse_sse_splits_containers():
    lines = [": hi", "",
             "id: 1:0",
             'data: [{"type":"update","data":[{"id":"a","type":"light"},{"id":"b","type":"light"}]},'
             '{"type":"delete","data":[{"id":"c","type":"scene"}]}]', ""]
    batches = list(parse_sse(iter(lines)))
    assert len(batches) == 1
    assert [(e["kind"], e["item"]["id"]) for e in batches[0]] == [("update", "a"), ("update", "b"), ("delete", "c")]


# ---------------------------------------------------------------- Queue

class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def drain(cq):
    n = 0
    while cq.step():
        n += 1
    return n


def test_slider_drag_coalesces_to_last_value():
    sent = []
    clk = Clock()
    cq = CommandQueue(lambda t, i, b: sent.append((t, i, b)), clock=clk)
    for v in range(1, 51):
        cq.submit("light", "L1", {"dimming": {"brightness": float(v)}})
    drain(cq)
    assert sent == [("light", "L1", {"dimming": {"brightness": 50.0}})]
    assert cq.stats()["coalesced"] == 49


def test_light_budget_is_ten_per_second():
    sent = []
    clk = Clock()
    cq = CommandQueue(lambda t, i, b: sent.append(i), clock=clk)
    for n in range(25):
        cq.submit("light", "L%d" % n, {"on": {"on": True}})
    assert drain(cq) == 10
    clk.t = 0.1
    assert drain(cq) == 1
    clk.t = 1.6
    assert drain(cq) == 10
    assert len(sent) == 21


def test_group_has_min_gap_but_last_value_arrives():
    sent = []
    clk = Clock()
    cq = CommandQueue(lambda t, i, b: sent.append(b["dimming"]["brightness"]), clock=clk)
    cq.submit("grouped_light", "G1", {"dimming": {"brightness": 10.0}})
    assert drain(cq) == 1                  # erster Wert sofort
    for v in (20.0, 30.0, 40.0):
        cq.submit("grouped_light", "G1", {"dimming": {"brightness": v}})
    clk.t = 0.2
    assert drain(cq) == 0                  # Mindestabstand
    clk.t = 0.41
    assert drain(cq) == 1
    assert sent == [10.0, 40.0]


def test_send_error_reaches_callback():
    errs = []

    def boom(*a):
        raise RuntimeError("bridge sagt nein")

    cq = CommandQueue(boom, on_error=lambda *a: errs.append(a), clock=Clock())
    cq.submit("light", "L1", {"on": {"on": True}})
    drain(cq)
    assert errs and errs[0][1] == "L1" and cq.stats()["failed"] == 1


def test_merge_keeps_colour_mode_exclusive():
    d = {"color_temperature": {"mirek": 300}, "dimming": {"brightness": 5.0}}
    merge(d, {"color": {"xy": {"x": .3, "y": .3}}})
    assert "color_temperature" not in d and d["dimming"]["brightness"] == 5.0
    merge(d, {"color_temperature": {"mirek": 200}})
    assert "color" not in d


# ---------------------------------------------------------------- Validierung

@pytest.mark.parametrize("bad", [
    {}, {"on": 1}, {"brightness": 101}, {"brightness": "50"}, {"brightness": True},
    {"xy": {"x": 2, "y": .3}}, {"xy": "rot"}, {"mirek": 100}, {"mirek": 300.5},
    {"xy": {"x": .3, "y": .3}, "mirek": 300}, {"transition_ms": -1}, {"evil": 1},
])
def test_to_bridge_rejects(bad):
    with pytest.raises(api.Invalid):
        api.to_bridge(bad)


def test_to_bridge_maps_fields():
    out = api.to_bridge({"on": True, "brightness": 42, "mirek": 300, "transition_ms": 400})
    assert out == {"on": {"on": True}, "dimming": {"brightness": 42.0},
                   "color_temperature": {"mirek": 300}, "dynamics": {"duration": 400}}
    assert api.to_bridge({"brightness": 0}) == {"on": {"on": False}}


# ---------------------------------------------------------------- HTTP

@pytest.fixture
def client():
    from flask import Flask
    fb = FakeBridge(fixture())
    st = HueState(fb)
    st.full_sync()
    submitted = []

    class Q:
        def submit(self, t, i, b):
            submitted.append((t, i, b))

        def stats(self):
            return {}

    app = Flask(__name__)
    app.register_blueprint(api.create_blueprint(st, Q(), fb))
    c = app.test_client()
    c.submitted, c.state = submitted, st
    return c


def test_writes_need_json_and_house_origin(client):
    # Formular-POST einer fremden Seite: kein JSON -> 415, nichts in der Queue
    assert client.post("/api/v2/all", data="on=false",
                       content_type="application/x-www-form-urlencoded").status_code == 415
    assert client.post("/api/v2/scene/S1/recall").status_code == 415
    r = client.put("/api/v2/light/L1", json={"on": True}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert client.submitted == []
    ok = client.put("/api/v2/light/L1", json={"on": True},
                    headers={"Origin": "https://home.celox.io:8443"})
    assert ok.status_code == 202


def test_v2_answers_carry_no_cors_allow(client):
    CORS = pytest.importorskip("flask_cors").CORS
    CORS(client.application, resources=api.CORS_RESOURCES)   # exakt wie app_lite
    r = client.get("/api/v2/state", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in r.headers


def test_app_lite_uses_the_restricted_cors_config():
    src = open(os.path.join(os.path.dirname(__file__), "..", "app_lite.py")).read()
    assert "CORS(app, resources=CORS_RESOURCES)" in src
    assert "\nCORS(app)\n" not in src


def test_cap_holds_under_concurrent_subscribe():
    st = HueState(FakeBridge(fixture()))
    got = []
    barrier = threading.Barrier(40)

    def grab():
        barrier.wait()
        got.append(st.subscribe(limit=12))

    ts = [threading.Thread(target=grab) for _ in range(40)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sum(q is not None for q in got) == 12
    assert len(st.subs) == 12


def test_live_connections_are_capped(client):
    for _ in range(api.MAX_SUBSCRIBERS):
        client.state.subscribe()
    assert client.get("/api/v2/events").status_code == 503


@pytest.mark.parametrize("name", ["<img src=x onerror=alert(1)>", 'a"b', "a&b", "", "x" * 33])
def test_scene_name_rejects_markup(client, name):
    r = client.post("/api/v2/room/R1/scene", json={"name": name})
    assert r.status_code == 400


def test_put_light_queues_bridge_body(client):
    r = client.put("/api/v2/light/L1", json={"brightness": 30})
    assert r.status_code == 202
    assert client.submitted == [("light", "L1", {"dimming": {"brightness": 30.0}})]


def test_put_room_targets_its_grouped_light(client):
    assert client.put("/api/v2/room/R1", json={"on": False}).status_code == 202
    assert client.submitted == [("grouped_light", "G1", {"on": {"on": False}})]


def test_invalid_and_unknown_never_reach_the_queue(client):
    assert client.put("/api/v2/light/L1", json={"brightness": 500}).status_code == 400
    assert client.put("/api/v2/light/NOPE", json={"on": True}).status_code == 404
    assert client.put("/api/v2/room/R1", data="kein json").status_code == 415
    assert client.submitted == []


def test_mood_sets_brightness_and_temperature(client):
    assert client.post("/api/v2/room/R1/mood", json={"mood": "nachtlicht"}).status_code == 202
    t, i, b = client.submitted[0]
    assert (t, i) == ("grouped_light", "G1")
    assert b["dimming"]["brightness"] == 3.0 and b["color_temperature"]["mirek"] == 500
    assert client.post("/api/v2/room/R1/mood", json={"mood": "disco"}).status_code == 400


def test_all_off_uses_bridge_home(client):
    assert client.post("/api/v2/all", json={"on": False}).status_code == 202
    assert client.submitted == [("grouped_light", "G0", {"on": {"on": False}})]


def test_scene_recall_is_queued(client):
    assert client.post("/api/v2/scene/S1/recall", json={}).status_code == 202
    assert client.submitted == [("scene", "S1", {"recall": {"action": "active"}})]


def test_state_has_rooms_lights_scenes_moods(client):
    d = client.get("/api/v2/state").get_json()
    assert {"rooms", "lights", "scenes", "moods", "status"} <= set(d)
    assert "nachtlicht" in d["moods"]


def test_events_start_with_a_snapshot(client):
    r = client.get("/api/v2/events", buffered=False)
    assert r.mimetype == "text/event-stream"
    assert r.headers["X-Accel-Buffering"] == "no"
    it = iter(r.response)
    first = next(it)
    r.close()
    text = first.decode() if isinstance(first, bytes) else first
    assert text.startswith("event: snapshot\n")
    assert json.loads(text.split("data: ", 1)[1])["rooms"]["R1"]["name"] == "Wohnzimmer"


def test_scene_actions_capture_current_state():
    v = build_view(fixture())
    acts = {a["target"]["rid"]: a["action"] for a in api.scene_actions(v, "R1")}
    assert acts["L1"]["color_temperature"] == {"mirek": 366}
    assert acts["L2"]["color"]["xy"] == {"x": .6, "y": .3}
    assert acts["L3"] == {"on": {"on": False}}


# ---------------------------------------------------------------- Effekte

def test_effect_only_hits_lights_that_support_it(client):
    r = client.post("/api/v2/room/R1/effect", json={"effect": "fire"})
    assert r.status_code == 202 and r.get_json()["lights"] == 3
    assert all(b["effects"] == {"effect": "fire"} for t, i, b in client.submitted)
    client.submitted.clear()
    # Schlafzimmer: L4 kann nur Kerze
    assert client.post("/api/v2/room/R2/effect", json={"effect": "fire"}).get_json()["lights"] == 0
    assert client.post("/api/v2/room/R2/effect", json={"effect": "candle"}).get_json()["lights"] == 1
    assert client.post("/api/v2/room/R1/effect", json={"effect": "rm -rf"}).status_code == 400


def test_effect_none_stops_only_running_ones(client):
    client.state.view["lights"]["L2"]["effect"] = "fire"
    client.post("/api/v2/room/R1/effect", json={"effect": "none"})
    assert client.submitted == [("light", "L2", {"effects": {"effect": "no_effect"}})]


def test_strobe_uses_native_signaling_with_colour_where_possible(client):
    r = client.post("/api/v2/room/R2/signal", json={"duration_ms": 5000, "xy": {"x": .6, "y": .3}})
    assert r.status_code == 202
    # L4 hat kein on_off_color -> faellt auf on_off zurueck
    assert client.submitted == [("light", "L4", {"signaling": {"signal": "on_off", "duration": 5000}})]
    client.submitted.clear()
    client.post("/api/v2/room/R1/signal", json={"duration_ms": 5000, "xy": {"x": .6, "y": .3}})
    assert client.submitted[0][2]["signaling"]["signal"] == "on_off_color"


def test_strobe_limits(client):
    assert client.post("/api/v2/room/R1/signal", json={"duration_ms": 999_999}).status_code == 400
    assert client.post("/api/v2/room/R1/signal", json={"duration_ms": "5"}).status_code == 400
    client.post("/api/v2/room/R1/signal", json={"duration_ms": 0})
    assert all(b == {"signaling": {"signal": "no_signal"}} for t, i, b in client.submitted)


def test_light_view_lists_effects_without_no_effect():
    v = build_view(fixture())["lights"]
    assert v["L1"]["effects"] == ["candle", "fire", "prism"]
    assert v["L4"]["effects"] == ["candle"] and v["L1"]["effect"] == "no_effect"
