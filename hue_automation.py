"""Automationen der Hue-Steuerung (2026-10-11).

* Zeitplaene  — Raum, Wochentage, Uhrzeit ODER Sonnenauf-/-untergang +- Minuten,
                Aktion an/aus/Helligkeit/Stimmung/Szene, optional mit Uebergang.
* Lichtwecker — Raum, Weckzeit, Dauer: startet bei 1 % / 2000 K und laeuft in
                EINEM Bridge-Uebergang bis 100 % / 5000 K zur Weckzeit. Wer den
                Raum waehrenddessen ausschaltet, beendet ihn (die Bridge bricht
                den Uebergang ab) — kein Nachsteuern gegen den Menschen.
* Bewegung    — PIR an GPIO 26: Raum an, nach Ablauf wieder aus. Hat jemand das
                Licht inzwischen von Hand veraendert, bleibt es an.
* Abwesenheit — alles aus; optional abends zufaellig 1–2 Raeume fuer 20–60 min.

Regeln liegen in SQLite (``automations.db``), der Zeitplaner prueft alle 20 s.
Verpasstes wird nach einem Neustart NICHT nachgeholt (ein Wecker um 6:30 soll
nicht um 9:10 losgehen). Uhr, Zufall und das Senden sind injizierbar.
"""
import json
import random
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from sun import TZ, sun_times

DAYS = 7
FIRE_WINDOW_S = 120          # ein Termin gilt als "jetzt", bis zu 2 min danach
TICK_S = 20
MOODS = ("hell", "konzentration", "lesen", "gemuetlich", "entspannen", "nachtlicht")
AWAY_END = (23, 30)
MOTION_SKIP_LOG_S = 15 * 60  # verworfene Bewegung: je Grund hoechstens so oft ins Protokoll


class Invalid(ValueError):
    pass


# ---------------------------------------------------------------- Pruefung

def _int(v, lo, hi, name):
    if type(v) is not int or not lo <= v <= hi:
        raise Invalid("%s %d..%d" % (name, lo, hi))
    return v


def _hhmm(v, name="time"):
    if not isinstance(v, str) or len(v) != 5 or v[2] != ":":
        raise Invalid("%s als HH:MM" % name)
    h, m = v.split(":")
    if not (h.isdigit() and m.isdigit()) or not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
        raise Invalid("%s als HH:MM" % name)
    return v


def _days(v):
    if not isinstance(v, list) or not v or any(type(d) is not int or not 0 <= d <= 6 for d in v):
        raise Invalid("days: Liste aus 0 (Mo) .. 6 (So)")
    return sorted(set(v))


def validate(kind, cfg, rooms, scenes):
    """Prueft eine Regel gegen bekannte Raeume/Szenen. Liefert die bereinigte Konfiguration."""
    if not isinstance(cfg, dict):
        raise Invalid("config muss ein Objekt sein")
    room = cfg.get("room")
    if room not in rooms:
        raise Invalid("unbekannter Raum")
    out = {"room": room}
    if kind == "schedule":
        out["days"] = _days(cfg.get("days"))
        at = cfg.get("at") or {}
        t = at.get("type")
        if t == "time":
            out["at"] = {"type": "time", "time": _hhmm(at.get("time"))}
        elif t in ("sunrise", "sunset"):
            out["at"] = {"type": t, "offset": _int(at.get("offset", 0), -180, 180, "offset")}
        else:
            raise Invalid("at.type: time | sunrise | sunset")
        act = cfg.get("action") or {}
        a = act.get("type")
        clean = {"type": a, "transition_min": _int(act.get("transition_min", 0), 0, 60, "transition_min")}
        if a in ("on", "off"):
            pass
        elif a == "brightness":
            clean["brightness"] = _int(act.get("brightness"), 1, 100, "brightness")
        elif a == "mood":
            if act.get("mood") not in MOODS:
                raise Invalid("unbekannte Stimmung")
            clean["mood"] = act["mood"]
        elif a == "scene":
            if act.get("scene") not in scenes:
                raise Invalid("unbekannte Szene")
            clean["scene"] = act["scene"]
        else:
            raise Invalid("action.type: on | off | brightness | mood | scene")
        out["action"] = clean
    elif kind == "wakeup":
        out["days"] = _days(cfg.get("days"))
        out["time"] = _hhmm(cfg.get("time"))
        out["duration_min"] = _int(cfg.get("duration_min", 30), 5, 60, "duration_min")
    elif kind == "motion":
        out["duration_min"] = _int(cfg.get("duration_min", 3), 1, 60, "duration_min")
        out["brightness"] = _int(cfg.get("brightness", 100), 1, 100, "brightness")
        out["mirek"] = _int(cfg.get("mirek", 370), 153, 500, "mirek")
        w = cfg.get("window", "dark")
        if w not in ("dark", "always"):
            raise Invalid("window: dark | always")
        out["window"] = w
    else:
        raise Invalid("kind: schedule | wakeup | motion")
    return out


# ---------------------------------------------------------------- Zeitrechnung

def due_today(kind, cfg, day):
    """Faelligkeit einer Regel am Datum ``day`` (Ortszeit) oder None."""
    if day.weekday() not in cfg.get("days", []):
        return None
    if kind == "wakeup":
        h, m = map(int, cfg["time"].split(":"))
        wake = datetime(day.year, day.month, day.day, h, m, tzinfo=TZ)
        return wake - timedelta(minutes=cfg["duration_min"])
    if kind == "schedule":
        at = cfg["at"]
        if at["type"] == "time":
            h, m = map(int, at["time"].split(":"))
            return datetime(day.year, day.month, day.day, h, m, tzinfo=TZ)
        ev = sun_times(day)[at["type"]]
        return (ev + timedelta(minutes=at["offset"])).replace(second=0, microsecond=0)
    return None


def next_run(kind, cfg, now):
    """Naechster Termin ab jetzt (ein gerade laufendes Ausfuehrungsfenster zaehlt mit)."""
    for i in range(DAYS + 1):
        t = due_today(kind, cfg, (now + timedelta(days=i)).date())
        if t and t + timedelta(seconds=FIRE_WINDOW_S) > now:
            return t
    return None


# ---------------------------------------------------------------- Speicher

class Store:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
                    name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                    config TEXT NOT NULL, last_fired TEXT);
                CREATE TABLE IF NOT EXISTS log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
                    rule INTEGER, msg TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    def _db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def rules(self):
        with self.lock, self._db() as db:
            return [dict(r, config=json.loads(r["config"]), enabled=bool(r["enabled"]))
                    for r in db.execute("SELECT * FROM rules ORDER BY id")]

    def add(self, kind, name, cfg, enabled=True):
        with self.lock, self._db() as db:
            cur = db.execute("INSERT INTO rules(kind,name,enabled,config) VALUES(?,?,?,?)",
                             (kind, name, int(enabled), json.dumps(cfg)))
            return cur.lastrowid

    def update(self, rid, **f):
        sets, vals = [], []
        for k in ("name", "enabled", "config", "last_fired"):
            if k in f:
                v = f[k]
                sets.append(k + "=?")
                vals.append(json.dumps(v) if k == "config" else int(v) if k == "enabled" else v)
        if not sets:
            return
        with self.lock, self._db() as db:
            db.execute("UPDATE rules SET %s WHERE id=?" % ",".join(sets), (*vals, rid))

    def delete(self, rid):
        with self.lock, self._db() as db:
            return db.execute("DELETE FROM rules WHERE id=?", (rid,)).rowcount

    def log(self, msg, rule=None, at=None):
        with self.lock, self._db() as db:
            db.execute("INSERT INTO log(at,rule,msg) VALUES(?,?,?)", (at or time.time(), rule, msg[:300]))
            db.execute("DELETE FROM log WHERE id NOT IN (SELECT id FROM log ORDER BY id DESC LIMIT 500)")

    def recent(self, n=30):
        with self.lock, self._db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM log ORDER BY id DESC LIMIT ?", (n,))]

    def get(self, key, default=None):
        with self.lock, self._db() as db:
            r = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            return json.loads(r["value"]) if r else default

    def put(self, key, value):
        with self.lock, self._db() as db:
            db.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (key, json.dumps(value)))


# ---------------------------------------------------------------- Motor

class Automation:
    def __init__(self, store, state, submit, moods, clock=None, rng=None, defer=None):
        self.db = store
        # defer(sekunden, fn): spaeter ausfuehren (Tests fuehren sofort aus)
        self.defer = defer or (lambda sec, fn: threading.Timer(sec, fn).start())
        self.state = state                       # HueState (view)
        self.submit = submit                     # submit(rtype, rid, body)
        self.moods = moods                       # {name: {brightness, mirek}}
        self.clock = clock or (lambda: datetime.now(TZ))
        self.rng = rng or random.Random()
        # Was der Melder eingeschaltet hat, liegt zusaetzlich im kv-Speicher: ohne
        # das vergass ein Neustart mitten in der Leuchtzeit, dass das Licht UNSER
        # war — es blieb dann an, bis es jemand von Hand ausschaltete.
        self.motion_until = None                 # Zeitpunkt fuers Ausschalten
        self.motion_set = None                   # (room, brightness) wie WIR gesetzt haben
        m = self.db.get("motion_active")
        if m:
            self.motion_set = (m["room"], float(m["brightness"]))
            self.motion_until = datetime.fromisoformat(m["until"])
        self._skip_logged = {}                   # Grund -> letzter Protokolleintrag
        self.away_visit = None                   # (room, until)
        self.away_next = None
        self.pir_ok = False
        self._stop = threading.Event()

    # -- Hilfen -------------------------------------------------------------
    def room_group(self, room):
        r = self.state.view["rooms"].get(room)
        return r and r.get("group")

    def room_name(self, room):
        r = self.state.view["rooms"].get(room)
        return r["name"] if r else room

    def send_room(self, room, body):
        g = self.room_group(room)
        if g:
            self.submit("grouped_light", g, body)

    def act(self, room, action):
        dur = {"dynamics": {"duration": action.get("transition_min", 0) * 60_000}} if action.get("transition_min") else {}
        a = action["type"]
        if a == "on":
            self.send_room(room, {"on": {"on": True}, **dur})
        elif a == "off":
            self.send_room(room, {"on": {"on": False}, **dur})
        elif a == "brightness":
            self.send_room(room, {"on": {"on": True}, "dimming": {"brightness": float(action["brightness"])}, **dur})
        elif a == "mood":
            m = self.moods[action["mood"]]
            self.send_room(room, {"on": {"on": True}, "dimming": {"brightness": float(m["brightness"])},
                                  "color_temperature": {"mirek": m["mirek"]}, **dur})
        elif a == "scene":
            body = {"recall": {"action": "active"}}
            if action.get("transition_min"):
                body["recall"]["duration"] = action["transition_min"] * 60_000
            self.submit("scene", action["scene"], body)

    def start_wakeup(self, room, minutes):
        """Erst dunkel-warm einschalten, dann EIN langer Uebergang bis Tageslicht.
        Der zweite Befehl kommt verzoegert: beide gingen sonst an dasselbe Ziel
        und die Queue wuerde sie zu einem zusammenfassen (letzter gewinnt)."""
        self.send_room(room, {"on": {"on": True}, "dimming": {"brightness": 1.0},
                              "color_temperature": {"mirek": 500}})
        self.defer(2.0, lambda: self.send_room(room, {
            "dimming": {"brightness": 100.0}, "color_temperature": {"mirek": 200},
            "dynamics": {"duration": max(0, minutes * 60_000 - 2000)}}))

    # -- Zeitplaner ---------------------------------------------------------
    def tick(self):
        now = self.clock()
        away = self.db.get("away", {"on": False})
        for r in self.db.rules():
            if not r["enabled"] or r["kind"] not in ("schedule", "wakeup"):
                continue
            due = due_today(r["kind"], r["config"], now.date())
            if not due or not (due <= now < due + timedelta(seconds=FIRE_WINDOW_S)):
                continue
            stamp = due.isoformat()
            if r.get("last_fired") == stamp:
                continue
            self.db.update(r["id"], last_fired=stamp)
            room = r["config"]["room"]
            if away.get("on") and not (r["kind"] == "schedule" and r["config"]["action"]["type"] == "off"):
                self.db.log("übersprungen (abwesend): " + r["name"], r["id"])
                continue
            if r["kind"] == "wakeup":
                self.start_wakeup(room, r["config"]["duration_min"])
                self.db.log("Lichtwecker gestartet: %s (%d min)" % (self.room_name(room), r["config"]["duration_min"]), r["id"])
            else:
                self.act(room, r["config"]["action"])
                self.db.log("ausgeführt: " + r["name"], r["id"])
        self.motion_tick(now)
        self.away_tick(now, away)

    # -- Bewegungsmelder ----------------------------------------------------
    def motion_rule(self):
        for r in self.db.rules():
            if r["kind"] == "motion":
                return r
        return None

    def _motion_skip(self, now, reason, rule_id=None):
        """Verworfene Bewegung protokollieren — sonst sieht niemand, ob der Sensor
        ueberhaupt meldet (ein PIR pulst bei Bewegung staendig, daher je Grund
        hoechstens einmal je MOTION_SKIP_LOG_S)."""
        last = self._skip_logged.get(reason)
        if last is not None and (now - last).total_seconds() < MOTION_SKIP_LOG_S:
            return False
        self._skip_logged[reason] = now
        self.db.log("Bewegung erkannt, ignoriert: " + reason, rule_id)
        return False

    def on_motion(self):
        now = self.clock()
        r = self.motion_rule()
        if not r or not r["enabled"]:
            return False
        if self.db.get("away", {"on": False}).get("on"):
            return self._motion_skip(now, "Abwesend aktiv", r["id"])
        c = r["config"]
        if c["window"] == "dark":
            st = sun_times(now.date())
            if st["sunrise"] <= now < st["sunset"]:
                return self._motion_skip(now, "es ist hell", r["id"])
        room = self.state.view["rooms"].get(c["room"])
        if not room:
            return self._motion_skip(now, "Raum unbekannt", r["id"])
        if room["on"] and room["on_count"] and self.motion_set is None:
            # war schon an — nicht uebernehmen, nicht spaeter ausschalten
            return self._motion_skip(now, "%s war schon an" % self.room_name(c["room"]), r["id"])
        if self.motion_set is None:
            self.send_room(c["room"], {"on": {"on": True}, "dimming": {"brightness": float(c["brightness"])},
                                       "color_temperature": {"mirek": c["mirek"]}})
            self.motion_set = (c["room"], float(c["brightness"]))
            self.db.log("Bewegung: %s an" % self.room_name(c["room"]), r["id"])
        self.db.update(r["id"], last_fired=now.isoformat(timespec="seconds"))
        self.motion_until = now + timedelta(minutes=c["duration_min"])
        self._save_motion()
        return True

    def _save_motion(self):
        self.db.put("motion_active", None if not self.motion_set else {
            "room": self.motion_set[0], "brightness": self.motion_set[1], "until": self.motion_until.isoformat()})

    def motion_tick(self, now):
        if not self.motion_set or not self.motion_until or now < self.motion_until:
            return
        room_id, bri = self.motion_set
        self.motion_set, self.motion_until = None, None
        self._save_motion()
        room = self.state.view["rooms"].get(room_id)
        if not room or not room["on"]:
            return
        # Handeingriff? Dann bleibt das Licht, wie der Mensch es eingestellt hat.
        if room["brightness"] is not None and abs(room["brightness"] - bri) > 3:
            self.db.log("Bewegung: %s von Hand verändert — bleibt an" % self.room_name(room_id))
            return
        self.send_room(room_id, {"on": {"on": False}, "dynamics": {"duration": 4000}})
        self.db.log("Bewegung: %s aus" % self.room_name(room_id))

    # -- Abwesenheit --------------------------------------------------------
    def set_away(self, on, simulate=False):
        self.db.put("away", {"on": bool(on), "simulate": bool(simulate), "since": time.time()})
        if on:
            home = (self.state.view.get("home") or {}).get("group")
            if home:
                self.submit("grouped_light", home, {"on": {"on": False}})
            self.db.log("Abwesend" + (" (bewohnt wirken)" if simulate else ""))
        else:
            self.away_visit, self.away_next = None, None
            self.db.log("Wieder da")

    def away_tick(self, now, away):
        if not (away.get("on") and away.get("simulate")):
            return
        st = sun_times(now.date())
        end = now.replace(hour=AWAY_END[0], minute=AWAY_END[1], second=0, microsecond=0)
        in_window = st["sunset"] <= now < end
        if self.away_visit:
            room, until = self.away_visit
            if now >= until or not in_window:
                self.send_room(room, {"on": {"on": False}, "dynamics": {"duration": 3000}})
                self.away_visit = None
                self.away_next = now + timedelta(minutes=self.rng.randint(10, 40))
            return
        if not in_window:
            return
        if self.away_next and now < self.away_next:
            return
        rooms = [r for r in self.state.view["rooms"].values()
                 if r["kind"] == "room" and r["lights"] and r.get("archetype") not in ("garden", "bathroom")]
        if not rooms:
            return
        room = self.rng.choice(rooms)
        m = self.moods["gemuetlich"]
        self.send_room(room["id"], {"on": {"on": True}, "dimming": {"brightness": float(m["brightness"])},
                                    "color_temperature": {"mirek": m["mirek"]}, "dynamics": {"duration": 2000}})
        self.away_visit = (room["id"], now + timedelta(minutes=self.rng.randint(20, 60)))
        self.db.log("Bewohnt wirken: %s an" % room["name"])

    # -- Ansicht ------------------------------------------------------------
    def overview(self):
        now = self.clock()
        st = sun_times(now.date())
        rules = []
        for r in self.db.rules():
            nxt = next_run(r["kind"], r["config"], now) if r["enabled"] else None
            rules.append({**r, "next": nxt.isoformat() if nxt else None,
                          "room_name": self.room_name(r["config"]["room"])})
        return {
            "rules": rules,
            "away": self.db.get("away", {"on": False, "simulate": False}),
            "sun": {"sunrise": st["sunrise"].strftime("%H:%M"), "sunset": st["sunset"].strftime("%H:%M")},
            "pir": {"available": self.pir_ok, "active_until": self.motion_until.isoformat() if self.motion_until else None},
            "log": self.db.recent(25),
        }

    def run(self):
        while not self._stop.wait(TICK_S):
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001 — der Planer darf nie sterben
                self.db.log("Fehler im Zeitplaner: %s" % e)

    def start(self):
        threading.Thread(target=self.run, name="hue-automation", daemon=True).start()

    def stop(self):
        self._stop.set()


def start_pir(automation, pin=26):
    """Bewegungsmelder per gpiozero (Pin-Fabrik lgpio — RPi.GPIO laeuft auf dem
    Pi 5 nicht: "Cannot determine SOC peripheral base address")."""
    import os
    os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")
    try:
        from gpiozero import MotionSensor
        sensor = MotionSensor(pin, pull_up=False)
        sensor.when_motion = lambda: automation.on_motion()
        automation.pir_ok = True
        automation.pir_sensor = sensor
        return sensor
    except Exception as e:  # noqa: BLE001
        automation.db.log("Bewegungsmelder nicht verfügbar: %s" % e)
        return None
