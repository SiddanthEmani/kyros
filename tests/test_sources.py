"""Parser tests — every source, driven by committed fixtures (offline)."""

import json

from conftest import TODAY, TZ

from kyros.sources import funcheap, ticketmaster


# --- Ticketmaster -----------------------------------------------------------

def _tm(fixture_text, log):
    payload = json.loads(fixture_text("ticketmaster_events.json"))
    return ticketmaster.parse_payload(payload, "ticketmaster/music", log)


def test_ticketmaster_maps_venue_and_coords(fixture_text, log):
    ev = _tm(fixture_text, log)[0]
    assert ev.venue == "SAP Center at San Jose"
    assert ev.lat and abs(ev.lat - 37.3327) < 0.001
    assert "San Jose" in ev.location
    assert ev.calendar_name == "Another Planet Entertainment"


def test_ticketmaster_price_ranges(fixture_text, log):
    paid, free = _tm(fixture_text, log)[:2]
    assert (paid.price_min, paid.price_max) == (55.0, 125.0)
    assert not paid.is_free
    assert free.is_free and free.price_min == 0


def test_ticketmaster_drops_time_tba(fixture_text, log):
    """Date-only listings would land at midnight and mislead the feed."""
    titles = [e.title for e in _tm(fixture_text, log)]
    assert "Date To Be Announced Show" not in titles
    assert len(titles) == 2


def test_ticketmaster_genres_skip_undefined(fixture_text, log):
    _paid, free = _tm(fixture_text, log)[:2]
    assert "Undefined" not in free.genres
    assert "Music" in free.genres


def test_ticketmaster_no_key_returns_empty(monkeypatch, log):
    monkeypatch.delenv(ticketmaster.ENV_KEY, raising=False)
    assert ticketmaster.fetch({}, log) == []


# --- Funcheap ---------------------------------------------------------------

def _funcheap(fixture_text, log):
    return funcheap.parse_rss(
        fixture_text("funcheap_sanjose.xml"), "san-jose", log,
        tz=TZ, today=TODAY)


def test_funcheap_parses_dates_and_times(fixture_text, log):
    events, skipped = _funcheap(fixture_text, log)
    movie = events[0]
    assert (movie.start.month, movie.start.day) == (9, 12)
    assert (movie.start.hour, movie.start.minute) == (19, 30)
    assert movie.end.hour == 22


def test_funcheap_drops_undated_items(fixture_text, log):
    events, skipped = _funcheap(fixture_text, log)
    assert skipped == 1
    assert all("Ongoing" not in e.title for e in events)


def test_funcheap_cost_extraction(fixture_text, log):
    events, _ = _funcheap(fixture_text, log)
    assert events[0].is_free
    assert events[1].price_min == 5.0 and not events[1].is_free


def test_funcheap_extracts_venue(fixture_text, log):
    events, _ = _funcheap(fixture_text, log)
    assert "Guadalupe River Park" in events[0].venue


def test_ticketmaster_builds_a_valid_request(fixture_text, log, monkeypatch):
    """The request itself, not just the response mapping — a wrong param
    name here is a 400 that only shows up in production."""
    import urllib.parse

    from kyros.config import load_config

    captured = []

    def fake_get(url, log, headers=None):
        captured.append(url)
        return fixture_text("ticketmaster_events.json").encode()

    monkeypatch.setattr(ticketmaster, "http_get", fake_get)
    monkeypatch.setenv(ticketmaster.ENV_KEY, "test-key")
    events = ticketmaster.fetch(load_config(), log)

    assert len(captured) == 1        # totalPages=1 stops the paging loop
    base, query = captured[0].split("?", 1)
    assert base == ticketmaster.API_URL
    params = dict(urllib.parse.parse_qsl(query))
    assert params["apikey"] == "test-key"
    assert params["geoPoint"] == "9q9k6m"      # downtown San Jose
    assert params["radius"] == "50" and params["unit"] == "miles"
    assert params["classificationName"] == "music"
    assert params["sort"] == "date,asc"
    for field in ("startDateTime", "endDateTime"):
        assert params[field].endswith("Z") and "T" in params[field]
    assert len(events) == 2

