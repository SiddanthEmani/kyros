"""Bay Area geography: city registry, region resolution, San Jose priority.

The old scraper substring-matched two city names. Covering the whole Bay
Area needs a registry (city -> region + coordinates), a radius test around
downtown San Jose for sources that give coordinates, and a per-region
score boost so San Jose and the South Bay win the caps while SF and the
East Bay stay eligible.
"""

from __future__ import annotations

import math
import re

# Downtown San Jose — the center everything is measured from.
SJ_LAT, SJ_LON = 37.3382, -121.8863

SOUTH_BAY = "south-bay"
PENINSULA = "peninsula"
SF = "sf"
EAST_BAY = "east-bay"
NORTH_BAY = "north-bay"
BAY_AREA = "bay-area"  # known-Bay but city unresolved

# city -> (region, lat, lon)
BAY_CITIES: dict[str, tuple[str, float, float]] = {
    # South Bay
    "san jose": (SOUTH_BAY, 37.3382, -121.8863),
    "santa clara": (SOUTH_BAY, 37.3541, -121.9552),
    "sunnyvale": (SOUTH_BAY, 37.3688, -122.0363),
    "mountain view": (SOUTH_BAY, 37.3861, -122.0839),
    "cupertino": (SOUTH_BAY, 37.3230, -122.0322),
    "campbell": (SOUTH_BAY, 37.2872, -121.9500),
    "los gatos": (SOUTH_BAY, 37.2358, -121.9624),
    "saratoga": (SOUTH_BAY, 37.2638, -122.0230),
    "milpitas": (SOUTH_BAY, 37.4323, -121.8996),
    "morgan hill": (SOUTH_BAY, 37.1305, -121.6544),
    "gilroy": (SOUTH_BAY, 37.0058, -121.5683),
    "los altos": (SOUTH_BAY, 37.3852, -122.1141),
    "santa cruz": (SOUTH_BAY, 36.9741, -122.0308),
    # Peninsula
    "palo alto": (PENINSULA, 37.4419, -122.1430),
    "menlo park": (PENINSULA, 37.4530, -122.1817),
    "redwood city": (PENINSULA, 37.4852, -122.2364),
    "san mateo": (PENINSULA, 37.5630, -122.3255),
    "burlingame": (PENINSULA, 37.5779, -122.3480),
    "foster city": (PENINSULA, 37.5585, -122.2711),
    "belmont": (PENINSULA, 37.5202, -122.2758),
    "san carlos": (PENINSULA, 37.5072, -122.2605),
    "millbrae": (PENINSULA, 37.5985, -122.3872),
    "south san francisco": (PENINSULA, 37.6547, -122.4077),
    "daly city": (PENINSULA, 37.6879, -122.4702),
    "half moon bay": (PENINSULA, 37.4636, -122.4286),
    "stanford": (PENINSULA, 37.4275, -122.1697),
    # San Francisco
    "san francisco": (SF, 37.7749, -122.4194),
    # East Bay
    "oakland": (EAST_BAY, 37.8044, -122.2712),
    "berkeley": (EAST_BAY, 37.8715, -122.2730),
    "emeryville": (EAST_BAY, 37.8313, -122.2852),
    "alameda": (EAST_BAY, 37.7652, -122.2416),
    "fremont": (EAST_BAY, 37.5485, -121.9886),
    "newark": (EAST_BAY, 37.5297, -122.0402),
    "union city": (EAST_BAY, 37.5934, -122.0438),
    "hayward": (EAST_BAY, 37.6688, -122.0808),
    "san leandro": (EAST_BAY, 37.7249, -122.1561),
    "richmond": (EAST_BAY, 37.9358, -122.3477),
    "walnut creek": (EAST_BAY, 37.9101, -122.0652),
    "concord": (EAST_BAY, 37.9780, -122.0311),
    "pleasanton": (EAST_BAY, 37.6624, -121.8747),
    "dublin": (EAST_BAY, 37.7022, -121.9358),
    "livermore": (EAST_BAY, 37.6819, -121.7680),
    "danville": (EAST_BAY, 37.8216, -121.9999),
    # North Bay
    "sausalito": (NORTH_BAY, 37.8591, -122.4853),
    "mill valley": (NORTH_BAY, 37.9060, -122.5450),
    "san rafael": (NORTH_BAY, 37.9735, -122.5311),
    "novato": (NORTH_BAY, 38.1074, -122.5697),
    "petaluma": (NORTH_BAY, 38.2324, -122.6367),
    "santa rosa": (NORTH_BAY, 38.4404, -122.7141),
    "napa": (NORTH_BAY, 38.2975, -122.2869),
    "vallejo": (NORTH_BAY, 38.1041, -122.2566),
}

# Venue -> city, for sources that print a venue but no city.
VENUE_CITY: dict[str, str] = {
    # San Jose / South Bay
    "the ritz": "san jose",
    "the ritz san jose": "san jose",
    "sap center": "san jose",
    "san jose civic": "san jose",
    "city national civic": "san jose",
    "the continental": "san jose",
    "motif": "san jose",
    "splash": "san jose",
    "the caravan": "san jose",
    "cafe stritch": "san jose",
    "the san jose improv": "san jose",
    "san jose improv": "san jose",
    "art boutiki": "san jose",
    "the glass house": "san jose",
    "shoreline amphitheatre": "mountain view",
    "shoreline amphitheater": "mountain view",
    "computer history museum": "mountain view",
    "the caravan lounge": "san jose",
    "levi's stadium": "santa clara",
    "levis stadium": "santa clara",
    "california theatre": "san jose",
    "hammer theatre": "san jose",
    "montgomery theater": "san jose",
    "frost amphitheater": "stanford",
    "bing concert hall": "stanford",
    "the guild theatre": "menlo park",
    "club fox": "redwood city",
    "fox theatre redwood city": "redwood city",
    # San Francisco
    "1015 folsom": "san francisco",
    "public works": "san francisco",
    "great northern": "san francisco",
    "the great northern": "san francisco",
    "halcyon": "san francisco",
    "audio": "san francisco",
    "audio sf": "san francisco",
    "monarch": "san francisco",
    "f8": "san francisco",
    "the midway": "san francisco",
    "midway": "san francisco",
    "bimbo's": "san francisco",
    "bimbos 365 club": "san francisco",
    "the independent": "san francisco",
    "the fillmore": "san francisco",
    "fillmore": "san francisco",
    "the warfield": "san francisco",
    "warfield": "san francisco",
    "bill graham civic": "san francisco",
    "bill graham civic auditorium": "san francisco",
    "chase center": "san francisco",
    "the regency ballroom": "san francisco",
    "regency ballroom": "san francisco",
    "rickshaw stop": "san francisco",
    "cafe du nord": "san francisco",
    "the chapel": "san francisco",
    "dna lounge": "san francisco",
    "temple": "san francisco",
    "temple sf": "san francisco",
    "the endup": "san francisco",
    "endup": "san francisco",
    "grand nightclub": "san francisco",
    "love + propaganda": "san francisco",
    "the valencia room": "san francisco",
    "August hall": "san francisco",
    "august hall": "san francisco",
    "the masonic": "san francisco",
    "gray area": "san francisco",
    "sf oasis": "san francisco",
    # East Bay
    "the new parish": "oakland",
    "new parish": "oakland",
    "fox theater": "oakland",
    "fox theater oakland": "oakland",
    "the fox oakland": "oakland",
    "the uptown": "oakland",
    "uptown nightclub": "oakland",
    "starline social club": "oakland",
    "oakland arena": "oakland",
    "the greek theatre": "berkeley",
    "greek theatre": "berkeley",
    "the uc theatre": "berkeley",
    "uc theatre": "berkeley",
    "cornerstone": "berkeley",
    "924 gilman": "berkeley",
    "the crucible": "oakland",
    "the golden bull": "oakland",
    "the legionnaire": "oakland",
    "eli's mile high club": "oakland",
    "sound room": "oakland",
    "shattuck down low": "berkeley",
    "the port bar": "oakland",
    "bal theatre": "san leandro",
}

_STATE_SUFFIX_RE = re.compile(r",\s*(?:ca|california)\b", re.IGNORECASE)

# Places a Bay-Area-scoped source still mentions, which are not the Bay.
# Checked before any region hint is applied.
OUT_OF_AREA = (
    "sacramento", "reno", "tahoe", "truckee", "davis", "stockton",
    "modesto", "fresno", "chico", "monterey", "carmel", "salinas",
    "los angeles", "san diego", "las vegas", "portland", "seattle",
)


def haversine_miles(lat1: float, lon1: float,
                    lat2: float, lon2: float) -> float:
    """Great-circle distance in miles."""
    r = 3958.7613
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def geohash(lat: float, lon: float, precision: int = 6) -> str:
    """Encode a coordinate as a geohash. Ticketmaster's `geoPoint` takes
    one; there's no stdlib encoder, so this is the standard bit-interleave."""
    base32 = "0123456789bcdefghjkmnpqrstuvwxyz"
    lat_range, lon_range = [-90.0, 90.0], [-180.0, 180.0]
    out: list[str] = []
    bits = 0
    bit = 0
    even = True
    while len(out) < precision:
        if even:
            mid = sum(lon_range) / 2
            if lon > mid:
                bits = (bits << 1) | 1
                lon_range[0] = mid
            else:
                bits <<= 1
                lon_range[1] = mid
        else:
            mid = sum(lat_range) / 2
            if lat > mid:
                bits = (bits << 1) | 1
                lat_range[0] = mid
            else:
                bits <<= 1
                lat_range[1] = mid
        even = not even
        bit += 1
        if bit == 5:
            out.append(base32[bits])
            bits = 0
            bit = 0
    return "".join(out)


_ADDRESS_RE = re.compile(
    r"^\d|\b(?:st|street|ave|avenue|blvd|boulevard|rd|road|dr|drive|way|"
    r"ln|lane|ct|court|pl|place|hwy|highway|pkwy|parkway)\.?$")


def _longest_city_in(text: str) -> str:
    """Longest registry city name contained in `text`, so
    'south san francisco' beats 'san francisco'."""
    best = ""
    for name in BAY_CITIES:
        if name in text and len(name) > len(best):
            best = name
    return best


def _is_address(segment: str) -> bool:
    """'525 W Santa Clara St' must not resolve to Santa Clara."""
    words = segment.split()
    if not words:
        return True
    return bool(_ADDRESS_RE.match(words[0]) or _ADDRESS_RE.match(words[-1]))


def city_from_text(text: str) -> str:
    """Find a known Bay city in a free-text location/venue string.

    Addresses put the city last ('525 W Santa Clara St, San Jose, CA'), so
    segments are read right to left and street-looking segments are skipped
    entirely — otherwise a street name outranks the actual city.
    """
    if not text:
        return ""
    low = _STATE_SUFFIX_RE.sub("", text.lower())
    segments = [re.sub(r"\s+", " ", s).strip(" ()")
                for s in re.split(r"[,\n|]", low)]
    segments = [s for s in segments if s]

    for seg in reversed(segments):          # exact segment: the common case
        if seg in BAY_CITIES:
            return seg
    for seg in reversed(segments):          # inside a non-address segment
        if _is_address(seg):
            continue
        best = _longest_city_in(seg)
        if best:
            return best
    best = _longest_city_in(low)            # last resort: anywhere in the text
    if best:
        return best
    for venue, city in VENUE_CITY.items():
        if venue and venue.lower() in low:
            return city
    return ""


def nearest_city(lat: float, lon: float,
                 max_miles: float = 15.0) -> str:
    """Snap coordinates to the closest registry city within max_miles."""
    best, best_d = "", max_miles
    for name, (_region, clat, clon) in BAY_CITIES.items():
        d = haversine_miles(lat, lon, clat, clon)
        if d < best_d:
            best, best_d = name, d
    return best


def resolve(event) -> None:
    """Set event.city / event.region in place.

    Coordinates win when we have them; otherwise match city names, then
    venue names, in the location / venue / title text.
    """
    city = ""
    if event.lat is not None and event.lon is not None:
        city = nearest_city(event.lat, event.lon)
    if not city:
        for text in (event.location, event.venue, event.title):
            city = city_from_text(text)
            if city:
                break
    event.city = city
    if city:
        event.region = BAY_CITIES[city][0]
        return
    if event.lat is not None and event.lon is not None:
        # Coordinates we couldn't snap to a city: still Bay if close enough.
        d = haversine_miles(event.lat, event.lon, SJ_LAT, SJ_LON)
        event.region = BAY_AREA if d <= 75 else ""
        return
    # No city, no coordinates. A source that only covers one area can still
    # vouch for the event — unless the text names somewhere else entirely.
    haystack = f"{event.location} {event.venue} {event.title}".lower()
    if event.region_hint and not any(p in haystack for p in OUT_OF_AREA):
        event.region = event.region_hint
    else:
        event.region = ""


def distance_from_sj(event) -> float | None:
    if event.lat is not None and event.lon is not None:
        return haversine_miles(event.lat, event.lon, SJ_LAT, SJ_LON)
    if event.city and event.city in BAY_CITIES:
        _r, lat, lon = BAY_CITIES[event.city]
        return haversine_miles(lat, lon, SJ_LAT, SJ_LON)
    return None


def in_scope(event, config: dict) -> bool:
    """Geographic keep/drop. Virtual events follow the existing
    include_virtual_global switch; physical ones must be in the Bay."""
    if event.is_virtual:
        return bool(config.get("include_virtual_global", True))
    center = config.get("center") or {}
    radius = float(center.get("radius_miles", 50) or 0)
    d = distance_from_sj(event)
    if d is not None and radius > 0:
        return d <= radius
    return bool(event.region)


def region_boost(event, config: dict) -> float:
    """Score bonus for being close to San Jose. San Jose proper gets an
    extra point on top of its region so it leads the South Bay."""
    boosts = config.get("region_boost") or {}
    score = float(boosts.get(event.region, 0.0) or 0.0)
    if event.city == "san jose":
        score += 1.0
    return score
