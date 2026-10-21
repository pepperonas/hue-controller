"""Automation: Sonnenstand, Zeitplaene, Lichtwecker, Bewegungsmelder, Abwesenheit.
Uhr, Zufall und Senden sind injiziert — keine Bridge, kein Warten."""
import os
import random
import sys
from datetime import date, datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import hue_api_v2 as api  # noqa: E402
from hue_automation import Automation, Invalid, Store, due_today, next_run, validate  # noqa: E402
from hue_state import HueState, build_view  # noqa: E402
from sun import TZ, sun_times  # noqa: E402
from test_v2 import FakeBridge, fixture  # noqa: E402


# ---------------------------------------------------------------- Sonne

# Referenzwerte aus der astral-Bibliothek (unabhaengige Implementierung) fuer
# denselben Standort — NICHT aus dem Gedaechtnis (ein solcher Wert lag 4 min daneben).
@pytest.mark.parametrize("d, rise, set_", [
    (date(2026, 6, 21), "04:43", "21:32"),     # Sommer, MESZ
    (date(2026, 12, 21), "08:14", "15:53"),    # Winter, MEZ
    (date(2026, 3, 20), "06:09", "18:19"),
])
def test_sun_times_berlin_within_three_minutes(d, rise, set_):
    st = sun_times(d)
    for key, want in (("sunrise", rise), ("sunset", set_)):
        h, m = map(int, want.split(":"))
        got = st[key]
        assert got.date() == d
        diff = abs((got.hour * 60 + got.minute) - (h * 60 + m))
        assert diff <= 3, "%s %s: %s statt %s" % (d, key, got.strftime("%H:%M"), want)


def test_sun_times_match_astral_all_year():
    astral = pytest.importorskip("astral")
    from astral.sun import sun
    from sun import LAT, LON
    obs = astral.Observer(latitude=LAT, longitude=LON)
    worst = 0.0
    for i in range(0, 366, 5):
        d = date(2026, 1, 1) + timedelta(days=i)
        ref, mine = sun(obs, date=d, tzinfo=TZ), sun_times(d)
        for k in ("sunrise", "sunset"):
            worst = max(worst, abs((ref[k] - mine[k]).total_seconds()) / 60)
    assert worst <= 2.0, "%.1f min Abweichung" % worst


def test_dst_switch_moves_sunset_by_about_an_hour():
    # 2026-03-29 Umstellung: der Untergang springt in Ortszeit um ~1 h nach hinten
    before, after = sun_times(date(2026, 3, 28))["sunset"], sun_times(date(2026, 3, 29))["sunset"]
    delta = (after.hour * 60 + after.minute) - (before.hour * 60 + before.minute)
    assert 55 <= delta <= 65


# ---------------------------------------------------------------- Pruefung

ROOMS = {"R1": {}, "R2": {}}
SCENES = {"S1": {}}


def test_validate_schedule_and_reject_garbage():
    cfg = validate("schedule", {"room": "R1", "days": [0, 0, 6], "at": {"type": "sunset", "offset": -15},
                                "action": {"type": "mood", "mood": "gemuetlich"}}, ROOMS, SCENES)
    assert cfg["days"] == [0, 6] and cfg["at"] == {"type": "sunset", "offset": -15}
    for bad in [
        {"room": "X", "days": [1], "at": {"type": "time", "time": "07:00"}, "action": {"type": "on"}},
        {"room": "R1", "days": [], "at": {"type": "time", "time": "07:00"}, "action": {"type": "on"}},
        {"room": "R1", "days": [9], "at": {"type": "time", "time": "07:00"}, "action": {"type": "on"}},
        {"room": "R1", "days": [1], "at": {"type": "time", "time": "25:00"}, "action": {"type": "on"}},
        {"room": "R1", "days": [1], "at": {"type": "noon"}, "action": {"type": "on"}},
        {"room": "R1", "days": [1], "at": {"type": "time", "time": "07:00"}, "action": {"type": "scene", "scene": "Z"}},
        {"room": "R1", "days": [1], "at": {"type": "time", "time": "07:00"}, "action": {"type": "rm"}},
        {"room": "R1", "days": [1], "at": {"type": "sunrise", "offset": 999}, "action": {"type": "on"}},
    ]:
        with pytest.raises(Invalid):
            validate("schedule", bad, ROOMS, SCENES)


def test_wakeup_due_is_duration_before_wake_time():
    cfg = {"room": "R1", "days": [0], "time": "06:30", "duration_min": 30}
    t = due_today("wakeup", cfg, date(2026, 10, 12))        # Montag
    assert (t.hour, t.minute) == (6, 0)
    assert due_today("wakeup", cfg, date(2026, 10, 13)) is None   # Dienstag nicht


def test_next_run_skips_to_next_matching_day():
    cfg = {"room": "R1", "days": [2], "at": {"type": "time", "time": "07:00"}, "action": {"type": "on"}}
    now = datetime(2026, 10, 12, 8, 0, tzinfo=TZ)            # Montag 8:00
    assert next_run("schedule", cfg, now) == datetime(2026, 10, 14, 7, 0, tzinfo=TZ)


# ---------------------------------------------------------------- Motor

class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def auto(tmp_path):
    st = HueState(FakeBridge(fixture()))
    st.full_sync()
    sent = []
    clk = Clock(datetime(2026, 10, 12, 6, 59, 50, tzinfo=TZ))     # Montag
    a = Automation(Store(str(tmp_path / "a.db")), st, lambda t, i, b: sent.append((t, i, b)),
                   api.MOODS, clock=clk, rng=random.Random(1), defer=lambda s, fn: fn())
    a.sent, a.clk = sent, clk
    return a


def test_schedule_fires_once_in_its_window(auto):
    auto.db.add("schedule", "Morgens", {"room": "R1", "days": [0], "at": {"type": "time", "time": "07:00"},
                                       "action": {"type": "brightness", "brightness": 40, "transition_min": 2}})
    auto.tick()
    assert auto.sent == []                                   # 6:59:50 — noch nicht
    auto.clk.t += timedelta(seconds=20)
    auto.tick()
    auto.tick()                                              # zweiter Tick im selben Fenster
    assert auto.sent == [("grouped_light", "G1", {"on": {"on": True}, "dimming": {"brightness": 40.0},
                                                  "dynamics": {"duration": 120000}})]


def test_missed_schedule_is_not_caught_up(auto):
    auto.db.add("schedule", "Morgens", {"room": "R1", "days": [0], "at": {"type": "time", "time": "07:00"},
                                       "action": {"type": "on"}})
    auto.clk.t = datetime(2026, 10, 12, 9, 10, tzinfo=TZ)    # Pi war bis 9:10 aus
    auto.tick()
    assert auto.sent == []


def test_wakeup_starts_dim_warm_then_one_long_transition(auto):
    auto.db.add("wakeup", "Wecker", {"room": "R1", "days": [0], "time": "07:30", "duration_min": 30})
    auto.clk.t = datetime(2026, 10, 12, 7, 0, 5, tzinfo=TZ)
    auto.tick()
    first, second = auto.sent
    assert first[2]["dimming"]["brightness"] == 1.0 and first[2]["color_temperature"]["mirek"] == 500
    assert second[2]["dimming"]["brightness"] == 100.0 and second[2]["color_temperature"]["mirek"] == 200
    assert second[2]["dynamics"]["duration"] == 30 * 60_000 - 2000


def test_away_suppresses_schedules_except_off(auto):
    auto.db.put("away", {"on": True, "simulate": False})
    auto.db.add("schedule", "An", {"room": "R1", "days": [0], "at": {"type": "time", "time": "07:00"}, "action": {"type": "on"}})
    auto.db.add("schedule", "Aus", {"room": "R2", "days": [0], "at": {"type": "time", "time": "07:00"}, "action": {"type": "off"}})
    auto.clk.t += timedelta(seconds=20)
    auto.tick()
    assert auto.sent == [("grouped_light", "G2", {"on": {"on": False}})]


def test_away_turns_everything_off(auto):
    auto.set_away(True)
    assert auto.sent == [("grouped_light", "G0", {"on": {"on": False}})]


def test_away_simulation_lights_a_room_in_the_evening_and_turns_it_off(auto):
    auto.db.put("away", {"on": True, "simulate": True})
    sunset = sun_times(date(2026, 10, 12))["sunset"]
    auto.clk.t = sunset + timedelta(minutes=30)
    auto.tick()
    assert len(auto.sent) == 1 and auto.sent[0][2]["on"] == {"on": True}
    room_group = auto.sent[0][1]
    auto.clk.t += timedelta(minutes=61)
    auto.tick()
    assert auto.sent[-1] == ("grouped_light", room_group, {"on": {"on": False}, "dynamics": {"duration": 3000}})


def motion(auto, window="always"):
    auto.db.add("motion", "Flur", {"room": "R2", "duration_min": 3, "brightness": 60, "mirek": 370, "window": window})


def test_motion_turns_on_and_off_after_duration(auto):
    motion(auto)
    assert auto.on_motion() is True
    assert auto.sent[0][2]["dimming"]["brightness"] == 60.0
    # Bridge meldet den Raum jetzt an, wie WIR ihn gesetzt haben
    auto.state.view["rooms"]["R2"].update(on=True, on_count=1, brightness=60.0)
    auto.clk.t += timedelta(minutes=3, seconds=1)
    auto.tick()
    assert auto.sent[-1][2]["on"] == {"on": False}


def test_motion_keeps_light_if_someone_changed_it(auto):
    motion(auto)
    auto.on_motion()
    auto.state.view["rooms"]["R2"].update(on=True, on_count=1, brightness=20.0)   # von Hand gedimmt
    auto.clk.t += timedelta(minutes=4)
    auto.tick()
    assert all(b.get("on") != {"on": False} for t, i, b in auto.sent)


def test_motion_does_not_take_over_a_room_that_was_already_on(auto):
    motion(auto)
    auto.state.view["rooms"]["R2"].update(on=True, on_count=1, brightness=80.0)
    assert auto.on_motion() is False
    assert auto.sent == []


def test_motion_only_in_the_dark_when_configured(auto):
    motion(auto, window="dark")
    auto.clk.t = datetime(2026, 10, 12, 13, 0, tzinfo=TZ)
    assert auto.on_motion() is False


def test_motion_retrigger_extends_without_resending(auto):
    motion(auto)
    auto.on_motion()
    auto.clk.t += timedelta(minutes=2)
    auto.on_motion()
    assert len(auto.sent) == 1
    auto.state.view["rooms"]["R2"].update(on=True, on_count=1, brightness=60.0)
    auto.clk.t += timedelta(minutes=2)
    auto.tick()
    assert len(auto.sent) == 1                               # noch nicht abgelaufen


def test_motion_records_last_fired(auto):
    motion(auto)
    assert auto.on_motion() is True
    r = auto.motion_rule()
    assert r["last_fired"] == auto.clk.t.isoformat(timespec="seconds")


def test_ignored_motion_is_logged_but_throttled(auto):
    motion(auto, window="dark")
    auto.clk.t = datetime(2026, 10, 12, 13, 0, tzinfo=TZ)
    for _ in range(5):                                   # PIR pulst staendig
        assert auto.on_motion() is False
        auto.clk.t += timedelta(minutes=1)
    hits = [l for l in auto.db.recent(50) if "ignoriert" in l["msg"]]
    assert len(hits) == 1 and "hell" in hits[0]["msg"]
    assert auto.motion_rule()["last_fired"] is None      # verworfen ist nicht ausgeloest
    auto.clk.t += timedelta(minutes=15)
    auto.on_motion()
    assert len([l for l in auto.db.recent(50) if "ignoriert" in l["msg"]]) == 2


def test_motion_logs_when_room_was_already_on(auto):
    motion(auto)
    auto.state.view["rooms"]["R2"].update(on=True, on_count=1, brightness=80.0)
    auto.on_motion()
    assert any("war schon an" in l["msg"] for l in auto.db.recent(10))


def test_motion_light_survives_a_restart(auto):
    motion(auto)
    auto.on_motion()
    auto.state.view["rooms"]["R2"].update(on=True, on_count=1, brightness=60.0)
    # Neustart: neue Automation auf demselben Speicher
    b = Automation(auto.db, auto.state, lambda t, i, x: auto.sent.append((t, i, x)), api.MOODS,
                   clock=auto.clk, rng=random.Random(1), defer=lambda s, fn: fn())
    assert b.motion_set == ("R2", 60.0)
    auto.clk.t += timedelta(minutes=3, seconds=1)
    b.tick()
    assert auto.sent[-1][2]["on"] == {"on": False}
    assert auto.db.get("motion_active") is None               # nach dem Aus wieder leer


# ---------------------------------------------------------------- HTTP

@pytest.fixture
def client(tmp_path):
    from flask import Flask
    fb = FakeBridge(fixture())
    st = HueState(fb)
    st.full_sync()
    sent = []
    a = Automation(Store(str(tmp_path / "h.db")), st, lambda t, i, b: sent.append((t, i, b)), api.MOODS,
                   clock=lambda: datetime(2026, 10, 12, 12, 0, tzinfo=TZ))

    class Q:
        def submit(self, *x):
            sent.append(x)

        def stats(self):
            return {}

    app = Flask(__name__)
    app.register_blueprint(api.create_blueprint(st, Q(), fb, a))
    c = app.test_client()
    c.auto, c.sent = a, sent
    return c


def test_rule_crud_roundtrip(client):
    r = client.post("/api/v2/automations", json={"kind": "wakeup", "name": "Wecker",
                                                 "config": {"room": "R1", "days": [0, 1], "time": "06:30"}})
    assert r.status_code == 201
    rid = r.get_json()["id"]
    ov = client.get("/api/v2/automations").get_json()
    rule = ov["rules"][0]
    assert rule["name"] == "Wecker" and rule["next"] and rule["room_name"] == "Wohnzimmer"
    assert "sunrise" in ov["sun"]
    assert client.put("/api/v2/automations/%d" % rid, json={"enabled": False}).status_code == 200
    assert client.get("/api/v2/automations").get_json()["rules"][0]["next"] is None
    assert client.delete("/api/v2/automations/%d" % rid, json={}).status_code == 200
    assert client.get("/api/v2/automations").get_json()["rules"] == []


def test_rule_routes_reject_bad_input(client):
    assert client.post("/api/v2/automations", json={"kind": "wakeup", "name": "<b>x</b>",
                                                    "config": {"room": "R1", "days": [0], "time": "06:30"}}).status_code == 400
    assert client.post("/api/v2/automations", json={"kind": "nope", "name": "x", "config": {}}).status_code == 400
    assert client.put("/api/v2/automations/99", json={"enabled": True}).status_code == 404
    assert client.post("/api/v2/automations", data="x").status_code == 415


def test_only_one_motion_rule(client):
    body = {"kind": "motion", "name": "Flur", "config": {"room": "R2"}}
    assert client.post("/api/v2/automations", json=body).status_code == 201
    assert client.post("/api/v2/automations", json=body).status_code == 409


def test_away_route(client):
    r = client.post("/api/v2/away", json={"on": True, "simulate": True})
    assert r.status_code == 200 and r.get_json()["away"]["simulate"] is True
    assert ("grouped_light", "G0", {"on": {"on": False}}) in client.sent
    assert client.post("/api/v2/away", json={"on": "ja"}).status_code == 400


def test_motion_off_after_can_be_changed_and_keeps_last_fired(client):
    rid = client.post("/api/v2/automations", json={"kind": "motion", "name": "Garten",
                                                   "config": {"room": "R2", "duration_min": 3}}).get_json()["id"]
    client.auto.db.update(rid, last_fired="2026-10-12T21:00:00+02:00")
    rule = client.get("/api/v2/automations").get_json()["rules"][0]
    r = client.put("/api/v2/automations/%d" % rid, json={"config": {**rule["config"], "duration_min": 10}})
    assert r.status_code == 200
    after = client.get("/api/v2/automations").get_json()["rules"][0]
    assert after["config"]["duration_min"] == 10
    assert after["last_fired"] == "2026-10-12T21:00:00+02:00"     # Abschaltzeit aendern loescht die Anzeige nicht
    for bad_min in (0, 61, "5"):
        assert client.put("/api/v2/automations/%d" % rid,
                          json={"config": {**rule["config"], "duration_min": bad_min}}).status_code == 400
