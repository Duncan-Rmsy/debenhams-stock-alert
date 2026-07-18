#!/usr/bin/env python3
"""Check Debenhams stock for the Norfolk Leisure Royce Executive cantilever parasol.

Fetches the raw server-rendered product HTML (no headless browser required) and
decides whether the item is IN STOCK or OUT OF STOCK.

Design goals:
  * Never send a false "in stock" alert. On any fetch problem (non-200, timeout,
    network error, or missing/unexpected product markup) we log and exit cleanly
    with status UNKNOWN so the workflow stays silent.
  * Emit machine-readable results to $GITHUB_OUTPUT so the workflow can decide
    whether to email.
  * Maintain a small state.json so we only alert once on the OUT -> IN
    transition rather than every run while the item stays in stock.

Exit code is always 0 for expected outcomes (in/out/unknown); a non-zero exit is
reserved for genuinely unexpected internal errors.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PRODUCT_URL = (
    "https://www.debenhams.com/product/"
    "norfolk-leisure-royce-executive-3m-cantilever-with-taupe-canopy-cover-base"
    "_p-55c70e19-7f48-4b73-a2e7-6622028fb3c2"
)

# A marker that must appear in the raw HTML for us to trust the page is the
# correct product page. If none of these are present the markup is unexpected
# (blocked, redirected, changed) and we refuse to make a stock decision.
PRODUCT_MARKERS = (
    "55c70e19-7f48-4b73-a2e7-6622028fb3c2",  # product id from the URL
    "M5060694431646",                        # SKU
    "Royce Executive",                       # product name
)

DEFAULT_PRICE = "£539.00"

# A realistic desktop Chrome User-Agent so we are not trivially blocked.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

STATE_PATH = Path(os.environ.get("STATE_PATH", "state.json"))

STATUS_IN = "IN_STOCK"
STATUS_OUT = "OUT_OF_STOCK"
STATUS_UNKNOWN = "UNKNOWN"


def log(msg: str) -> None:
    print(msg, flush=True)


def fetch_html(url: str, timeout: int = 30) -> str | None:
    """Return the page HTML, or None on any fetch failure."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-GB,en;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                log(f"Non-200 response: {resp.status}")
                return None
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        log(f"HTTP error fetching page: {exc.code} {exc.reason}")
        return None
    except (urllib.error.URLError, TimeoutError) as exc:
        log(f"Network error fetching page: {exc}")
        return None
    except Exception as exc:  # pragma: no cover - defensive
        log(f"Unexpected error fetching page: {exc}")
        return None


def markup_looks_valid(html: str) -> bool:
    return any(marker in html for marker in PRODUCT_MARKERS)


def determine_status(html: str) -> str:
    """Classify the page as IN_STOCK or OUT_OF_STOCK.

    Verified 18 Jul 2026: while out of stock the HTML contains the literal
    "Out of Stock" (including the size line "One Size - Out of Stock").
    We treat the item as out of stock whenever that text is still present, and
    as in stock only when it is gone and/or an add-to-basket control appears.
    """
    lowered = html.lower()

    out_of_stock_present = "out of stock" in lowered
    add_to_basket_present = (
        "add to basket" in lowered
        or "add to bag" in lowered
        or "addtobasket" in lowered
        or "add-to-basket" in lowered
    )

    if out_of_stock_present:
        return STATUS_OUT
    if add_to_basket_present:
        return STATUS_IN
    # Neither signal: "Out of Stock" gone but no explicit basket control seen.
    # Per the spec, the disappearance of the out-of-stock text is itself the
    # alert condition, so treat this as in stock.
    return STATUS_IN


def extract_price(html: str) -> str:
    """Best-effort price extraction; falls back to the known price."""
    # Look for a £ amount, preferring one near the product/price markup.
    matches = re.findall(r"£\s?(\d{1,4}(?:,\d{3})*(?:\.\d{2})?)", html)
    if matches:
        # Prefer the known 539 value if present, otherwise the first match.
        for m in matches:
            if m.replace(",", "").startswith("539"):
                return f"£{m}"
        return f"£{matches[0]}"
    return DEFAULT_PRICE


def load_previous_status() -> str:
    try:
        data = json.loads(STATE_PATH.read_text())
        return str(data.get("status", STATUS_UNKNOWN))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return STATUS_UNKNOWN


def save_state(status: str, price: str, alerted: bool) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        existing = json.loads(STATE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        existing = {}
    existing["status"] = status
    existing["price"] = price
    existing["last_checked"] = now
    if alerted:
        existing["last_alert"] = now
    STATE_PATH.write_text(json.dumps(existing, indent=2) + "\n")


def write_outputs(**kwargs: str) -> None:
    out_file = os.environ.get("GITHUB_OUTPUT")
    if not out_file:
        log("GITHUB_OUTPUT not set; outputs: " + json.dumps(kwargs))
        return
    with open(out_file, "a", encoding="utf-8") as fh:
        for key, value in kwargs.items():
            fh.write(f"{key}={value}\n")


def main() -> int:
    log(f"Checking stock for: {PRODUCT_URL}")
    previous = load_previous_status()
    log(f"Previous status: {previous}")

    html = fetch_html(PRODUCT_URL)

    if html is None:
        log("Fetch failed; staying silent (status=UNKNOWN).")
        # Do not overwrite the known previous status with UNKNOWN, and never alert.
        write_outputs(status=STATUS_UNKNOWN, should_alert="false",
                      price=DEFAULT_PRICE, url=PRODUCT_URL)
        return 0

    if not markup_looks_valid(html):
        log("Product markup not found in response; unexpected page. Staying silent.")
        write_outputs(status=STATUS_UNKNOWN, should_alert="false",
                      price=DEFAULT_PRICE, url=PRODUCT_URL)
        return 0

    status = determine_status(html)
    price = extract_price(html)
    log(f"Detected status: {status} (price: {price})")

    should_alert = status == STATUS_IN and previous != STATUS_IN
    if status == STATUS_IN and not should_alert:
        log("In stock but already alerted on a prior run; staying silent.")

    save_state(status, price, alerted=should_alert)
    write_outputs(
        status=status,
        should_alert="true" if should_alert else "false",
        price=price,
        url=PRODUCT_URL,
    )
    log(f"should_alert={should_alert}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
