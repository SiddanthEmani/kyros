"""Classification, geography, ranking, dedup, caps and feed output."""

from datetime import datetime, timedelta, timezone

import pytest
from conftest import TZ

from kyros import classify as C
from kyros import geo, ics, pipeline, rank
from kyros.config import load_config
from kyros.dedup import merge_duplicates
from kyros.model import Event

def _next_saturday_evening() -> datetime:
    """A near-future Saturday 9 PM local — always clears the schedule filter,
    so tests exercise the filter under test rather than the clock."""
    now = datetime.now(TZ)
    day = now + timedelta(days=(5 - now.weekday()) % 7 + 7)
    return day.replace(hour=21, minute=0, second=0,
                       microsecond=0).astimezone(timezone.utc)


SOON = _next_saturday_evening()


def ev(title, **kw):
    kw.setdefault("start", SOON)
    start = kw.pop("start")
    return Event(kw.pop("event_id", title), title, start,
                 start + timedelta(hours=2), **kw)


# --- classification ---------------------------------------------------------

@pytest.mark.parametrize("title, kwargs, expected", [
    ("Warehouse Techno: b2b all night", {}, {"edm"}),
    ("Dirtybird presents tech house", {}, {"edm"}),
    ("Kaytranada", {"genres": ("Music", "Dance/Electronic")}, {"edm"}),
    ("Metallica: M72 World Tour", {"genres": ("Music", "Rock")}, {"concert"}),
    ("SF Symphony: Mahler 5", {}, {"concert"}),
    ("Building agentic RAG systems", {"calendar_name": "AI Tinkerers"}, {"ai"}),
    ("San Jose Night Market", {}, {"community"}),
    ("Free Outdoor Movie Night", {}, {"community", "free"}),
    ("Happy Hour Networking Drinks", {}, set()),
])
def test_classify(title, kwargs, expected):
    assert C.classify(ev(title, **kwargs)) == expected


def test_free_detection_from_price_fields():
    assert C.is_free(ev("Show", price_min=0.0, price_max=0.0))
    assert not C.is_free(ev("Show", price_min=0.0, price_max=15.0))
    assert C.is_free(ev("Free entry all night"))
    assert not C.is_free(ev("Free before 11pm, $20 after"))


# --- geography --------------------------------------------------------------

@pytest.mark.parametrize("location, city, region", [
    ("525 W Santa Clara St, San Jose, CA", "san jose", "south-bay"),
    ("Sunnyvale, CA", "sunnyvale", "south-bay"),
    ("Palo Alto, CA", "palo alto", "peninsula"),
    ("San Francisco, CA", "san francisco", "sf"),
    ("Oakland, CA", "oakland", "east-bay"),
    ("South San Francisco, CA", "south san francisco", "peninsula"),
])
def test_geo_resolve(location, city, region):
    e = ev("x", location=location)
    geo.resolve(e)
    assert (e.city, e.region) == (city, region)


def test_geo_resolves_venue_when_no_city():
    e = ev("Techno night", venue="1015 Folsom")
    geo.resolve(e)
    assert e.city == "san francisco"


def test_geo_resolve_prefers_coordinates():
    e = ev("x", location="somewhere vague", lat=37.3327, lon=-121.9012)
    geo.resolve(e)
    assert e.city == "san jose"


def test_geo_radius_excludes_far_events():
    cfg = load_config()
    sac = ev("x", lat=38.5816, lon=-121.4944)   # Sacramento, ~90mi
    geo.resolve(sac)
    assert not geo.in_scope(sac, cfg)
    sj = ev("x", lat=37.3327, lon=-121.9012)
    geo.resolve(sj)
    assert geo.in_scope(sj, cfg)


def test_san_jose_outranks_equivalent_sf_event():
    cfg = load_config()
    sj = ev("Techno night", venue="The Ritz", location="San Jose, CA",
            genres=("techno",))
    sf = ev("Techno night", venue="Monarch", location="San Francisco, CA",
            genres=("techno",))
    for e in (sj, sf):
        geo.resolve(e)
        e.categories = C.classify(e)
    assert (rank.category_score(sj, "edm", cfg)
            > rank.category_score(sf, "edm", cfg))


# --- dedup ------------------------------------------------------------------

def test_dedup_merges_same_show_from_two_sources():
    tm = ev("Kaytranada Timeless Tour", event_id="tm-1",
            url="https://ticketmaster.com/1", location="San Jose, CA",
            venue="SAP Center", price_min=55.0, price_max=125.0,
            source="ticketmaster")
    hz = ev("Kaytranada Timeless Tour", event_id="19hz-1",
            location="San Jose, CA", genres=("house",), source="19hz")
    for e in (tm, hz):
        geo.resolve(e)
        e.categories = C.classify(e)
    merged = merge_duplicates([tm, hz], tz=TZ)
    assert len(merged) == 1
    assert merged[0].price_min == 55.0        # kept Ticketmaster's price
    assert "house" in merged[0].genres        # kept 19hz's genres
    assert "19hz" in merged[0].source


def test_dedup_keeps_distinct_events():
    a = ev("Techno Night", event_id="a", location="San Jose, CA")
    b = ev("Jazz Brunch", event_id="b", location="San Jose, CA")
    assert len(merge_duplicates([a, b], tz=TZ)) == 2


# --- schedule / caps --------------------------------------------------------

def test_weekday_daytime_events_are_dropped():
    cfg = load_config()
    wednesday_noon = datetime(2026, 9, 9, 12, tzinfo=TZ).astimezone(timezone.utc)
    e = ev("Lunch talk", start=wednesday_noon)
    e.categories = {"community"}
    assert not pipeline.fits_schedule(e, cfg, TZ)


def test_weekend_daytime_events_pass():
    cfg = load_config()
    saturday_noon = datetime(2026, 9, 12, 12, tzinfo=TZ).astimezone(timezone.utc)
    e = ev("Street fair", start=saturday_noon)
    e.categories = {"community"}
    assert pipeline.fits_schedule(e, cfg, TZ)


def test_caps_are_applied_per_category(log):
    cfg = load_config()
    cfg["categories"]["edm"]["cap"] = 2
    cfg["combined_cap"] = 0
    pool = []
    for i in range(6):
        e = ev(f"Techno night {i}", event_id=f"e{i}",
               location="San Jose, CA", genres=("techno",))
        geo.resolve(e)
        e.categories = C.classify(e)
        pool.append(e)
    kept = pipeline.apply_caps(pool, cfg, log)
    assert len(kept) == 2


def test_uncategorized_events_are_dropped(log):
    cfg = load_config()
    junk = ev("Networking Drinks", event_id="j", location="San Jose, CA")
    good = ev("Techno night", event_id="g", location="San Jose, CA",
              genres=("techno",))
    kept, drops = pipeline.filter_and_rank([junk, good], cfg, log)
    assert [e.title for e in kept] == ["Techno night"]
    assert drops["uncategorized"] == 1


# --- feed output ------------------------------------------------------------

def test_writes_valid_ics_with_categories(tmp_path, log):
    from icalendar import Calendar
    cfg = load_config()
    e = ev("Techno night", event_id="e1", location="San Jose, CA",
           venue="The Ritz", genres=("techno",), url="https://x.test/1")
    geo.resolve(e)
    e.categories = C.classify(e)
    out = tmp_path / "events.ics"
    counts = ics.write_all([e], out, cfg, log)

    cal = Calendar.from_ical(out.read_bytes())
    vevents = [c for c in cal.walk("VEVENT")]
    assert len(vevents) == 1
    item = vevents[0]
    assert str(item["SUMMARY"]).startswith("[EDM]")   # combined feed prefixes
    assert item["DTSTART"].dt and item["DTEND"].dt
    assert str(item["UID"]) == "e1"
    assert "The Ritz" in str(item["DESCRIPTION"])
    assert counts["edm"] == 1 and counts["music"] == 1
    assert counts["ai"] == 0

    edm_cal = Calendar.from_ical((tmp_path / "feeds/edm.ics").read_bytes())
    edm_item = [c for c in edm_cal.walk("VEVENT")][0]
    assert str(edm_item["SUMMARY"]) == "Techno night"  # no prefix per-category


def test_publish_guard_keeps_existing_feed(tmp_path, log, monkeypatch):
    """A collapsed fetch must fail the run, not wipe a good calendar."""
    out = tmp_path / "events.ics"
    out.write_bytes(b"BEGIN:VCALENDAR\nEND:VCALENDAR\n")
    monkeypatch.setattr(pipeline, "fetch_all",
                        lambda cfg, log, offline=False: [])
    rc = pipeline.run(ics_path=out)
    assert rc == 1
    assert out.read_bytes().startswith(b"BEGIN:VCALENDAR")
