# kyros

> **An iCalendar feed of the best events in the SF Bay Area — EDM, concerts,
> free things to do, and AI talks — refreshed every 6 hours.** San Jose
> first, the rest of the Bay right behind it. One URL — subscribe from any
> calendar app.

[![refresh](https://github.com/SiddanthEmani/kyros/actions/workflows/refresh.yml/badge.svg)](https://github.com/SiddanthEmani/kyros/actions/workflows/refresh.yml)
[![calendar feed](https://img.shields.io/badge/feed-events.ics-blue?logo=apple)](https://raw.githubusercontent.com/SiddanthEmani/kyros/main/events.ics)
[![python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![license](https://img.shields.io/github/license/SiddanthEmani/kyros)](LICENSE)

## Subscribe

**[Add to Google Calendar](https://calendar.google.com/calendar/render?cid=webcal%3A%2F%2Fraw.githubusercontent.com%2FSiddanthEmani%2Fkyros%2Fmain%2Fevents.ics)**
&nbsp;— one tap on Android or desktop. Google Calendar (app or web) opens
straight to the "Subscribe" prompt, already filled in.

Or add a raw feed URL manually. Everything lives under
`https://raw.githubusercontent.com/SiddanthEmani/kyros/main/`:

| feed | what's in it |
|---|---|
| `events.ics` | **everything**, tagged `[EDM]` / `[Live]` / `[AI]` / `[Free]` / `[Bay]` |
| `feeds/edm.ics` | electronic — club nights, warehouse parties, festivals |
| `feeds/music.ics` | all live music: concerts + EDM |
| `feeds/free.ics` | free events only |
| `feeds/ai.ics` | AI talks, demos, hackathons (the original kyros feed) |

- **Apple Calendar** &nbsp;`File → New Calendar Subscription` → paste URL
- **Google Calendar / Android** &nbsp;use the one-tap link above, or on
  desktop: `Other calendars → + → From URL` → paste URL
- **Outlook / Fantastical / anything else** &nbsp;Add subscription by URL

`kyros` (κῦρος): authority, weight, signal over noise.

---

## How it works

```
Luma ┐
 TM  ├─►  classify  ─►  geo filter  ─►  dedup  ─►  rank  ─►  cap  ─►  5 feeds
19hz │     5 buckets     50mi of SJ    merge      SJ first   per cat    every 6h
Fun. ┘
```

1. **Fetch** — four sources, each isolated so a dead site can't take down a
   refresh:
   - **Luma** — AI talks, demos and hackathons. Scrapes the server-rendered
     discover HTML and paginates the JSON discover API, falling back through
     CORS relays when the runner IP is blocked.
   - **Ticketmaster** — concerts and ticketed shows within 50 miles of
     downtown San Jose (SAP Center, Shoreline, The Ritz, Fox Oakland, Chase
     Center). Needs a free API key; skips itself without one.
   - **19hz** — the Bay Area's electronic music listing. Its table is
     hand-maintained, so columns are located by header text rather than
     position.
   - **Funcheap** — free and cheap events, region by region, South Bay first.
2. **Classify** — each event lands in one or more of `ai`, `edm`, `concert`,
   `free`, `community`. Anything that matches nothing is dropped, which is
   what keeps "Networking Drinks" out of the feed.
3. **Geo** — resolved to a Bay city and region by coordinates when a source
   gives them, else by city and venue names. Outside 50 miles of San Jose
   is dropped.
4. **Dedup** — the same show arrives from Ticketmaster *and* 19hz *and*
   Funcheap. Matches merge, so one event keeps Ticketmaster's price and
   19hz's genre tags.
5. **Rank & cap** — per-category scoring plus a **San Jose / South Bay
   boost**, so SJ wins the caps while a strong SF show still makes it. Caps
   are per category, then a combined cap over the union.
6. **Write** — the combined `events.ics` plus the four category feeds.

If a refresh collapses (blocked IP, changed markup), the run **fails loudly
and keeps the existing feeds** rather than publishing an empty calendar.

## The Ticketmaster key (optional)

Concert coverage is much better with one. Grab a free key at
[developer.ticketmaster.com](https://developer.ticketmaster.com/) (5,000
calls/day; a refresh uses ~10) and add it as a repository secret named
`TICKETMASTER_API_KEY`. Without it, that source logs `no key, skipping` and
everything else still builds.

## Running it locally

```bash
pip install -r requirements-dev.txt

python run.py                      # build the feeds
python run.py --explain            # ...and log the ranked keep-list per category
python run.py --dry-run --explain  # fetch and rank, write nothing
python run.py --offline --explain  # run the whole pipeline off committed fixtures
python -m pytest -q                # offline parser + pipeline tests
```

`--ics-path` puts the combined feed anywhere; the category feeds follow it
into the same directory, so a scratch run stays out of the repo:

```bash
python run.py --offline --ics-path /tmp/kyros/events.ics
```

## Configuration (`config.json`)

| key | default | meaning |
|---|---|---|
| `lookahead_days` | `30` | drop events past this horizon |
| `local_tz` | `"America/Los_Angeles"` | IANA tz for every schedule check |
| `center` | SJ, `radius_miles: 50` | what counts as "around the area" |
| `region_boost` | south-bay `3.0`, peninsula `1.5`, sf/east-bay `0.5` | the San Jose priority dial; San Jose proper gets `+1.0` on top |
| `free_bonus` | `1.0` | score bonus for free events |
| `sources` | all `true` | turn an individual source off |
| `cities` / `luma_categories` | SJ, SF, Oakland, Palo Alto / `["ai"]` | Luma discover scope |
| `ticketmaster_classifications` | `["music"]` | Discovery classifications to query |
| `categories.<name>.cap` | 8–15 | top-N per category |
| `categories.<name>.min_weekday_hour_local` | `16`–`17` | weekday events must start at/after this hour; weekends always pass |
| `combined_cap` | `60` | cap on the combined feed |
| `prefix_titles` | `true` | `[EDM]`-style tags in the combined feed |
| `min_events_floor` | `5` | below this, keep the old feeds and fail the run |

Old flat configs still work: `min_weekday_hour_local` and
`max_events_per_run` are read and mapped onto the new shape.

## Files

```
run.py                         # CLI entry point
kyros/
  config.py  http.py  model.py # config, fetching, the Event record
  geo.py                       # Bay city registry, radius, SJ boost
  classify.py  rank.py         # categories and per-category scoring
  dedup.py  ics.py             # cross-source merge, feed writing
  pipeline.py                  # fetch -> filter -> rank -> write
  sources/                     # luma, ticketmaster, nineteenhz, funcheap
tests/                         # offline, fixture-driven
scripts/fetch_fixtures.py      # refresh fixtures when a site changes
config.json                    # user-editable
.github/workflows/refresh.yml  # 6-hourly schedule
events.ics  feeds/*.ics        # output (committed by CI)
```

## Why this exists

It started as one calendar I could open on Sunday night and see every
meaningful AI talk in the Bay for the coming weeks. The same filtering turns
out to be exactly what the rest of a week needs — which warehouse party is
worth the drive, which show at The Ritz is on sale, what's free downtown this
weekend — without scrolling five sites that each cover a third of it.

## License

MIT — fork it, run it for your city, ship your own feed.
