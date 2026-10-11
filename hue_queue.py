"""Befehls-Warteschlange zur Bridge (2026-10-11).

Die Bridge vertraegt ~10 Lampen-Befehle/s und je Gruppe etwa einen pro
Sekunde; was darueber geht, verwirft sie still. Ein Helligkeits-Slider erzeugt
beim Ziehen aber Dutzende Werte pro Sekunde. Deshalb:

* **Koaleszenz:** je Ziel (Lampe / grouped_light) liegt hoechstens EIN Befehl
  in der Schlange; ein neuer Wert ersetzt Felder des alten (letzter gewinnt).
* **Budget:** Lampen per Token-Bucket (10/s), Gruppen mit Mindestabstand je
  Gruppe und globaler Obergrenze.
* **Fehler** gehen per Rueckruf an den Zustand (-> SSE ``error``), damit die
  Oberflaeche ihren optimistischen Wert zuruecknimmt.

Alles mit injizierbarer Uhr + Senden, daher ohne Bridge und ohne Warten testbar.
"""
import threading
import time
from collections import OrderedDict

LIGHT_RATE = 10.0          # Befehle pro Sekunde an einzelne Lampen
LIGHT_BURST = 10
GROUP_MIN_GAP = 0.4        # Sekunden zwischen zwei Befehlen an DIESELBE Gruppe
GROUP_RATE = 3.0           # Gruppenbefehle pro Sekunde insgesamt


class CommandQueue:
    def __init__(self, send, on_error=None, clock=time.monotonic,
                 light_rate=LIGHT_RATE, light_burst=LIGHT_BURST,
                 group_gap=GROUP_MIN_GAP, group_rate=GROUP_RATE):
        self.send = send                  # send(rtype, rid, body) -> wirft bei Fehler
        self.on_error = on_error or (lambda *a: None)
        self.clock = clock
        self.light_rate, self.light_burst = light_rate, light_burst
        self.group_gap, self.group_rate = group_gap, group_rate
        self.pending = OrderedDict()      # (rtype, rid) -> body
        self.tokens = float(light_burst)
        self.last_fill = clock()
        self.group_last = {}              # rid -> Zeitpunkt
        self.group_sent = []              # Zeitpunkte der letzten Gruppenbefehle
        self.cv = threading.Condition()
        self.sent = 0
        self.coalesced = 0
        self.failed = 0
        self._stop = False

    # ------------------------------------------------------------ Annahme

    def submit(self, rtype, rid, body):
        key = (rtype, rid)
        with self.cv:
            if key in self.pending:
                merge(self.pending[key], body)
                self.coalesced += 1
            else:
                self.pending[key] = dict(body)
            self.cv.notify()

    # ------------------------------------------------------------ Takt

    def _refill(self, now):
        self.tokens = min(self.light_burst, self.tokens + (now - self.last_fill) * self.light_rate)
        self.last_fill = now

    def _ready(self, key, now):
        rtype, rid = key
        if rtype == "grouped_light":
            if now - self.group_last.get(rid, -1e9) < self.group_gap:
                return False
            recent = [t for t in self.group_sent if now - t < 1.0]
            return len(recent) < self.group_rate
        return self.tokens >= 1.0

    def take(self):
        """Naechster sendbarer Befehl oder ``(None, wartezeit)``."""
        with self.cv:
            now = self.clock()
            self._refill(now)
            self.group_sent = [t for t in self.group_sent if now - t < 1.0]
            for key in list(self.pending):
                if self._ready(key, now):
                    body = self.pending.pop(key)
                    if key[0] == "grouped_light":
                        self.group_last[key[1]] = now
                        self.group_sent.append(now)
                    else:
                        self.tokens -= 1.0
                    return key, body
            return None, (0.05 if self.pending else None)

    def step(self):
        """Einen Befehl senden, falls einer bereit ist. Liefert True, wenn gesendet."""
        key, body = self.take()
        if key is None:
            return False
        try:
            self.send(key[0], key[1], body)
            self.sent += 1
        except Exception as e:  # noqa: BLE001
            self.failed += 1
            self.on_error(key[0], key[1], body, e)
        return True

    def run(self):
        while not self._stop:
            if self.step():
                continue
            with self.cv:
                # Wartet etwas an (Budget), kurz nachsehen; sonst bis zum naechsten submit.
                self.cv.wait(timeout=0.05 if self.pending else 1.0)

    def start(self):
        t = threading.Thread(target=self.run, name="hue-queue", daemon=True)
        t.start()
        return t

    def stop(self):
        self._stop = True
        with self.cv:
            self.cv.notify_all()

    def stats(self):
        with self.cv:
            return {"pending": len(self.pending), "sent": self.sent,
                    "coalesced": self.coalesced, "failed": self.failed}


def merge(dst, src):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            merge(dst[k], v)
        else:
            dst[k] = v
    # Farbe XOR Farbtemperatur: der juengere Modus gewinnt, sonst schickt ein
    # Zug am Farbrad nach einem Temperatur-Klick beide Felder und die Bridge
    # nimmt das zuletzt geparste.
    if "color" in src and "color_temperature" in dst:
        dst.pop("color_temperature", None)
    if "color_temperature" in src and "color" in dst:
        dst.pop("color", None)
    return dst
