# Hue Controller

Philips-Hue-Steuerung für den Raspberry Pi 5 im Heimnetz: Räume, Szenen, Farbe,
Effekte, Energie und Automationen. Läuft unter `https://home.celox.io:8443/app/hue/`
und speist die Karte „Wohnung“ im Home-Dashboard.

## Was sie kann

- **Live:** Die App hört dem Event-Stream der Bridge (CLIP API v2) zu. Änderungen
  aus der Philips-App, von Schaltern oder Automationen erscheinen in ~0,1 s.
  Gepollt wird nicht, außer als Rückfall bei getrennter Verbindung.
- **Räume:** Kachel mit echter Lichtfarbe, Schalter und Live-Dimmer. Ein Tipp öffnet
  den Raum: Stimmungen (Hell, Konzentration, Lesen, Gemütlich, Entspannen, Nachtlicht),
  eigene Szenen samt „aktuellen Zustand speichern“, Farbrad mit Klemmung auf den
  Farbraum jeder Lampe, Weißton in Kelvin, die einzelnen Lampen.
- **Effekte:** Eingebaute Bridge-Effekte (Kerze, Feuer, Prisma, Funkeln, Opal,
  Glitzern, Unterwasser, Kosmos, Sonnenstrahl, Zauber). Sie laufen in den Lampen
  selbst und erzeugen keine Funklast. Strobo per eingebautem Signaling, mit
  Epilepsie-Warnung.
- **Automation:** Zeitpläne (Uhrzeit oder Sonnenauf-/-untergang ± Minuten,
  Sommerzeit korrekt), Lichtwecker, Bewegungsmelder (PIR an GPIO 26) und
  Abwesenheit mit optionalem „bewohnt wirken“.
- **Anordnen per Drag-and-drop:** Alle Karten lassen sich ziehen: Räume, Lampen im Raum,
  Szenen-, Automations-, Energie- und Status-Karten. SortableJS 1.15.6 (MIT) liegt lokal
  unter `static/vendor/`, ohne CDN. Das Verhalten ist wie in ops und cue: frei schwebende
  Vorschau, die anderen Karten machen Platz, die Maus startet nach 6 px, Touch nach 180 ms
  Halten, Auto-Scroll, Alt + Pfeiltasten. Schalter und Regler starten keinen Zug.
  Die Reihenfolge gilt je Gerät (localStorage `hue-order:*`).
- **Energie:** Geschätzter Verbrauch (Helligkeit × 9 W je Lampe) mit Verlauf,
  Wochentagen und Monaten aus der MariaDB `hue_monitoring`.

## Architektur

```
Browser ──HTTPS──> nginx (raspi5) ──> waitress :5000 (app_lite.py)
                     /app/hue/            ├─ hue_api_v2  /api/v2/*   (neu)
                     /proxy/hue/api/      ├─ hue_state   Zustand + Event-Stream der Bridge
                     …/v2/events (SSE,    ├─ hue_queue   Befehls-Warteschlange
                      ungepuffert)        ├─ hue_automation + sun   Regeln, Planer, PIR
                                          └─ /api/*  v1-Altbestand (Energie, alte Oberfläche)
```

- **Befehls-Warteschlange:** Je Lampe bzw. Gruppe liegt höchstens ein Befehl
  bereit, ein neuer Wert ersetzt den alten (beim Ziehen eines Reglers kommt nur
  der letzte an). Budget: 10 Lampenbefehle/s, Gruppen mit 0,4 s Mindestabstand.
  Fehler gehen als `fail`-Event an die Oberfläche, die dann ihren optimistischen
  Wert zurücknimmt.
- **Oberfläche:** `public/index.html` plus ES-Module unter `static/app/`, ohne Build.
  Nur Haus-Tokens und der `sh-*`-Dialekt aus `/shared/`, Dark und Light automatisch.
  Namen gehen nur per `textContent` ins DOM. Der Service Worker liegt unter `/sw.js`,
  damit sein Scope die App ist.
- **Alte Oberfläche:** liegt bis zur Abnahme unter `/app/hue/alt/` (`public/legacy.html`).

## API v2 (Auszug)

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/v2/state` | Räume, Lampen, Szenen, Stimmungen, Effekte |
| GET | `/api/v2/events` | SSE: `snapshot`, `delta`, `status`, `fail` |
| PUT | `/api/v2/light/<id>`, `/api/v2/room/<id>` | `{on, brightness, xy, mirek, transition_ms}` |
| POST | `/api/v2/room/<id>/mood` · `/scene` · `/effect` · `/signal` | Stimmung, Szene speichern, Effekt, Strobo |
| POST | `/api/v2/scene/<id>/recall` · `/api/v2/all` | Szene, alles an/aus |
| GET/POST/PUT/DELETE | `/api/v2/automations[/<id>]` | Regeln |
| POST | `/api/v2/away` | `{on, simulate}` |
| GET | `/api/v2/status` | Stream, Queue, letzte Fehler |

Schreibende Aufrufe verlangen `Content-Type: application/json` und, falls ein
`Origin` mitkommt, die Haus-Herkunft. Für `/api/v2` gibt es kein CORS.

## Hardware

PIR-Bewegungsmelder an **GPIO 26 (Pin 37)**, VCC 5 V, GND. Angesprochen wird er per
`gpiozero` mit der Pin-Fabrik **lgpio**; `RPi.GPIO` läuft auf dem Pi 5 nicht
(„Cannot determine SOC peripheral base address“).

## Betrieb

```bash
# Abhängigkeiten (venv OHNE System-Pakete; das pip im venv ist kaputt -> System-pip nutzen)
/usr/bin/python3 -m pip --python venv/bin/python install -r requirements.txt

# Deploy (Checkout auf dem Pi weicht ab -> Dateien per scp, Repo ist die Wahrheit)
scp app_lite.py hue_*.py sun.py raspi5:/home/pi/apps/hue-controller/
rsync -a static/app raspi5:/home/pi/apps/hue-controller/static/
scp public/index.html raspi5:/home/pi/apps/hue-controller/public/
ssh raspi5 'sudo systemctl restart hue-controller'   # Jinja-Cache: Neustart nötig
```

- **Konfiguration:** `.env` mit `HUE_BRIDGE_IP`, `HUE_USERNAME` (Pflicht, kein
  Standardwert im Code), `HUE_TLS_FINGERPRINT` (Pflicht: SHA-256 des Bridge-Zertifikats,
  angeheftet statt abgeschalteter TLS-Prüfung; auslesen mit
  `echo | openssl s_client -connect <bridge>:443 | openssl x509 -noout -fingerprint -sha256`), `DB_*`.
- **Automationen:** Regeln liegen in `automations.db` (SQLite, nicht im Repo, in der
  nächtlichen Sicherung von `/home/pi/apps`).
- **Verpasste Termine:** Fällige Termine während einer Ausfallzeit werden nicht
  nachgeholt. Ein Wecker um 6:30 soll nicht um 9:10 losgehen.

## Tests

```bash
python3 -m pytest -q tests/        # Backend: v2, Queue, Automation, Sonne, Fixes
node --test tests/*.mjs            # Oberfläche (DOM-frei) + alte Oberfläche
```

Für den CORS-Test und den Jahresvergleich der Sonnenzeiten braucht das venv
`flask-cors` bzw. `astral`; fehlen sie, werden diese Tests übersprungen.
