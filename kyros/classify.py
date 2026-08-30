"""Category classification.

An event can hold several categories — a free warehouse techno party is
{"edm", "free"} — because the caps and the per-category feeds both work
off the set. Events that match nothing are dropped by the pipeline.
"""

from __future__ import annotations

import re

AI = "ai"
EDM = "edm"
CONCERT = "concert"
FREE = "free"
COMMUNITY = "community"

ALL_CATEGORIES = (AI, EDM, CONCERT, FREE, COMMUNITY)

# Discover's `category=ai` is a loose tag — many generic tech/networking
# events leak through. Require an explicit AI-vocabulary hit in either
# the event title or the host calendar name.
AI_PATTERN = re.compile(
    r"\bAI\b|\bAGI\b|\bA\.I\.\b|\bML\b|\bLLM[s]?\b|\bGPT[-\d]*\b"
    r"|\bRAG\b|\bMCP\b|\bRLHF\b|\bSLM\b|\bVLM\b"
    r"|\bClaude\b|\bChatGPT\b|\bGemini\b|\bLlama\b|\bMistral\b|\bGrok\b"
    r"|\bAnthropic\b|\bOpenAI\b|\bDeepMind\b|\bxAI\b|\bHugging\s?Face\b"
    r"|\bLangChain\b|\bLangGraph\b|\bLlamaIndex\b|\bPyTorch\b"
    r"|\bartificial intelligence\b|\bmachine learning\b|\bdeep learning\b"
    r"|\bgenerative\b|\bagentic\b|\bagent[s]?\b|\bcopilot[s]?\b"
    r"|\bneural\b|\btransformer[s]?\b|\bdiffusion model[s]?\b"
    r"|\bembedding[s]?\b|\bfine[- ]?tun(?:e|ing)\b"
    r"|\bprompt(?:ing|s)?\b|\bfoundation model[s]?\b|\bmultimodal\b"
    r"|\balignment\b|\binference\b|\breinforcement learning\b"
    r"|\bvector (?:db|database|store|search)\b|\bopen[- ]?weight\b"
    r"|\bAI[- ](?:safety|alignment|agent|infra|infrastructure|hackathon)\b",
    re.IGNORECASE,
)

# Electronic music, split by how much a match is worth.
#
# STRONG terms mean electronic and nothing else. WEAK ones — house, disco,
# bass, garage, dub, acid, hardcore — are also ordinary English and ordinary
# band genres: matching them bare put "Lionel Richie and Earth, Wind & Fire"
# (subgenre Disco), a post-hardcore bill, and a funk night called "House of
# Funk" into the EDM feed. Only STRONG decides the category; WEAK is kept
# for ranking, where a false positive is cheap.
EDM_STRONG = re.compile(
    r"\bedm\b|\belectronic\b|\bdance[/ ]electronic\b|\bdance music\b"
    r"|\btechno\b|\bhard ?techno\b|\bminimal techno\b"
    r"|\btrance\b|\bpsytrance\b|\bpsy[- ]?trance\b"
    r"|\bdubstep\b|\briddim\b|\bbass music\b|\bbassline\b"
    r"|\bdrum ?(?:and|n|&) ?bass\b|\bdnb\b|\bd&b\b|\bjungle\b"
    r"|\bbreakbeat\b|\bbreakcore\b|\buk ?garage\b|\bukg\b|\bspeed garage\b"
    r"|\btech[- ]house\b|\bdeep house\b|\bafro[- ]?house\b|\bacid house\b"
    r"|\bprogressive house\b|\bhouse music\b|\bmelodic house\b"
    r"|\bhardstyle\b|\bgabber\b|\bhard dance\b|\bhappy hardcore\b"
    r"|\bnu[- ]?disco\b|\bitalo\b|\bamapiano\b|\bafro ?beats?\b"
    r"|\bdowntempo\b|\belectro\b|\bsynthwave\b|\bidm\b|\bambient\b"
    r"|\brave\b|\bwarehouse\b|\bafter[- ]?hours\b|\bafters\b"
    r"|\bb2b\b|\bdj set\b|\bdjs?\b|\bsilent disco\b|\bboiler room\b"
    r"|\bsound ?system\b|\bselectors?\b|\bopen decks\b|\bclub night\b",
    re.IGNORECASE,
)
# Ambiguous on their own — never sufficient, only a ranking nudge.
EDM_WEAK = re.compile(
    r"\bhouse\b|\bdisco\b|\bbass\b|\bgarage\b|\bdub\b|\bacid\b"
    r"|\bhardcore\b|\bnightclub\b|\bday ?party\b|\bresidency\b",
    re.IGNORECASE,
)

# Live (non-electronic) music.
CONCERT_PATTERN = re.compile(
    r"\bconcert\b|\blive (?:music|band|show|set)\b|\bin concert\b"
    r"|\btour\b|\bworld tour\b|\bpresents\b|\blive at\b|\bon stage\b"
    r"|\bband\b|\bacoustic\b|\bunplugged\b|\borchestra\b|\bsymphony\b"
    r"|\bphilharmonic\b|\bchoir\b|\bquartet\b|\btrio\b|\bjazz\b|\bblues\b"
    r"|\bindie\b|\brock\b|\bpunk\b|\bmetal\b|\bhip[- ]?hop\b|\brap\b"
    r"|\br&b\b|\bsoul\b|\bfolk\b|\bcountry\b|\bpop\b|\bopera\b"
    r"|\bmusic festival\b|\bshowcase\b|\bopen mic\b|\bmatinee\b",
    re.IGNORECASE,
)

# The "interesting events" bucket: things worth an evening that aren't
# music or AI.
COMMUNITY_PATTERN = re.compile(
    r"\bfestival\b|\bfair\b|\bnight market\b|\bmarket\b|\bstreet food\b"
    r"|\bfood truck[s]?\b|\bpop[- ]?up\b|\bexhibit(?:ion)?\b|\bgallery\b"
    r"|\bmuseum\b|\bart walk\b|\bfirst friday\b|\bopen studio[s]?\b"
    r"|\bfilm\b|\bscreening\b|\bcinema\b|\bmovie night\b|\bdrive[- ]?in\b"
    r"|\bcomedy\b|\bstand[- ]?up\b|\bimprov\b|\btheat(?:er|re)\b|\bplay\b"
    r"|\bmusical\b|\bdance\b|\bballet\b|\bcircus\b|\bburlesque\b"
    r"|\btrivia\b|\bkaraoke\b|\bgame night\b|\bchess\b|\bbook club\b"
    r"|\blecture\b|\btalk\b|\bpanel\b|\bworkshop\b|\bclass\b|\bseminar\b"
    r"|\bhackathon\b|\bdemo day\b|\bmeetup\b|\bconference\b|\bsummit\b"
    r"|\bparade\b|\bfireworks\b|\bmarathon\b|\brun\b|\bhike\b|\bbike\b"
    r"|\bpark\b|\bgarden\b|\btour\b|\bwine\b|\bbeer\b|\btasting\b"
    r"|\bcraft\b|\bmaker\b|\bswap\b|\bflea\b|\bfarmers\b",
    re.IGNORECASE,
)

# Titles that are pure networking filler. Not a hard drop — just a
# ranking penalty — but a title that is *only* this doesn't earn the
# community bucket.
SOCIAL_KW = (
    "happy hour", "drinks", "dinner", "party", "mixer", "social",
    "afterparty", "after party", "brunch", "lunch", "networking",
)

FREE_TEXT_RE = re.compile(
    r"\bfree\b|\bno cover\b|\bfree entry\b|\bfree admission\b|\brsvp free\b"
    r"|\$0\b", re.IGNORECASE)
PAID_HINT_RE = re.compile(r"\$\s*[1-9]")


def _haystack(event) -> str:
    return " | ".join(filter(None, (
        event.title, event.calendar_name, event.venue,
        " ".join(event.genres),
    )))


def is_free(event) -> bool:
    """Free if a price says so, or the price text says so and no non-zero
    dollar figure contradicts it."""
    if event.is_free:
        return True
    if event.price_min is not None:
        return event.price_min <= 0 and not (event.price_max or 0) > 0
    if not event.price_text_trusted:
        # A ticketing API's blurb says "free parking" and "smoke-free
        # venue"; believing it listed paid concerts as free events.
        return False
    text = f"{event.title} {event.description[:400]}"
    if FREE_TEXT_RE.search(text) and not PAID_HINT_RE.search(text):
        return True
    return False


def classify(event) -> set[str]:
    """Return the set of categories this event belongs to."""
    cats: set[str] = set()
    hay = _haystack(event)
    genre_text = " ".join(event.genres).lower()

    if AI_PATTERN.search(f"{event.title} | {event.calendar_name}"):
        cats.add(AI)

    if EDM_STRONG.search(hay):
        cats.add(EDM)

    # Ticketmaster stamps its segment/genre names onto event.genres, so a
    # "Music" segment is authoritative for live shows. Electronic shows
    # already landed in EDM above and keep that (better) label.
    tm_music = "music" in genre_text
    if EDM not in cats and (tm_music or CONCERT_PATTERN.search(hay)):
        cats.add(CONCERT)

    if is_free(event):
        cats.add(FREE)

    if not (cats - {FREE}):
        # Nothing musical or AI matched — is it still interesting?
        if COMMUNITY_PATTERN.search(hay):
            low = event.title.lower()
            only_social = (any(k in low for k in SOCIAL_KW)
                           and not COMMUNITY_PATTERN.search(event.title))
            if not only_social:
                cats.add(COMMUNITY)

    return cats
