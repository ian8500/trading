from __future__ import annotations

import hashlib
import re
import unicodedata

MAX_HEADLINE_LENGTH = 500
MAX_SUMMARY_LENGTH = 4000
CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitise_untrusted_text(value: str, *, max_length: int) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = CONTROL_CHARACTERS.sub(" ", value)
    return " ".join(value.split())[:max_length]


def content_fingerprint(source: str, headline: str) -> str:
    canonical = re.sub(r"[^a-z0-9]+", " ", headline.lower()).strip()
    return hashlib.sha256(f"{source.lower()}:{canonical}".encode()).hexdigest()


def bounded_news_payload(headline: str, summary: str | None) -> dict[str, str | None]:
    """Delimit news as inert data; it is never promoted to model or tool instructions."""
    return {
        "headline_untrusted_data": sanitise_untrusted_text(
            headline, max_length=MAX_HEADLINE_LENGTH
        ),
        "summary_untrusted_data": (
            sanitise_untrusted_text(summary, max_length=MAX_SUMMARY_LENGTH) if summary else None
        ),
    }
