"""HTTP-Schnittstelle der neuen Hue-Steuerung: ``/api/v2/*`` (2026-10-11).

* ``GET  /api/v2/state``            — komplette Ansicht (Raeume, Lampen, Szenen)
* ``GET  /api/v2/events``           — Server-Sent Events: ``snapshot``, dann ``delta``,
                                      ``status``, ``fail``; Herzschlag alle 25 s
* ``PUT  /api/v2/light/<id>``       — {on, brightness, xy, mirek, transition_ms}
* ``PUT  /api/v2/room/<id>``        — dasselbe fuer den ganzen Raum (grouped_light)
* ``POST /api/v2/room/<id>/mood``   — eingebaute Stimmung {mood}
* ``POST /api/v2/room/<id>/scene``  — aktuellen Zustand als Szene speichern {name}
* ``POST /api/v2/scene/<id>/recall``
* ``POST /api/v2/all``              — {on} fuer alle Lampen (bridge_home)
* ``GET  /api/v2/status``           — Stream, Queue, letzte Fehler

Schreibende Aufrufe gehen durch die Queue (Koaleszenz + Bridge-Budget) und
antworten sofort mit 202; das Ergebnis kommt als Event zurueck.
"""
import json
import os
import queue as _queue
import re
import time

from flask import Blueprint, Response, jsonify, request, stream_with_context

from hue_queue import CommandQueue
from hue_state import HueState
from hue_v2 import Bridge

HEARTBEAT_S = 25
# Jede SSE-Verbindung haelt einen waitress-Thread (32). Ohne Deckel koennten
# offene Verbindungen die ganze App aushungern (Security-Review 2026-10-11).
MAX_SUBSCRIBERS = 12
# Schreibende Aufrufe nur von hier. CORS ist in app_lite offen (CORS(app)) — eine
# fremde Seite im Heimnetz koennte sonst per Browser Licht schalten.
ALLOWED_ORIGINS = tuple(os.environ.get(
    "HUE_ALLOWED_ORIGINS",
    "https://home.celox.io:8443,https://192.168.178.105:8443,https://192.168.178.103:8443,"
    "http://192.168.178.105:5000,http://localhost:5000,http://127.0.0.1:5000").split(","))
# Szenennamen landen in fremden Oberflaechen (alte App, Philips-App): nur
# harmlose Zeichen — keine spitzen Klammern, kein & und keine Anfuehrungszeichen.
SCENE_NAME = re.compile(r"^[\w ÄÖÜäöüß.,!?:+()/-]{1,32}$")
MAX_TRANSITION_MS = 3_600_000   # Lichtwecker braucht lange Uebergaenge

# Eingebaute Raum-Stimmungen. Die Bridge hat praktisch keine eigenen Szenen,
# diese decken den Alltag ab. Lampen ohne Farbtemperatur nehmen nur die Helligkeit.
MOODS = {
    "hell":          {"label": "Hell",          "brightness": 100, "mirek": 233},
    "konzentration": {"label": "Konzentration", "brightness": 100, "mirek": 182},
    "lesen":         {"label": "Lesen",         "brightness": 80,  "mirek": 290},
    "gemuetlich":    {"label": "Gemütlich",     "brightness": 55,  "mirek": 400},
    "entspannen":    {"label": "Entspannen",    "brightness": 40,  "mirek": 447},
    "nachtlicht":    {"label": "Nachtlicht",    "brightness": 3,   "mirek": 500},
}


# CORS nur fuer die alten v1-Routen (Altbestand, wird in Phase 5 enger). /api/v2
# bekommt KEINE Freigabe — fremde Seiten koennen weder lesen noch einen
# Preflight bestehen. Ein Abziehen der Koepfe im Blueprint reicht NICHT: der
# flask_cors-Hook laeuft danach und setzt sie wieder (per Test belegt).
CORS_RESOURCES = {r"/api/(?!v2/).*": {"origins": "*"}}


EFFECT_LABELS = {
    "candle": "Kerze", "fire": "Feuer", "prism": "Prisma", "sparkle": "Funkeln",
    "opal": "Opal", "glisten": "Glitzern", "underwater": "Unterwasser",
    "cosmos": "Kosmos", "sunbeam": "Sonnenstrahl", "enchant": "Zauber",
}
MAX_SIGNAL_MS = 60_000


class Invalid(ValueError):
    pass


def to_bridge(body):
    """Browser-Format -> v2-Koerper. Wirft ``Invalid`` bei allem Unerwarteten."""
    if not isinstance(body, dict) or not body:
        raise Invalid("leerer Befehl")
    out = {}
    for k in body:
        if k not in ("on", "brightness", "xy", "mirek", "transition_ms"):
            raise Invalid("unbekanntes Feld: %s" % k)
    if "on" in body:
        if type(body["on"]) is not bool:
            raise Invalid("on muss true/false sein")
        out["on"] = {"on": body["on"]}
    if "brightness" in body:
        b = body["brightness"]
        if type(b) not in (int, float) or not 0 <= b <= 100:
            raise Invalid("brightness 0..100")
        if b == 0:
            out["on"] = {"on": False}
        else:
            out["dimming"] = {"brightness": float(b)}
    if "xy" in body:
        xy = body["xy"]
        try:
            x, y = float(xy["x"]), float(xy["y"])
        except (TypeError, KeyError, ValueError):
            raise Invalid("xy braucht x und y")
        if not (0 <= x <= 1 and 0 < y <= 1):
            raise Invalid("xy ausserhalb 0..1")
        out["color"] = {"xy": {"x": round(x, 4), "y": round(y, 4)}}
    if "mirek" in body:
        m = body["mirek"]
        if type(m) is not int or not 153 <= m <= 500:
            raise Invalid("mirek 153..500")
        out["color_temperature"] = {"mirek": m}
    if "xy" in body and "mirek" in body:
        raise Invalid("entweder xy oder mirek")
    if "transition_ms" in body:
        t = body["transition_ms"]
        if type(t) is not int or not 0 <= t <= MAX_TRANSITION_MS:
            raise Invalid("transition_ms 0..%d" % MAX_TRANSITION_MS)
        out["dynamics"] = {"duration": t}
    return out


def scene_actions(view, room_id):
    """Aktueller Zustand eines Raums als v2-Szenen-Aktionen."""
    acts = []
    for lid in view["rooms"][room_id]["lights"]:
        l = view["lights"][lid]
        a = {"on": {"on": l["on"]}}
        if l["on"] and l["brightness"] is not None:
            a["dimming"] = {"brightness": l["brightness"]}
        if l["on"] and l["mode"] == "xy" and l["xy"]:
            a["color"] = {"xy": l["xy"]}
        elif l["on"] and l["mode"] == "ct" and l["mirek"]:
            a["color_temperature"] = {"mirek": l["mirek"]}
        acts.append({"target": {"rid": lid, "rtype": "light"}, "action": a})
    return acts


def create_blueprint(state, cq, bridge, automation=None):
    bp = Blueprint("hue_v2", __name__, url_prefix="/api/v2")

    def bad(msg, code=400):
        return jsonify({"ok": False, "error": msg}), code

    @bp.before_request
    def guard_writes():
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return None
        ctype = (request.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            # erzwingt beim Browser einen CORS-Preflight — ein Formular-POST kommt nie durch
            return bad("nur application/json", 415)
        origin = request.headers.get("Origin")
        if origin is not None and origin not in ALLOWED_ORIGINS:
            return bad("fremde Herkunft", 403)
        return None


    def body_json():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise Invalid("JSON-Objekt erwartet")
        return data

    @bp.get("/state")
    def get_state():
        v = state.snapshot()
        v["moods"] = {k: m["label"] for k, m in MOODS.items()}
        v["effects"] = EFFECT_LABELS
        v["status"] = state.status()
        return jsonify(v)

    @bp.get("/status")
    def get_status():
        return jsonify({**state.status(), "queue": cq.stats()})

    @bp.get("/events")
    def events():
        q = state.subscribe(limit=MAX_SUBSCRIBERS)
        if q is None:
            return bad("zu viele Live-Verbindungen", 503)

        def gen():
            try:
                snap = state.snapshot()
                snap["moods"] = {k: m["label"] for k, m in MOODS.items()}
                snap["effects"] = EFFECT_LABELS
                yield sse("snapshot", snap)
                yield sse("status", state.status())
                while True:
                    try:
                        msg = q.get(timeout=HEARTBEAT_S)
                    except _queue.Empty:
                        yield ": ping\n\n"
                        continue
                    yield sse(msg["type"], msg["data"])
            finally:
                state.unsubscribe(q)

        return Response(stream_with_context(gen()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache",
                                 "X-Accel-Buffering": "no"})   # nginx puffert sonst

    @bp.put("/light/<lid>")
    def put_light(lid):
        if lid not in state.view["lights"]:
            return bad("unbekannte Lampe", 404)
        try:
            cq.submit("light", lid, to_bridge(body_json()))
        except Invalid as e:
            return bad(str(e))
        return jsonify({"ok": True}), 202

    @bp.put("/room/<rid>")
    def put_room(rid):
        room = state.view["rooms"].get(rid)
        if not room or not room["group"]:
            return bad("unbekannter Raum", 404)
        try:
            cq.submit("grouped_light", room["group"], to_bridge(body_json()))
        except Invalid as e:
            return bad(str(e))
        return jsonify({"ok": True}), 202

    @bp.post("/room/<rid>/mood")
    def room_mood(rid):
        room = state.view["rooms"].get(rid)
        if not room or not room["group"]:
            return bad("unbekannter Raum", 404)
        try:
            name = body_json().get("mood")
        except Invalid as e:
            return bad(str(e))
        m = MOODS.get(name)
        if not m:
            return bad("unbekannte Stimmung")
        cq.submit("grouped_light", room["group"], {
            "on": {"on": True}, "dimming": {"brightness": float(m["brightness"])},
            "color_temperature": {"mirek": m["mirek"]}, "dynamics": {"duration": 400}})
        return jsonify({"ok": True}), 202

    @bp.post("/room/<rid>/scene")
    def save_scene(rid):
        view = state.snapshot()
        if rid not in view["rooms"] or view["rooms"][rid]["kind"] != "room":
            return bad("unbekannter Raum", 404)
        try:
            name = (body_json().get("name") or "").strip()
        except Invalid as e:
            return bad(str(e))
        if not SCENE_NAME.match(name):
            return bad("Name: 1–32 Zeichen, nur Buchstaben, Ziffern, Leerzeichen und .,!?:+()/-")
        try:
            data = bridge.post("scene", {
                "type": "scene", "metadata": {"name": name},
                "group": {"rid": rid, "rtype": "room"},
                "actions": scene_actions(view, rid)})
        except Exception as e:  # noqa: BLE001
            state.note_error("scene", e)
            return bad("Bridge: %s" % e, 502)
        return jsonify({"ok": True, "id": (data[0] if data else {}).get("rid")}), 201

    @bp.post("/room/<rid>/effect")
    def room_effect(rid):
        """Eingebauter Effekt auf alle Lampen des Raums, die ihn koennen.
        ``none`` beendet ihn. Lampen ohne den Effekt bleiben unberuehrt."""
        view = state.view
        room = view["rooms"].get(rid)
        if not room:
            return bad("unbekannter Raum", 404)
        try:
            eff = body_json().get("effect")
        except Invalid as e:
            return bad(str(e))
        if eff != "none" and eff not in EFFECT_LABELS:
            return bad("unbekannter Effekt")
        hit = 0
        for lid in room["lights"]:
            l = view["lights"][lid]
            if eff == "none":
                if l.get("effect", "no_effect") != "no_effect":
                    cq.submit("light", lid, {"effects": {"effect": "no_effect"}})
                    hit += 1
            elif eff in l.get("effects", []):
                cq.submit("light", lid, {"on": {"on": True}, "effects": {"effect": eff}})
                hit += 1
        return jsonify({"ok": True, "lights": hit}), 202

    @bp.post("/room/<rid>/signal")
    def room_signal(rid):
        """Strobo ueber das eingebaute Signaling der Lampen: blinkt in der Lampe
        selbst (nicht per Befehlsflut), endet nach ``duration_ms`` von allein."""
        view = state.view
        room = view["rooms"].get(rid)
        if not room:
            return bad("unbekannter Raum", 404)
        try:
            b = body_json()
        except Invalid as e:
            return bad(str(e))
        dur = b.get("duration_ms", 10_000)
        if type(dur) is not int or not 0 <= dur <= MAX_SIGNAL_MS:
            return bad("duration_ms 0..%d" % MAX_SIGNAL_MS)
        xy = b.get("xy")
        if xy is not None:
            try:
                xy = {"x": float(xy["x"]), "y": float(xy["y"])}
            except (TypeError, KeyError, ValueError):
                return bad("xy braucht x und y")
            if not (0 <= xy["x"] <= 1 and 0 < xy["y"] <= 1):
                return bad("xy ausserhalb 0..1")
        hit = 0
        for lid in room["lights"]:
            sig = view["lights"][lid].get("signals", [])
            if dur == 0:
                body = {"signaling": {"signal": "no_signal"}}
            elif xy and "on_off_color" in sig:
                body = {"signaling": {"signal": "on_off_color", "duration": dur, "colors": [{"xy": xy}]}}
            elif "on_off" in sig:
                body = {"signaling": {"signal": "on_off", "duration": dur}}
            else:
                continue
            cq.submit("light", lid, body)
            hit += 1
        return jsonify({"ok": True, "lights": hit}), 202

    @bp.post("/scene/<sid>/recall")
    def recall(sid):
        if sid not in state.view["scenes"]:
            return bad("unbekannte Szene", 404)
        cq.submit("scene", sid, {"recall": {"action": "active"}})
        return jsonify({"ok": True}), 202

    @bp.post("/all")
    def all_lights():
        home = state.view.get("home", {}).get("group")
        if not home:
            return bad("bridge_home unbekannt", 503)
        try:
            on = body_json().get("on")
        except Invalid as e:
            return bad(str(e))
        if type(on) is not bool:
            return bad("on muss true/false sein")
        cq.submit("grouped_light", home, {"on": {"on": on}})
        return jsonify({"ok": True}), 202

    if automation is not None:
        add_automation_routes(bp, automation, state, bad, body_json)
    return bp


RULE_NAME = re.compile(r"^[\w ÄÖÜäöüß.,!?:+()/-]{1,40}$")


def add_automation_routes(bp, auto, state, bad, body_json):
    from hue_automation import Invalid as AInvalid, validate

    def known():
        return state.view["rooms"], state.view["scenes"]

    @bp.get("/automations")
    def automations():
        return jsonify(auto.overview())

    @bp.post("/automations")
    def add_rule():
        try:
            b = body_json()
            kind, name = b.get("kind"), (b.get("name") or "").strip()
            if not RULE_NAME.match(name):
                raise AInvalid("Name: 1–40 Zeichen, nur Buchstaben, Ziffern und .,!?:+()/-")
            if kind == "motion" and any(r["kind"] == "motion" for r in auto.db.rules()):
                return bad("es gibt nur einen Bewegungsmelder — bestehende Regel bearbeiten", 409)
            cfg = validate(kind, b.get("config"), *known())
        except (Invalid, AInvalid) as e:
            return bad(str(e))
        rid = auto.db.add(kind, name, cfg, enabled=b.get("enabled", True) is not False)
        auto.db.log("Regel angelegt: " + name, rid)
        return jsonify({"ok": True, "id": rid}), 201

    @bp.put("/automations/<int:rid>")
    def edit_rule(rid):
        rule = next((r for r in auto.db.rules() if r["id"] == rid), None)
        if not rule:
            return bad("unbekannte Regel", 404)
        try:
            b = body_json()
            f = {}
            if "name" in b:
                name = (b.get("name") or "").strip()
                if not RULE_NAME.match(name):
                    raise AInvalid("Name: 1–40 Zeichen")
                f["name"] = name
            if "enabled" in b:
                if type(b["enabled"]) is not bool:
                    raise AInvalid("enabled muss true/false sein")
                f["enabled"] = b["enabled"]
            if "config" in b:
                f["config"] = validate(rule["kind"], b["config"], *known())
                if rule["kind"] != "motion":   # Zeitplan darf nach Aenderung erneut feuern; beim Melder ist es reine Anzeige
                    f["last_fired"] = None
        except (Invalid, AInvalid) as e:
            return bad(str(e))
        auto.db.update(rid, **f)
        return jsonify({"ok": True})

    @bp.delete("/automations/<int:rid>")
    def del_rule(rid):
        if not auto.db.delete(rid):
            return bad("unbekannte Regel", 404)
        return jsonify({"ok": True})

    @bp.post("/away")
    def away():
        try:
            b = body_json()
        except Invalid as e:
            return bad(str(e))
        if type(b.get("on")) is not bool or type(b.get("simulate", False)) is not bool:
            return bad("on/simulate muessen true/false sein")
        auto.set_away(b["on"], b.get("simulate", False))
        return jsonify({"ok": True, "away": auto.db.get("away")})


def sse(event, data):
    return "event: %s\ndata: %s\n\n" % (event, json.dumps(data, separators=(",", ":")))


def init(app, ip, key):
    """Startet Zustand + Queue und haengt die Routen ein. Ohne Schluessel: nichts."""
    if not key:
        return None
    bridge = Bridge(ip, key)
    state = HueState(bridge)

    def on_error(rtype, rid, body, err):
        state.note_error(rtype, err)
        # "fail", nicht "error": in EventSource kollidiert ein Event namens
        # "error" mit dem Verbindungsfehler gleichen Namens.
        state.publish({"type": "fail", "data": {"rtype": rtype, "rid": rid,
                                                 "msg": str(err)[:200], "at": time.time()}})

    cq = CommandQueue(lambda t, i, b: bridge.put(t, i, b), on_error=on_error)

    from hue_automation import Automation, Store, start_pir
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "automations.db")
    auto = Automation(Store(db_path), state, cq.submit, MOODS)

    app.register_blueprint(create_blueprint(state, cq, bridge, auto))
    state.start()
    cq.start()
    auto.start()
    start_pir(auto)
    app.hue_state, app.hue_queue, app.hue_automation = state, cq, auto
    return state, cq
