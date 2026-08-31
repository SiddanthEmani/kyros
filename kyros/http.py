"""Shared HTTP helpers.

Luma silently degrades responses for non-browser clients, so every fetch
goes out with a real browser User-Agent. `http_get` never raises: it logs
and returns None so one dead source can't kill a run.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.parse
import urllib.request

HTTP_TIMEOUT = 30

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)

# Free CORS-relay services. Used only when a direct call comes back
# blocked-empty (Luma silently empty-responds to many datacenter IPs,
# notably GitHub Actions runners).
PROXIES = (
    "https://api.allorigins.win/raw?url={}",
    "https://api.codetabs.com/v1/proxy/?quest={}",
)


def http_get(url: str, log: logging.Logger,
             headers: dict[str, str] | None = None) -> bytes | None:
    """GET a URL with browser-ish headers. Returns None on any failure."""
    hdrs = {
        "User-Agent": _BROWSER_UA,
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        log.warning("HTTP %s on %s", e.code, redact(url))
    except urllib.error.URLError as e:
        log.warning("URL error on %s: %s", redact(url), e.reason)
    except Exception as e:  # noqa: BLE001
        log.warning("Fetch error on %s: %s", redact(url), e)
    return None


def redact(url: str) -> str:
    """Strip query strings before logging (they can carry API keys)."""
    try:
        p = urllib.parse.urlsplit(url)
        return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, "", ""))
    except Exception:  # noqa: BLE001
        return "<url>"


def proxy_wrap(url: str, proxy_idx: int) -> str:
    """Wrap a target URL in a CORS-relay service URL."""
    enc = urllib.parse.quote(url, safe="")
    return PROXIES[proxy_idx % len(PROXIES)].format(enc)
