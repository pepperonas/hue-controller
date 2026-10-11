"""Pins fuer Korrekturen im Altbestand von app_lite.py (2026-10-11)."""
import os
import re

SRC = open(os.path.join(os.path.dirname(__file__), "..", "app_lite.py"), encoding="utf-8").read()
CODE = re.sub(r"#[^\n]*", "", SRC)   # Kommentare zitieren die alten Fehler


def test_no_connection_pool_that_leaks_shut():
    # 23 Aufrufstellen schliessen nur im Erfolgsfall; mit einem Pool der Groesse 2
    # stand nach zwei Ausnahmen JEDE DB-Abfrage ("pool exhausted").
    assert "MySQLConnectionPool(" not in CODE
    assert "db_pool = ConnectionFactory(MYSQL_CONFIG)" in CODE


def test_factory_drops_pool_keys():
    cls = re.search(r"class ConnectionFactory:.*?\n\n\n", SRC, re.S).group(0)
    assert "not k.startswith('pool_')" in cls
    assert "connection_timeout=" in cls


def test_bridge_key_has_no_default():
    assert re.search(r"HUE_USERNAME = os\.getenv\('HUE_USERNAME', ''\)", CODE)
    assert not re.search(r"getenv\('HUE_USERNAME', '[A-Za-z0-9-]{20,}'\)", CODE)


def test_monthly_cost_converts_decimal_before_multiplying():
    i = CODE.index("month['cost_eur'] = round(")
    assert "month['total_kwh'] = float(" in CODE[i - 200:i]


def test_v1_list_routes_escape_bridge_names_for_the_legacy_ui():
    for route, var in (("lights", "lights"), ("groups", "hue_request('groups')"),
                       ("scenes", "hue_request('scenes')"), ("sensors", "hue_request('sensors')")):
        assert "jsonify(_escape_names(%s))" % var in CODE, route
    fn = re.search(r"def _escape_names\(items\):.*?return items", SRC, re.S).group(0)
    assert "_html.escape(obj['name'], quote=True)" in fn


def test_beat_sync_timer_binds_the_light_id_now():
    i = CODE.index("threading.Timer(0.1, lambda")
    assert CODE[i:i + 80].startswith("threading.Timer(0.1, lambda lid=light_id:")
