"""Parser tests — every source, driven by committed fixtures (offline)."""

from conftest import TODAY, TZ

from kyros.sources import funcheap


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

