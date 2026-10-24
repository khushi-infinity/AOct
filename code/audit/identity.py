"""Current and historical identity resolution.

The request supplies a single email address, which may be a historical value.
Deletion completeness therefore has to be evaluated against *every* identifier
a person has ever used.  This module builds that identity graph from the
current snapshot plus the identity audit trail.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
HASH_RE = re.compile(r"\b[a-fA-F0-9]{32,64}\b")
USER_RE = re.compile(r"\buser[_-]?\d+\b", re.IGNORECASE)
PHONE_RE = re.compile(r"\+?\d[\d\s().\-]{6,}\d")

# Characters that survive Unicode normalisation but differ between the
# identity snapshot and OCR/typed evidence.
_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff\u00ad"), None)


def normalize(value: object) -> str:
    """Case-folded, whitespace-collapsed representation used for matching."""

    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).translate(_INVISIBLE)
    return " ".join(text.strip().casefold().split())


def digits(value: object) -> str:
    """Phone numbers are compared on their digits only."""

    return re.sub(r"\D", "", str(value or ""))


def name_key(value: object) -> str:
    return re.sub(r"[^a-z0-9 ]", "", normalize(value))


@dataclass
class Identity:
    user_id: str
    names: set[str] = field(default_factory=set)
    emails: set[str] = field(default_factory=set)
    phones: set[str] = field(default_factory=set)
    hashes: set[str] = field(default_factory=set)

    def keys(self) -> set[str]:
        keys: set[str] = {normalize(self.user_id)}
        keys.update(normalize(item) for item in self.emails)
        keys.update(digits(item) for item in self.phones if digits(item))
        keys.update(normalize(item) for item in self.hashes)
        keys.update(name_key(item) for item in self.names if name_key(item))
        return {key for key in keys if key}


class IdentityGraph:
    """Maps any identifier (current or historical) to a stable ``user_id``."""

    def __init__(self, dataset: Path):
        self.dataset = dataset
        self.identities: dict[str, Identity] = {}
        self.index: dict[str, str] = {}
        self._ambiguous: set[str] = set()
        self._load_snapshot()
        self._load_history()
        self._build_index()

    # ------------------------------------------------------------------ load
    def _load_snapshot(self) -> None:
        with (self.dataset / "user_identities.csv").open(
            newline="", encoding="utf-8-sig"
        ) as handle:
            for row in csv.DictReader(handle):
                identity = Identity(user_id=row["user_id"].strip())
                if row.get("name"):
                    identity.names.add(row["name"])
                if row.get("email"):
                    identity.emails.add(row["email"])
                if row.get("phone"):
                    identity.phones.add(row["phone"])
                if row.get("email_hash"):
                    identity.hashes.add(row["email_hash"])
                self.identities[identity.user_id] = identity

    def _load_history(self) -> None:
        path = self.dataset / "user_audit_log.csv"
        if not path.exists():
            return
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                identity = self.identities.get(row.get("user_id", "").strip())
                if identity is None:
                    continue
                for column in ("old_value", "new_value"):
                    value = row.get(column) or ""
                    if not value:
                        continue
                    field_name = (row.get("field_name") or "").casefold()
                    if "mail" in field_name and "@" in value:
                        identity.emails.add(value)
                    elif "phone" in field_name:
                        identity.phones.add(value)
                    elif "hash" in field_name:
                        identity.hashes.add(value)
                    elif "name" in field_name:
                        identity.names.add(value)
                    elif "@" in value:
                        identity.emails.add(value)

    def _build_index(self) -> None:
        for user_id, identity in sorted(self.identities.items()):
            for key in identity.keys():
                existing = self.index.get(key)
                if existing and existing != user_id:
                    # A shared key is not a safe link; record it but keep the
                    # first owner so lookups stay deterministic.
                    self._ambiguous.add(key)
                    if key.startswith("user_"):
                        continue
                self.index.setdefault(key, user_id)

    # --------------------------------------------------------------- resolve
    def resolve(self, value: object) -> str | None:
        """Resolve a single literal identifier to a ``user_id``."""

        if value is None:
            return None
        raw = normalize(value)
        if not raw:
            return None
        return self.index.get(raw)

    def resolve_any(self, value: object) -> set[str]:
        """Resolve a value that may be an identifier or a free-text fragment."""

        found: set[str] = set()
        if isinstance(value, (list, tuple, set)):
            for item in value:
                found |= self.resolve_any(item)
            return found
        if isinstance(value, dict):
            for item in value.values():
                found |= self.resolve_any(item)
            return found
        text = str(value or "")
        direct = self.resolve(text)
        if direct:
            found.add(direct)
        normalized = normalize(text)
        for email in EMAIL_RE.findall(text):
            owner = self.index.get(normalize(email))
            if owner:
                found.add(owner)
        for hashed in HASH_RE.findall(text):
            owner = self.index.get(normalize(hashed))
            if owner:
                found.add(owner)
        for token in USER_RE.findall(text):
            owner = self.index.get(normalize(token))
            if owner:
                found.add(owner)
            else:
                cleaned = re.sub(r"[^0-9]", "", token)
                if cleaned and f"user_{cleaned}" in self.identities:
                    found.add(f"user_{cleaned}")
        # Phone numbers only when the fragment looks like a phone, so that we
        # never link two customers because of a shared order number.
        stripped = normalized.replace(" ", "")
        if stripped.startswith("+") or (sum(ch.isdigit() for ch in stripped) >= 9):
            phone = digits(stripped)
            if phone:
                owner = self.index.get(phone)
                if owner:
                    found.add(owner)
        for name in self._names_in(text):
            owner = self.index.get(name)
            if owner:
                found.add(owner)
        return found

    def _names_in(self, text: str) -> set[str]:
        """Full-name matches on multi-word strings (rarely ambiguous)."""

        candidate = name_key(text)
        if not candidate or " " not in candidate:
            return set()
        return {candidate} if candidate in self.index else set()

    def user(self, user_id: str) -> Identity | None:
        return self.identities.get(user_id)

    def identifiers(self, user_id: str) -> set[str]:
        identity = self.identities.get(user_id)
        return identity.keys() if identity else set()

    def all_users(self) -> list[str]:
        return sorted(self.identities)
