"""Parser tests — every source, driven by committed fixtures (offline)."""

import json
from datetime import date, datetime, timedelta, timezone

from conftest import TODAY, TZ

from kyros.sources import (cerebralvalley, dothebay, funcheap, stanford,
                           visitsanjose)


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



# --- Stanford ---------------------------------------------------------------

def _stanford(fixture_text, log):
    return stanford.parse_payload(
        json.loads(fixture_text("stanford_events.json")), log)


def test_stanford_keeps_only_public_timed_in_person(fixture_text, log):
    titles = [e.title for e in _stanford(fixture_text, log)]
    assert [t.split(":")[0] for t in titles] == [
        "Public Tour | A Closer Look",
        "Stanford Energy Seminar | AI for Climate Solutions",
        "Challenge Success Annual Conference",
        "Explore Energy Seminar | Stanford's Top-Flight Energy Complex",
    ]
    # Dropped: an all-day academic date, a PhD defense for faculty and
    # students, a virtual deadline, and a students-only treasure hunt.


def test_stanford_cost_and_free(fixture_text, log):
    tour, seminar, conference, _ = _stanford(fixture_text, log)
    assert tour.is_free and tour.price_min == 0
    assert conference.price_min == 1095.0 and not conference.is_free
    assert seminar.price_min is None and not seminar.is_free


def test_stanford_ignores_bad_coordinates(fixture_text, log):
    """Localist geocoded "Central Energy Facility" to Australia."""
    from kyros import geo
    energy = _stanford(fixture_text, log)[3]
    assert energy.lat is None and energy.lon is None
    geo.resolve(energy)
    assert energy.city == "stanford" and energy.region == "peninsula"


def test_stanford_ai_talk_and_museum_tour_classify(fixture_text, log):
    from kyros import classify as C
    from kyros import geo
    tour, seminar, *_ = _stanford(fixture_text, log)
    for e in (tour, seminar):
        geo.resolve(e)
    assert C.AI in C.classify(seminar)
    # A museum tour is not a concert tour.
    assert C.CONCERT not in C.classify(tour)
    assert C.COMMUNITY in C.classify(tour)


def test_stanford_fetch_pages_until_total(fixture_text, log, monkeypatch):
    import urllib.parse

    captured = []
    body = json.loads(fixture_text("stanford_events.json"))
    body["page"]["total"] = 2

    def fake_get(url, log, headers=None):
        captured.append(url)
        return json.dumps(body).encode()

    monkeypatch.setattr(stanford, "http_get", fake_get)
    events = stanford.fetch({"lookahead_days": 30}, log)
    assert len(captured) == 2 and len(events) == 8
    base, query = captured[1].split("?", 1)
    assert base == stanford.API_URL
    params = dict(urllib.parse.parse_qsl(query))
    assert params == {"days": "30", "pp": "100", "page": "2"}


# --- DoTheBay ---------------------------------------------------------------

def _dtb(fixture_text, log):
    return {e.title: e for e in dothebay.parse_payload(
        json.loads(fixture_text("dothebay_day.json")), log)}


def test_dothebay_uses_tz_adjusted_start(fixture_text, log):
    """`begin_time` says -05:00 for a Berkeley show; the adjusted field is
    the real local time."""
    batiste = _dtb(fixture_text, log)["Jon Batiste"]
    local = batiste.start.astimezone(TZ)
    assert (local.hour, local.minute) == (18, 30)
    assert batiste.venue == "Greek Theatre"
    assert batiste.lat and abs(batiste.lat - 37.87) < 0.01


def test_dothebay_prices(fixture_text, log):
    evs = _dtb(fixture_text, log)
    assert (evs["Jantsen"].price_min, evs["Jantsen"].price_max) == (25.0, 30.0)
    assert evs["Death From Above 1979"].price_max == 77.16
    popup = next(e for t, e in evs.items() if t.startswith("Pop-Ups"))
    assert popup.is_free and popup.price_min == 0
    assert evs["Jon Batiste"].price_min is None  # "All ages" is no price


def test_dothebay_club_venue_reaches_edm(fixture_text, log):
    from kyros import classify as C
    jantsen = _dtb(fixture_text, log)["Jantsen"]
    assert "Electronic" in jantsen.genres
    assert C.classify(jantsen) == {C.EDM}
    assert C.classify(_dtb(fixture_text, log)["Jon Batiste"]) == {C.CONCERT}


def test_dothebay_clips_multi_week_runs(fixture_text, log):
    run = _dtb(fixture_text, log)["Little Shop of Horrors"]
    assert run.end - run.start <= timedelta(hours=2)


def test_dothebay_fetch_dedups_across_days(fixture_text, log, monkeypatch):
    captured = []

    def fake_get(url, log, headers=None):
        captured.append(url)
        return fixture_text("dothebay_day.json").encode()

    monkeypatch.setattr(dothebay, "http_get", fake_get)
    events = dothebay.fetch({"lookahead_days": 3}, log)
    # total_pages=1 in the fixture, so one page per day.
    assert len(captured) == 3
    assert all(u.startswith("https://dothebay.com/events/20") and
               u.endswith(".json?page=1") for u in captured)
    assert len(events) == 5   # same listings every day, kept once


# --- Cerebral Valley --------------------------------------------------------

def _cv(fixture_text, log):
    return cerebralvalley.parse_payload(
        json.loads(fixture_text("cerebralvalley_events.json")), log)


def test_cerebralvalley_keeps_california_only(fixture_text, log):
    """"Dublin 8, Ireland" would otherwise resolve to Dublin, CA."""
    titles = [e.title for e in _cv(fixture_text, log)]
    assert titles == ["Build Your AI Co-Founder Hackathon",
                      "ThinkingAI Agentic Growth Summit 2026", "Hard Things"]


def test_cerebralvalley_times_are_utc(fixture_text, log):
    hack = _cv(fixture_text, log)[0]
    assert hack.start == datetime(2026, 9, 28, 19, 0, tzinfo=timezone.utc)
    assert hack.start.astimezone(TZ).hour == 12
    assert hack.location == "3120 Scott Blvd, Santa Clara, California"
    assert hack.url == "https://luma.com/i8976ew3789"


def test_cerebralvalley_ai_still_needs_ai_words(fixture_text, log):
    from kyros import classify as C
    hack, summit, hard = _cv(fixture_text, log)
    assert C.AI in C.classify(hack) and C.AI in C.classify(summit)
    assert C.AI not in C.classify(hard)


def test_cerebralvalley_fetch_request(fixture_text, log, monkeypatch):
    import urllib.parse

    captured = []

    def fake_get(url, log, headers=None):
        captured.append(url)
        return fixture_text("cerebralvalley_events.json").encode()

    monkeypatch.setattr(cerebralvalley, "http_get", fake_get)
    cerebralvalley.fetch({"lookahead_days": 3650}, log)
    assert len(captured) == 1   # offset reaches totalCount
    base, query = captured[0].split("?", 1)
    assert base == cerebralvalley.API_URL
    params = dict(urllib.parse.parse_qsl(query))
    assert params["approved"] == "true" and params["limit"] == "100"
    assert params["offset"] == "0" and params["startDateTime"].endswith("Z")


# --- Visit San Jose ---------------------------------------------------------

def _vsj_listings(fixture_text):
    return json.loads(fixture_text("visitsanjose_listings.json"))


def test_visitsanjose_selects_short_runs_in_window(fixture_text):
    picked = visitsanjose.select_listings(
        _vsj_listings(fixture_text), date(2026, 9, 28), 30)
    titles = [i["title"] for i in picked]
    # Sonic Runway runs 2021-2027 (an installation); 9/27 is past.
    assert titles == ["Las Alucines", "Oktoberfest at San Pedro Square Market",
                      "Trick-or-Treat The Row Halloween Family Festival"]
    assert picked[0]["_date"] == date(2026, 9, 30)


def test_visitsanjose_detail_time(fixture_text):
    assert visitsanjose.detail_time(
        fixture_text("visitsanjose_detail.html")) == (20, 30)
    assert visitsanjose.detail_time("<p>no time here</p>") is None
    assert visitsanjose.description_time("Doors at 7:30pm") == (19, 30)


def test_visitsanjose_make_event(fixture_text):
    from kyros import classify as C
    from kyros import geo
    item = visitsanjose.select_listings(
        _vsj_listings(fixture_text), date(2026, 9, 28), 30)[0]
    ev = visitsanjose.make_event(item, (20, 30), TZ,
                                 street="135 West San Carlos Street, ")
    assert ev.start == datetime(2026, 9, 30, 20, 30, tzinfo=TZ)
    assert ev.url == "https://www.sanjose.org/theaters/events/las-alucines"
    assert ev.location == ("San Jose Civic, 135 West San Carlos Street, "
                           "San Jose, CA")
    assert "Music" in ev.genres and "Latin" in ev.genres
    geo.resolve(ev)
    assert ev.city == "san jose"
    assert C.CONCERT in C.classify(ev)


def test_visitsanjose_ballet_is_not_edm():
    """Categories "Dance, Music" once read as "dance music"."""
    from kyros import classify as C
    item = {"title": "Georgian National Ballet", "link": "/events/gnb",
            "categories": "Dance, Music, Stage &amp; Theater",
            "venue": "California Theatre", "city": "San Jose",
            "_date": date(2026, 10, 13)}
    ev = visitsanjose.make_event(item, (20, 0), TZ)
    assert C.EDM not in C.classify(ev)
    assert C.CONCERT in C.classify(ev)


def test_visitsanjose_fetch_drops_untimed(fixture_text, log, monkeypatch):
    detail = fixture_text("visitsanjose_detail.html")

    def fake_get(url, log, headers=None):
        if url == visitsanjose.LISTINGS_URL:
            return fixture_text("visitsanjose_listings.json").encode()
        if url.endswith("/las-alucines"):
            return detail.encode()
        return b"<html>no when block</html>"

    monkeypatch.setattr(visitsanjose, "http_get", fake_get)
    monkeypatch.setattr(visitsanjose, "datetime", _FrozenDatetime)
    events = visitsanjose.fetch({"lookahead_days": 30}, log)
    # Las Alucines: time from the detail page. Trick-or-Treat: "10 AM" in
    # its description. Oktoberfest has neither and is dropped.
    assert [(e.title[:14], e.start.hour) for e in events] == [
        ("Las Alucines", 20), ("Trick-or-Treat", 10)]


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 9, 28, 12, 0, tzinfo=tz)
