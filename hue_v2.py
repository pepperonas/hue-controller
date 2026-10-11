"""Hue-Bridge-Client fuer die CLIP-API v2 (2026-10-11).

v2 statt v1, weil nur v2 einen Event-Stream hat: die Bridge meldet jede
Aenderung selbst (auch aus der Philips-App, von Schaltern, von Automationen)
und wir muessen nicht mehr pollen. Der v1-Benutzername gilt in v2 als
``hue-application-key``.

TLS: die Bridge spricht nur HTTPS mit einem selbstsignierten Zertifikat, dessen
Name die Bridge-ID ist, nicht die IP — eine normale Pruefung scheitert also
immer. Wir sprechen sie im Heimnetz per fester IP an; ``HUE_TLS_VERIFY`` kann
auf einen CA-Pfad zeigen, wenn jemand die Hue-Root-CA hinterlegen will.
"""
import json
import os
import time

import requests
import urllib3

TIMEOUT = (3, 5)            # (Verbindung, Lesen) fuer normale Aufrufe
STREAM_TIMEOUT = (5, 90)    # Event-Stream: die Bridge schickt regelmaessig ": hi"


class BridgeError(Exception):
    pass


class Bridge:
    def __init__(self, ip, key, verify=None, session=None):
        self.ip = ip
        self.key = key
        self.base = "https://%s" % ip
        if verify is None:
            verify = os.environ.get("HUE_TLS_VERIFY") or False
        self.verify = verify
        if verify is False:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self.s = session or requests.Session()
        self.s.headers.update({"hue-application-key": key})

    # ------------------------------------------------------------ Ressourcen

    def get(self, rtype=None):
        path = "/clip/v2/resource" + ("/" + rtype if rtype else "")
        r = self.s.get(self.base + path, timeout=TIMEOUT, verify=self.verify)
        return self._data(r)

    def put(self, rtype, rid, body):
        r = self.s.put("%s/clip/v2/resource/%s/%s" % (self.base, rtype, rid),
                       json=body, timeout=TIMEOUT, verify=self.verify)
        return self._data(r)

    def post(self, rtype, body):
        r = self.s.post("%s/clip/v2/resource/%s" % (self.base, rtype),
                        json=body, timeout=TIMEOUT, verify=self.verify)
        return self._data(r)

    def delete(self, rtype, rid):
        r = self.s.delete("%s/clip/v2/resource/%s/%s" % (self.base, rtype, rid),
                          timeout=TIMEOUT, verify=self.verify)
        return self._data(r)

    @staticmethod
    def _data(r):
        try:
            body = r.json()
        except ValueError:
            raise BridgeError("HTTP %s ohne JSON" % r.status_code)
        errs = [e.get("description", str(e)) for e in body.get("errors") or []]
        if r.status_code >= 400 or errs:
            raise BridgeError("; ".join(errs) or "HTTP %s" % r.status_code)
        return body.get("data") or []

    # ------------------------------------------------------------ Event-Stream

    def events(self):
        """Liefert Listen von Event-Objekten, solange die Verbindung steht.
        Bricht mit einer Ausnahme ab, wenn sie reisst — der Aufrufer verbindet neu."""
        r = self.s.get(self.base + "/eventstream/clip/v2",
                       headers={"Accept": "text/event-stream"},
                       stream=True, timeout=STREAM_TIMEOUT, verify=self.verify)
        if r.status_code != 200:
            raise BridgeError("Event-Stream HTTP %s" % r.status_code)
        for batch in parse_sse(r.iter_lines(decode_unicode=True)):
            yield batch


def parse_sse(lines):
    """SSE-Zeilen -> Listen von Events. Jede ``data:``-Zeile der Bridge ist ein
    JSON-Array von Container-Objekten mit eigenem ``data``-Array."""
    buf = []
    for line in lines:
        if line is None:
            continue
        if line == "":
            if buf:
                raw = "\n".join(buf)
                buf = []
                try:
                    containers = json.loads(raw)
                except ValueError:
                    continue
                out = []
                for c in containers if isinstance(containers, list) else []:
                    for item in c.get("data") or []:
                        out.append({"kind": c.get("type"), "item": item})
                if out:
                    yield out
            continue
        if line.startswith("data:"):
            buf.append(line[5:].lstrip())


def now():
    return time.time()
