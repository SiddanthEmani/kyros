"""Per-category scoring.

score = base(best category) + region boost + free/weekend bonuses
        - social penalty

The AI base is the original `event_score()` from the single-file version,
kept verbatim so the AI slice of the feed ranks exactly as it did before.
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import classify as C
from .geo import region_boost

# --- AI signal vocab (unchanged from the original run.py) ------------------
REPUTABLE_KW = (
    "langchain", "langgraph", "openai", "anthropic", "deepmind", "google",
    "snorkel", "hugging face", "huggingface", "modal", "databricks",
    "ai tinkerers", "ai engineer", "ai engineers", "south park commons",
    "y combinator", " yc ", "saastr", "veris ai", "gmi cloud", "mlops",
    "weaviate", "pinecone", "scale ai", "ai collective", "ai council",
    "ai salon", "resolve ai", "builders collective", "rosebud ai",
    "cursor", "vercel", "github", "nvidia", "perplexity", "microsoft",
    "frontier tower", "foresight institute", "novita ai",
)
TECH_KW = (
    "rag", "fine-tun", "fine tun", "agentic", "agent", "transformer",
    "diffusion", "embedding", "inference", "rlhf", "mcp", "llm",
    "evaluation", "benchmark", "alignment", "interpret", "hackathon",
    "workshop", "deep dive", "reading group", "research", "paper",
    "reinforcement", "multimodal", "robotics", "model", "prompt",
    "open source", "open-weight", "framework", "architecture", "training",
)
SOCIAL_KW = C.SOCIAL_KW

# --- Music signal ----------------------------------------------------------
# Promoters and rooms that consistently book quality electronic lineups.
EDM_REPUTABLE = (
    "public works", "1015 folsom", "great northern", "halcyon", "audio",
    "the midway", "monarch", "f8", "dna lounge", "temple", "the endup",
    "as you like it", "housepitality", "direct to earth", "symbiotic",
    "no way back", "robot ears", "dirtybird", "desert hearts",
    "anthem", "the ritz", "motif", "splash", "the continental",
    "sunset campout", "honey soundsystem", "honey sound system",
    "polyglamorous", "boiler room", "modular", "grimey", "recess",
    "surface tension", "unter", "wormhole", "bloom", "kontrol",
)
# Rooms whose booking bar is high enough that the venue alone is signal.
VENUE_TIERS = {
    3.0: ("sap center", "chase center", "shoreline amphitheatre",
          "shoreline amphitheater", "frost amphitheater", "the masonic",
          "bill graham civic", "oakland arena", "greek theatre"),
    2.0: ("the fillmore", "the warfield", "fox theater", "the fox oakland",
          "the regency ballroom", "the uc theatre", "san jose civic",
          "city national civic", "california theatre", "the independent",
          "august hall", "bimbo's", "the midway", "public works"),
    1.0: ("rickshaw stop", "the chapel", "cafe du nord", "the new parish",
          "the uptown", "starline social club", "the continental",
          "the ritz", "art boutiki", "the caravan", "1015 folsom",
          "great northern", "halcyon", "monarch", "dna lounge"),
}

# Words that make an "interesting" event actually interesting.
INTEREST_KW = (
    "festival", "night market", "street fair", "first friday", "art walk",
    "open studios", "screening", "film", "comedy", "improv", "exhibit",
    "gallery", "museum", "parade", "fireworks", "silent disco",
    "maker", "craft", "tasting", "pop-up", "popup", "outdoor movie",
    "free concert", "block party", "lantern", "lunar new year", "pride",
)


def _venue_tier(event) -> float:
    hay = f"{event.venue} {event.location}".lower()
    for pts, names in VENUE_TIERS.items():
        if any(n in hay for n in names):
            return pts
    return 0.0


def ai_base(event) -> float:
    """The original AI scorer: host reputation + technical vocabulary."""
    title = event.title.lower()
    cal = event.calendar_name.lower()
    score = 0.0
    if any(k in cal for k in REPUTABLE_KW):
        score += 4.0
    if any(k in title for k in REPUTABLE_KW):
        score += 2.0
    score += sum(1.2 for k in TECH_KW if k in title)
    score -= sum(0.4 for k in SOCIAL_KW if k in title)
    return score


def edm_base(event) -> float:
    hay = f"{event.title} {event.venue} {event.calendar_name}".lower()
    score = 2.0
    if any(k in hay for k in EDM_REPUTABLE):
        score += 3.0
    score += _venue_tier(event)
    # A row tagged with real genres beats an untagged "club night".
    score += min(len(event.genres), 3) * 0.8
    if C.EDM_WEAK.search(hay):
        score += 0.3
    score -= sum(0.4 for k in SOCIAL_KW if k in event.title.lower())
    return score


def concert_base(event) -> float:
    score = 2.0 + _venue_tier(event)
    score += min(len(event.genres), 3) * 0.5
    return score


def community_base(event) -> float:
    low = f"{event.title} {event.venue}".lower()
    score = 1.0
    score += sum(1.0 for k in INTEREST_KW if k in low)
    score -= sum(0.6 for k in SOCIAL_KW if k in event.title.lower())
    return score


BASE_SCORERS = {
    C.AI: ai_base,
    C.EDM: edm_base,
    C.CONCERT: concert_base,
    C.FREE: community_base,
    C.COMMUNITY: community_base,
}


def category_score(event, category: str, config: dict) -> float:
    """Score within one category — used when applying that category's cap."""
    base = BASE_SCORERS.get(category, community_base)(event)
    score = base + region_boost(event, config)
    if event.is_free or C.FREE in event.categories:
        score += float(config.get("free_bonus", 1.0))
    if event.start.weekday() >= 4:  # Fri/Sat/Sun read as easier to attend
        score += 0.5
    return score


def best_score(event, config: dict) -> float:
    """Score across every category the event holds — used for the
    combined feed's cap."""
    cats = event.categories or {C.COMMUNITY}
    return max(category_score(event, c, config) for c in cats)


def soonness(event) -> float:
    """Tie-breaker: sooner is better, so a stale far-future listing never
    outranks something this week at equal score."""
    delta = (event.start - datetime.now(timezone.utc)).total_seconds()
    return -delta / 86400.0
