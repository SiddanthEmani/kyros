# Source candidates

Research notes for replacing Ticketmaster and widening coverage (Sept 2026).
Each entry says what it covers, how it would be fetched, and what it costs
to maintain. "Effort" is relative to the existing Luma and Funcheap parsers.

Current sources: **Luma** (AI), **Cerebral Valley** (AI), **Visit San Jose**,
**DoTheBay**, **Stanford Events**, **Funcheap** (free/cheap).

**San Jose Downtown (sjdowntown.com) was tried and doesn't work:** every
endpoint (iCal export, WP REST, RSS) returns a Cloudflare JS challenge to
GitHub Actions runners, and the CORS relays time out (522) on it. Most of
its big events also appear on Visit San Jose, which does work.

## Tier 1: build next

| source | covers | access | effort | notes |
|---|---|---|---|---|
| [19hz.info — Bay Area](https://19hz.info/eventlisting_BayArea.php) | EDM | static HTML table | low | The most complete Bay Area electronic listing. Covers everything from club nights to warehouse parties, with a city column (SF / Oakland / San Jose), price, age and a ticket link. One page, no key, rarely changes. |
| [Edmtrain API](https://edmtrain.com/api-documentation) | EDM, festivals | JSON API, free client key | low | `locationIds` for SF/Bay Area, returns venue lat/lon and artist lineups. The terms require attribution ("Powered by Edmtrain"), so put a link in the event description. |
| [SeatGeek Platform API](https://seatgeek.github.io/) | concerts, big-venue shows | JSON API, free `client_id` | low | The closest replacement for Ticketmaster's arena and theater coverage. `/events?lat=&lon=&range=50mi&taxonomies.name=concert`, includes price stats. About 1000 requests per hour on the free tier. |
| [foopee "The List"](http://www.foopee.com/punk/the-list/) | concerts (club/indie/punk/rock) | static HTML, updated weekly | low–med | Covers the small rooms that the ticketing APIs miss. Plain text by date, format is `band, band at Venue, City, age, price, time`. Needs a venue→city map, and `geo.py` already has most of what that needs. |
| [San Jose Downtown (sjdowntown.com)](https://sjdowntown.com/whats-going-on/) | free, community (SJ) | iCal export (The Events Calendar plugin, `?ical=1`) | very low | San Jose events, the top priority region. Reading an existing `.ics` needs no parser work. |
| [Stanford Events](https://events.stanford.edu/) | AI talks, free, community (Peninsula) | Localist JSON API `/api/2/events` | low | Public, no key. Filter by type or keyword for AI/CS/HAI talks. Most events are free, and it returns geo data. Other Localist campuses (SJSU, Santa Clara U) expose the same API. |

## Tier 2: worth it, but more work or more churn

| source | covers | access | effort | notes |
|---|---|---|---|---|
| [Resident Advisor](https://ra.co/) | EDM | unofficial GraphQL (`ra.co/graphql`, area id for SF) | med | Best lineup data. The endpoint is undocumented, so it can break or rate-limit. Open-source reference: [djb-gt/resident-advisor-events-scraper](https://github.com/djb-gt/resident-advisor-events-scraper). |
| [DoTheBay](https://dothebay.com/) | concerts, EDM, free, community | HTML by date (`/events/YYYY/MM/DD`) | med | Still active in 2026. It's an editorial mix across all categories, so there's heavy overlap for dedup to handle. |
| [Cerebral Valley events](https://cerebralvalley.ai/events) | AI, hackathons | HTML / JSON from the page | med | Curated SF AI events. Many of them are also on Luma, and dedup would merge those. |
| [Devpost hackathons](https://devpost.com/hackathons) | AI hackathons | JSON at `devpost.com/api/hackathons` (undocumented) | low–med | Filter to in-person events and a Bay Area `displayed_location`. Low volume but high signal (DeveloperWeek SJ, API World Santa Clara). |
| [GarysGuide SF](https://www.garysguide.com/events?region=sf) | AI / tech talks | HTML | med | Long-running SF tech calendar. Noisier than Luma, so it needs the AI classifier to do the filtering. |
| [San José Public Library](https://sjpl.bibliocommons.com/v2/events) | free, community (SJ) | BiblioCommons events (RSS/JSON behind the v2 UI) | med | Free SJ events, including tech/maker ones. It skews toward family events, so it needs a keyword or type filter. |
| [SF Rec & Park calendar](https://sfrecpark.org/Calendar.aspx) | free (SF) | CivicPlus calendar (iCal per calendar id) | low | Free concerts in the park and Golden Gate Park events. |
| [Visit San Jose](https://www.sanjose.org/events) | concerts, free, community (SJ) | HTML (or a Simpleview API, if exposed) | med | Tourism board calendar with good SJ festival coverage. |

## Tier 3: skip unless something changes

| source | why not |
|---|---|
| Eventbrite | Public search API was removed in Feb 2020 ([docs](https://www.eventbrite.com/platform/docs/by-location)). Only per-venue and per-organizer listings are left. Scraping `/d/ca--san-jose/events/` works but breaks often. |
| Meetup | The [GraphQL API](https://www.meetup.com/graphql/) needs a Pro subscription (about $55/month) for anything useful. |
| DICE | No public API, and aggressive Cloudflare protection that blocks Actions runners. |
| Songkick / Bandsintown | Both are artist-centric. Songkick stopped issuing new keys, and Bandsintown's API is only for artists showing their own dates. |
| Partiful, Posh, Shotgun | No public discovery endpoints. Events are mostly invite or link only. |
| AI Tinkerers SF | Its events are already posted on Luma, so a separate parser adds nothing. |

## Suggested order

1. **19hz**: fixes EDM coverage on its own, and needs no key.
2. **SeatGeek**: restores the arena and theater concerts that Ticketmaster used to cover.
3. **sjdowntown.com iCal** and **Stanford Localist**: cheap, and they boost San Jose and the Peninsula.
4. **foopee**: covers small-venue shows.
5. **Edmtrain** or **RA**: adds lineup detail to EDM, if 19hz isn't enough.
