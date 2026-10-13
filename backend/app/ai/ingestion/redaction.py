"""Finds personal data and secrets in text and replaces them with [REDACTED_...] markers before
anything is embedded or stored, then rates the chunk's sensitivity from what was found.

Secrets are found two ways: long random-looking tokens (keys, JWTs, private key lines), and any value
given to a key named like a password, secret, token or API key ("password = hunter2"), however short.
The text cache stores redacted text, so a rule change here needs EXTRACTOR_VERSION (extractors.py) bumped,
or text cached under the old rules would still be served.
"""

import math
import re

ENTROPY_THRESHOLD = 4.0

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")
AWS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
HIGH_ENTROPY_TOKEN_RE = re.compile(r"\b[A-Za-z0-9+/_=\-]{20,}\b")
# A key whose name ends in a secret's name, then = or : (not ==), then the value, quoted or not. The key is
# kept. `max_tokens = 512` and `tokens = text.split()` are left alone; `DB_PASSWORD=Summer2026!` is not.
SECRET_ASSIGNMENT_RE = re.compile(
    r"""(?i)(\b[\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)["']?\s*[:=](?!=)\s*)"""
    r"""("[^"\n]+"|'[^'\n]+'|[^\s"',;]+)"""
)


def shannon_entropy(value):
    if not value:
        return 0.0
    counts = {char: value.count(char) for char in set(value)}
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def redact_pii(text):
    hits = {
        "ssn": 0,
        "aws_key": 0,
        "credit_card": 0,
        "email": 0,
        "phone": 0,
        "high_entropy": 0,
        "secret": 0,
    }

    def redact_assigned(match):
        hits["secret"] += 1
        return match.group(1) + "[REDACTED_SECRET]"

    def substitute(pattern, label, value):
        def replace(_match):
            hits[label] += 1
            return f"[REDACTED_{label.upper()}]"

        return pattern.sub(replace, value)

    # First, so the key name stays readable even when the value would also pass as a random token.
    redacted = SECRET_ASSIGNMENT_RE.sub(redact_assigned, text)
    for pattern, label in (
        (SSN_RE, "ssn"),
        (AWS_KEY_RE, "aws_key"),
        (CREDIT_CARD_RE, "credit_card"),
        (EMAIL_RE, "email"),
        (PHONE_RE, "phone"),
    ):
        redacted = substitute(pattern, label, redacted)

    def redact_secret(match):
        if shannon_entropy(match.group(0)) >= ENTROPY_THRESHOLD:
            hits["high_entropy"] += 1
            return "[REDACTED_SECRET]"
        return match.group(0)

    return HIGH_ENTROPY_TOKEN_RE.sub(redact_secret, redacted), hits


def classify_sensitivity(hits):
    if hits.get("ssn") or hits.get("credit_card") or hits.get("aws_key") or hits.get("secret"):
        return "high"
    if hits.get("email") or hits.get("phone") or hits.get("high_entropy"):
        return "medium"
    return "low"
