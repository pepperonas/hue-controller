"""Zustandsmodell der Bridge im Speicher, gespeist aus dem v2-Event-Stream.

Ein Voll-Abgleich beim Start und nach jedem Wiederverbinden, dazwischen nur
Events. Abnehmer (Browser per SSE) bekommen eine fertige ANSICHT — Raeume mit
echter Helligkeit und Farbe, Lampen mit Farbraum, Szenen mit ihren Farben —
statt roher Bridge-Objekte. Die Ansicht ist reine Funktion des Speichers
(``build_view``) und damit ohne Bridge testbar.
"""
import copy
import math
import queue
import threading
import time
from collections import deque

RESOURCES = ("light", "room", "zone", "grouped_light", "scene", "device",
             "zigbee_connectivity")


# ---------------------------------------------------------------- Farbe

def _gamma(c):
    c = max(0.0, c)
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def xy_to_hex(x, y, bri=100.0):
    """CIE xy (+ Helligkeit 0..100) -> sRGB-Hex. Fuer die ANZEIGE: die Farbe wird
    auf volle Leuchtkraft normiert, sonst waere jede gedimmte Lampe schwarz."""
    if y <= 0:
        return "#ffffff"
    Y = 1.0
    X = (Y / y) * x
    Z = (Y / y) * (1 - x - y)
    r = X * 3.2406 - Y * 1.5372 - Z * 0.4986
    g = -X * 0.9689 + Y * 1.8758 + Z * 0.0415
    b = X * 0.0557 - Y * 0.2040 + Z * 1.0570
    m = max(r, g, b, 1e-9)
    r, g, b = (_gamma(v / m) for v in (r, g, b))
    return "#%02x%02x%02x" % tuple(int(round(max(0, min(1, v)) * 255)) for v in (r, g, b))


def mirek_to_hex(mirek):
    """Farbtemperatur -> sRGB (Tanner-Helland), fuer die Anzeige."""
    k = 1e6 / max(1, mirek) / 100.0
    if k <= 66:
        r = 255
        g = 99.4708025861 * math.log(k) - 161.1195681661
        b = 0 if k <= 19 else 138.5177312231 * math.log(k - 10) - 305.0447927307
    else:
        r = 329.698727446 * (k - 60) ** -0.1332047592
        g = 288.1221695283 * (k - 60) ** -0.0755148492
        b = 255
    return "#%02x%02x%02x" % tuple(int(max(0, min(255, v))) for v in (r, g, b))


def _mix(hexes):
    if not hexes:
        return None
    rgb = [tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) for h in hexes]
    return "#%02x%02x%02x" % tuple(int(sum(c[i] for c in rgb) / len(rgb)) for i in range(3))


# ---------------------------------------------------------------- Ansicht

def light_view(l, room_of, reachable):
    ct = l.get("color_temperature") or {}
    col = l.get("color") or {}
    schema = ct.get("mirek_schema") or {}
    on = bool((l.get("on") or {}).get("on"))
    bri = (l.get("dimming") or {}).get("brightness")
    mode = "ct" if ct.get("mirek_valid") and ct.get("mirek") else ("xy" if col.get("xy") else None)
    if mode == "ct":
        shown = mirek_to_hex(ct["mirek"])
    elif mode == "xy":
        shown = xy_to_hex(col["xy"]["x"], col["xy"]["y"])
    else:
        shown = "#ffd9a0"   # nur dimmbar: warmweiss anzeigen
    owner = (l.get("owner") or {}).get("rid")
    return {
        "id": l["id"],
        # v1-Kennung ("/lights/18" -> "18"): das Dashboard speichert seine
        # Sortierung je Geraet unter diesen IDs — so bleibt sie beim Umstieg erhalten.
        "v1": (l.get("id_v1") or "").rsplit("/", 1)[-1] or None,
        "name": (l.get("metadata") or {}).get("name", "?"),
        "archetype": (l.get("metadata") or {}).get("archetype"),
        "on": on,
        "brightness": round(bri, 1) if bri is not None else None,
        "dimmable": "dimming" in l,
        "color": bool(col),
        "xy": col.get("xy"),
        "gamut": col.get("gamut"),
        "ct": bool(schema),
        "mirek": ct.get("mirek") if mode == "ct" else None,
        "mirek_min": schema.get("mirek_minimum"),
        "mirek_max": schema.get("mirek_maximum"),
        "mode": mode,
        "hex": shown,
        "room": room_of.get(owner),
        "reachable": reachable.get(owner, True),
        # eingebaute Bridge-Effekte (laufen in der Lampe, keine Funk-Last)
        "effects": [e for e in (l.get("effects") or {}).get("effect_values", []) if e != "no_effect"],
        "effect": ((l.get("effects") or {}).get("status") or "no_effect"),
        "signals": [x for x in (l.get("signaling") or {}).get("signal_values", []) if x != "no_signal"],
    }


def build_view(res):
    """``res``: {rtype: {id: obj}} -> {rooms, lights, scenes, home}."""
    rooms_raw = res.get("room", {})
    zones_raw = res.get("zone", {})
    gl = res.get("grouped_light", {})

    # Raeume enthalten GERAETE; Lampen gehoeren einem Geraet.
    room_of = {}
    for r in rooms_raw.values():
        for c in r.get("children") or []:
            if c.get("rtype") == "device":
                room_of[c["rid"]] = r["id"]
    reachable = {}
    for z in res.get("zigbee_connectivity", {}).values():
        owner = (z.get("owner") or {}).get("rid")
        reachable[owner] = z.get("status") == "connected"

    lights = {lid: light_view(l, room_of, reachable) for lid, l in res.get("light", {}).items()}

    def group_of(obj):
        for s in obj.get("services") or []:
            if s.get("rtype") == "grouped_light":
                return s["rid"]
        return None

    rooms = {}
    for kind, src in (("room", rooms_raw), ("zone", zones_raw)):
        for rid, r in src.items():
            if kind == "room":
                members = [l["id"] for l in lights.values() if l["room"] == rid]
            else:
                ids = {c["rid"] for c in r.get("children") or [] if c.get("rtype") == "light"}
                members = [lid for lid in lights if lid in ids]
            g = gl.get(group_of(r)) or {}
            on_lights = [lights[m] for m in members if lights[m]["on"]]
            bri = None
            if on_lights:
                vals = [l["brightness"] for l in on_lights if l["brightness"] is not None]
                bri = round(sum(vals) / len(vals), 1) if vals else None
            rooms[rid] = {
                "id": rid,
                "v1": (r.get("id_v1") or "").rsplit("/", 1)[-1] or None,
                "kind": kind,
                "name": (r.get("metadata") or {}).get("name", "?").lstrip("."),
                "archetype": (r.get("metadata") or {}).get("archetype"),
                "group": group_of(r),
                # an/aus kommt aus grouped_light (das ist any_on), die
                # Helligkeit aus den EINGESCHALTETEN Lampen — nicht der letzte Befehl.
                "on": bool((g.get("on") or {}).get("on")) if g else bool(on_lights),
                "brightness": bri,
                "lights": sorted(members, key=lambda m: lights[m]["name"]),
                "on_count": len(on_lights),
                "hex": _mix([l["hex"] for l in on_lights]),
                "color": any(lights[m]["color"] for m in members),
                "ct": any(lights[m]["ct"] for m in members),
            }

    scenes = {}
    for sid, s in res.get("scene", {}).items():
        colors = []
        for a in s.get("actions") or []:
            act = a.get("action") or {}
            if (act.get("color") or {}).get("xy"):
                xy = act["color"]["xy"]
                colors.append(xy_to_hex(xy["x"], xy["y"]))
            elif (act.get("color_temperature") or {}).get("mirek"):
                colors.append(mirek_to_hex(act["color_temperature"]["mirek"]))
        status = (s.get("status") or {}).get("active", "inactive")
        scenes[sid] = {
            "id": sid,
            "name": (s.get("metadata") or {}).get("name", "?"),
            "room": (s.get("group") or {}).get("rid"),
            "colors": colors[:5],
            "active": status != "inactive",
        }

    home = next((g for g in gl.values() if (g.get("owner") or {}).get("rtype") == "bridge_home"), None)
    return {
        "rooms": rooms,
        "lights": lights,
        "scenes": scenes,
        "home": {"group": home["id"] if home else None,
                 "any_on": any(l["on"] for l in lights.values())},
    }


def deep_merge(dst, src):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_merge(dst[k], v)
        else:
            dst[k] = copy.deepcopy(v)
    return dst


def diff_views(old, new):
    """Nur geaenderte Eintraege — das ist das ``delta``, das die Browser bekommen."""
    out = {}
    for part in ("rooms", "lights", "scenes"):
        o, n = old.get(part, {}), new.get(part, {})
        changed = {k: v for k, v in n.items() if o.get(k) != v}
        removed = [k for k in o if k not in n]
        if changed or removed:
            out[part] = changed
            if removed:
                out.setdefault("removed", {})[part] = removed
    if old.get("home") != new.get("home"):
        out["home"] = new["home"]
    return out


# ---------------------------------------------------------------- Speicher

class HueState:
    def __init__(self, bridge, clock=time.time, retry_min=1.0):
        self.bridge = bridge
        self.retry_min = retry_min
        self.clock = clock
        self.lock = threading.Lock()
        self.res = {r: {} for r in RESOURCES}
        self.view = {"rooms": {}, "lights": {}, "scenes": {}, "home": {}}
        self.subs = []
        self.connected = False
        self.last_event = None
        self.last_sync = None
        self.errors = deque(maxlen=20)
        self._stop = threading.Event()

    # Abonnenten (SSE) ------------------------------------------------------
    def subscribe(self, limit=None):
        """Neuer Abonnent; mit ``limit`` atomar gedeckelt (None = voll). Pruefen
        und Eintragen unter EINER Sperre — getrennt liessen sich gleichzeitige
        Anfragen am Deckel vorbeischieben (Security-Review 2026-10-11)."""
        q = queue.Queue(maxsize=500)
        with self.lock:
            if limit is not None and len(self.subs) >= limit:
                return None
            self.subs.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.subs:
                self.subs.remove(q)

    def publish(self, msg):
        with self.lock:
            subs = list(self.subs)
        for q in subs:
            try:
                q.put_nowait(msg)
            except queue.Full:
                # ein haengender Browser darf die anderen nicht aufhalten
                self.unsubscribe(q)

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.view)

    def note_error(self, where, msg):
        self.errors.append({"at": self.clock(), "where": where, "msg": str(msg)[:200]})

    # Abgleich --------------------------------------------------------------
    def full_sync(self):
        res = {r: {} for r in RESOURCES}
        for item in self.bridge.get():
            t = item.get("type")
            if t in res:
                res[t][item["id"]] = item
        self._replace(res, kind="snapshot")
        self.last_sync = self.clock()

    def _replace(self, res, kind):
        new = build_view(res)
        with self.lock:
            old = self.view
            self.res = res
            self.view = new
        if kind == "snapshot":
            self.publish({"type": "snapshot", "data": new})
        else:
            d = diff_views(old, new)
            if d:
                self.publish({"type": "delta", "data": d})

    def apply_events(self, batch):
        with self.lock:
            res = copy.deepcopy(self.res)
        touched = False
        for ev in batch:
            item, kind = ev["item"], ev["kind"]
            t, i = item.get("type"), item.get("id")
            if t not in res or not i:
                continue
            touched = True
            if kind == "delete":
                res[t].pop(i, None)
            elif kind == "add" or i not in res[t]:
                res[t][i] = item
            else:
                deep_merge(res[t][i], item)
        self.last_event = self.clock()
        if touched:
            self._replace(res, kind="delta")

    # Hintergrund-Thread ----------------------------------------------------
    def run(self):
        backoff = self.retry_min
        while not self._stop.is_set():
            try:
                self.full_sync()
                self.connected = True
                backoff = self.retry_min
                self.publish({"type": "status", "data": self.status()})
                for batch in self.bridge.events():
                    self.apply_events(batch)
                    if self._stop.is_set():
                        return
                raise ConnectionError("Event-Stream beendet")
            except Exception as e:  # noqa: BLE001 — jeder Abbruch heisst: neu verbinden
                was = self.connected
                self.connected = False
                self.note_error("stream", e)
                if was:
                    self.publish({"type": "status", "data": self.status()})
                self._stop.wait(backoff)
                backoff = min(30, backoff * 2)

    def start(self):
        t = threading.Thread(target=self.run, name="hue-state", daemon=True)
        t.start()
        return t

    def stop(self):
        self._stop.set()

    def status(self):
        return {
            "connected": self.connected,
            "last_event": self.last_event,
            "last_sync": self.last_sync,
            "subscribers": len(self.subs),
            "errors": list(self.errors)[-5:],
        }
