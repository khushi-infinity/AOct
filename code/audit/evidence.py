"""Normalised evidence index.

Every participant-facing artefact is parsed into the same observation shape:

    (system, resource, category, state, observed_at, evidence_id, subjects)

so the planner never needs to know whether a fact came from a JSON export, a
SQL snapshot, a log trace, a PDF or a screenshot.  Reported workflow statuses
and operation results are kept as *claims* in ``system_activity.csv``; they are
useful for attribution, but they never decide a case on their own.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from .identity import IdentityGraph, digits, normalize

# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------

CATEGORY_BY_COLLECTION: dict[str, str] = {
    "customer_profiles": "USER_PROFILE",
    "customer_search_documents": "SEARCH_INDEX_ENTRY",
    "customer_analytics_reports": "ANALYTICS_PROFILE",
    "customer_analytics_profiles": "ANALYTICS_PROFILE",
    "product_telemetry": "PRODUCT_TELEMETRY",
    "support_conversations": "SUPPORT_MESSAGE",
    "support_records": "SUPPORT_MESSAGE",
    "ticket_attachments": "SUPPORT_ATTACHMENT",
    "support_attachments": "SUPPORT_ATTACHMENT",
    "customer_export_jobs": "USER_EXPORT",
    "customer_exports": "USER_EXPORT",
    "connector_configurations": "DATA_FLOW",
    "connector_subscriptions": "DATA_FLOW",
    "backup_catalog": "BACKUP_ARCHIVE",
    "backup_restore_entries": "BACKUP_ARCHIVE",
    "security_audit_events": "SECURITY_AUDIT_LOG",
    "security_audit_records": "SECURITY_AUDIT_LOG",
    "retained_order_records": "LEGAL_HOLD_RECORD",
    "deleted_customer_references": "ACCOUNT_TOMBSTONE",
    "marketing_profiles": "MARKETING_PROFILE",
    "email_delivery_log": "EMAIL_DELIVERY_LOG",
    "cache_entries": "CACHE_ENTRY",
    "secondary_identifiers": "SECONDARY_IDENTIFIER",
}

SYSTEM_BY_CATEGORY: dict[str, str] = {
    "USER_PROFILE": "account_service",
    "SECONDARY_IDENTIFIER": "identity_service",
    "SEARCH_INDEX_ENTRY": "search_service",
    "CACHE_ENTRY": "cache_service",
    "SUPPORT_MESSAGE": "support_platform",
    "SUPPORT_ATTACHMENT": "support_platform",
    "ANALYTICS_PROFILE": "analytics_platform",
    "PRODUCT_TELEMETRY": "analytics_platform",
    "USER_EXPORT": "export_service",
    "MARKETING_PROFILE": "marketing_platform",
    "EMAIL_DELIVERY_LOG": "email_delivery_service",
    "SECURITY_AUDIT_LOG": "security_service",
    "LEGAL_HOLD_RECORD": "legal_service",
    "BACKUP_ARCHIVE": "backup_service",
    "ACCOUNT_TOMBSTONE": "identity_service",
    "DATA_FLOW": "integration_service",
}

# Physical location names that appear in artefacts (replicas, stores, caches)
# mapped to the logical service the plan must reference.  A record belongs to the
# service that wrote it, even when it was observed through a replica.
SYSTEM_ALIASES: dict[str, str] = {
    "support_replica": "support_platform",
    "support_store": "support_platform",
    "user_export_store": "export_service",
    "export_store": "export_service",
    "account_store": "account_service",
    "search_store": "search_service",
    "identity_store": "identity_service",
    "marketing_store": "marketing_platform",
    "security_store": "security_service",
    "analytics_store": "analytics_platform",
    "object_store": "support_platform",
    "backup_store": "backup_service",
    "cache_store": "cache_service",
    "integration_store": "integration_service",
    "support_replica_store": "support_platform",
}

_KNOWN_SYSTEMS = set(SYSTEM_BY_CATEGORY.values()) | {
    "attachment_preview",
    "email_delivery_service",
    "identity_service",
    "legal_service",
}

# Resource-id prefixes are a stable, published convention in the corpus and are
# used as a fallback when an artefact does not name the data category.
PREFIX_CATEGORY: tuple[tuple[str, str], ...] = (
    ("account_", "USER_PROFILE"),
    ("search_", "SEARCH_INDEX_ENTRY"),
    ("analytics_", "ANALYTICS_PROFILE"),
    ("support_", "SUPPORT_MESSAGE"),
    ("ticket_", "SUPPORT_ATTACHMENT"),
    ("export_", "USER_EXPORT"),
    ("data_flow_", "DATA_FLOW"),
    ("connector_", "DATA_FLOW"),
    ("backup_", "BACKUP_ARCHIVE"),
    ("audit_record_", "SECURITY_AUDIT_LOG"),
    ("tombstone_", "ACCOUNT_TOMBSTONE"),
    ("marketing_", "MARKETING_PROFILE"),
    ("email_delivery_", "EMAIL_DELIVERY_LOG"),
    ("cache_", "CACHE_ENTRY"),
    ("object_", "SUPPORT_ATTACHMENT"),
)

RESULT_STATE: dict[str, str] = {
    "FOUND": "PRESENT",
    "PRESENT": "PRESENT",
    "EXISTS": "PRESENT",
    "NOT_FOUND": "ABSENT",
    "ABSENT": "ABSENT",
    "MISSING": "ABSENT",
    "DELETED": "ABSENT",
    "IDENTIFIABLE": "IDENTIFIABLE",
    "ANONYMIZED": "ANONYMIZED",
    "DEIDENTIFIED": "ANONYMIZED",
    "REDACTED": "REDACTED",
    "ACTIVE": "ACTIVE",
    "ENABLED": "ACTIVE",
    "BLOCKED": "BLOCKED",
    "DISABLED": "DISABLED",
    "STOPPED": "DISABLED",
}

# Origin (manifest) to default category for artefacts that contain no explicit
# record-type column, e.g. screenshots and PDFs.
ORIGIN_CATEGORY: dict[str, str] = {
    "account_admin_portal": "USER_PROFILE",
    "search_index_admin": "SEARCH_INDEX_ENTRY",
    "search_index_service": "SEARCH_INDEX_ENTRY",
    "integration_admin": "DATA_FLOW",
    "integration_management_service": "DATA_FLOW",
    "analytics_platform": "ANALYTICS_PROFILE",
    "export_service": "USER_EXPORT",
    "customer_export_service": "USER_EXPORT",
    "backup_service": "BACKUP_ARCHIVE",
    "support_platform": "SUPPORT_MESSAGE",
    "security_service": "SECURITY_AUDIT_LOG",
    "security_audit_service": "SECURITY_AUDIT_LOG",
    "identity_service": "ACCOUNT_TOMBSTONE",
    "marketing_platform": "MARKETING_PROFILE",
    "account_history_service": "USER_EXPORT",
    "object_storage": "SUPPORT_ATTACHMENT",
    "legal_retention_service": "LEGAL_HOLD_RECORD",
    "downstream_delivery_service": "EMAIL_DELIVERY_LOG",
}

_IDENTIFIER_FIELDS = (
    "user_id",
    "customer_reference",
    "subject_reference",
    "subject_selector",
    "email",
    "phone",
    "email_hash",
    "owner_email",
    "owner_phone",
    "requester_email",
    "requester_name",
    "requester_phone",
    "customer_email",
    "full_name",
    "display_name",
    "lookup_key",
    "correlation_key",
    "subject_key",
)
_DIRECT_IDENTIFIER_FIELDS = (
    "user_id",
    "customer_reference",
    "email",
    "phone",
    "email_hash",
    "owner_email",
    "owner_phone",
    "requester_email",
    "requester_name",
    "requester_phone",
    "customer_email",
    "full_name",
    "display_name",
)
_NULLS = {"", "null", "none", "n/a", "[redacted]", "redacted", "not available"}

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_RESOURCE_RE = re.compile(
    r"\b(?:account|search|analytics|support|ticket|export|data_flow|connector|backup|"
    r"audit_record|tombstone|marketing|email_delivery|cache|object)_[0-9]+\b",
    re.IGNORECASE,
)


def parse_time(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        match = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})", text)
        if match:
            return datetime.fromisoformat(f"{match.group(1)}T{match.group(2)}+00:00")
        return datetime.min.replace(tzinfo=timezone.utc)


def _clean(value: object) -> str:
    return str(value if value is not None else "").strip()


def _is_null(value: object) -> bool:
    return normalize(_clean(value)) in _NULLS


def _first(payload: dict[str, Any], *names: str) -> object:
    for name in names:
        if name in payload and not _is_null(payload.get(name)):
            return payload.get(name)
    return None


def flatten(record: dict[str, Any]) -> dict[str, Any]:
    """Merge nested payloads (search document, profile, contact) upward."""

    merged: dict[str, Any] = dict(record)
    for key in ("document", "profile", "contact", "attributes", "payload"):
        nested = record.get(key)
        if isinstance(nested, dict):
            for inner_key, inner_value in nested.items():
                merged.setdefault(inner_key, inner_value)
    return merged


def canonical_system(name: str, category: str) -> str:
    """Resolve a reported service/replica/store name to the owning service."""

    cleaned = (name or "").strip().casefold()
    if cleaned in SYSTEM_ALIASES:
        return SYSTEM_ALIASES[cleaned]
    for suffix in ("_read_replica", "_failover_replica", "_replica", "_primary"):
        if cleaned.endswith(suffix) and cleaned[: -len(suffix)] in _KNOWN_SYSTEMS:
            return cleaned[: -len(suffix)]
    if cleaned in _KNOWN_SYSTEMS:
        return cleaned
    return SYSTEM_BY_CATEGORY.get(category, "") or cleaned or "unknown"


def category_for_resource(resource_id: str) -> str | None:
    lowered = (resource_id or "").casefold()
    for prefix, category in PREFIX_CATEGORY:
        if lowered.startswith(prefix):
            return category
    return None


def _sql_table_category(table: str) -> str | None:
    """Resolve a SQL table name, including replica-suffixed variants."""

    lowered = (table or "").casefold()
    if lowered in CATEGORY_BY_COLLECTION:
        return CATEGORY_BY_COLLECTION[lowered]
    if "customer_profiles" in lowered:
        return "USER_PROFILE"
    if "search_documents" in lowered or "search_index" in lowered:
        return "SEARCH_INDEX_ENTRY"
    for collection, category in CATEGORY_BY_COLLECTION.items():
        if collection in lowered:
            return category
    return None


def _service_export_category(system: str, group: str) -> str | None:
    """Map a service-export system/group pair to a data category."""

    if system == "account_service" or group == "profile_lookups":
        return "USER_PROFILE"
    if system == "search_service":
        return "SEARCH_INDEX_ENTRY"
    if system == "analytics_platform":
        return "ANALYTICS_PROFILE"
    if system == "support_platform":
        return "SUPPORT_MESSAGE" if "ticket" in group else "SUPPORT_ATTACHMENT"
    if system == "integration_service":
        return "DATA_FLOW"
    if system == "backup_service":
        return "BACKUP_ARCHIVE"
    if system == "security_service":
        return "SECURITY_AUDIT_LOG"
    if system == "export_service":
        return "USER_EXPORT"
    if system == "identity_service":
        return "ACCOUNT_TOMBSTONE"
    if system == "marketing_platform":
        return "MARKETING_PROFILE"
    return None


def _service_export_state(system: str, category: str, payload: dict[str, Any]) -> str:
    """Derive the observed state from one service-export record."""

    if category == "USER_PROFILE":
        return "ABSENT" if payload.get("profile") is None else "PRESENT"
    if category == "SEARCH_INDEX_ENTRY":
        hits = payload.get("hits") or {}
        total = hits.get("total") if isinstance(hits, dict) else 0
        try:
            hit_count = int(total or 0)
        except (TypeError, ValueError):
            hit_count = 0
        found = (
            payload.get("found") is True
            or _clean(payload.get("result")).casefold() in {"hit", "found"}
            or hit_count > 0
        )
        return "PRESENT" if found else "ABSENT"
    if category in {"ANALYTICS_PROFILE", "PRODUCT_TELEMETRY"}:
        return (
            "IDENTIFIABLE"
            if any(
                not _is_null(payload.get(name))
                for name in ("customer_reference", "email", "phone", "email_hash", "user_id")
            )
            else "ANONYMIZED"
        )
    if category == "SUPPORT_MESSAGE":
        return _support_state(payload)
    if category == "SUPPORT_ATTACHMENT":
        return "PRESENT"
    if category == "DATA_FLOW":
        return (
            "ACTIVE"
            if payload.get("enabled") in {True, 1, "1", "true", "TRUE"}
            else "DISABLED"
        )
    if category == "BACKUP_ARCHIVE":
        return (
            "ACTIVE"
            if payload.get("restore_allowed") in {True, 1, "1", "true", "TRUE"}
            else "BLOCKED"
        )
    if category == "ACCOUNT_TOMBSTONE":
        return _tombstone_state(payload)
    if category == "EMAIL_DELIVERY_LOG":
        return "IDENTIFIABLE" if _EMAIL_RE.search(json.dumps(payload)) else "REDACTED"
    return "PRESENT"


def _walk_strings(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_strings(item)
    elif value is not None and not isinstance(value, bool):
        if isinstance(value, (int, float)):
            return
        yield str(value)


@dataclass(frozen=True)
class Observation:
    system_id: str
    resource_id: str
    category: str
    state: str
    observed_at: datetime
    evidence_id: str
    available_at: datetime
    subjects: frozenset[str] = frozenset()
    source: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.system_id, self.resource_id)

    @property
    def positive(self) -> bool:
        return self.state in {"PRESENT", "IDENTIFIABLE", "ACTIVE"}


@dataclass
class Activity:
    """A workflow claim from ``system_activity.csv`` (never proof on its own)."""

    activity_id: str
    event_time: datetime
    event_type: str
    source_system: str
    target_system: str
    resource_id: str
    reported_result: str
    details: str
    subjects: frozenset[str] = frozenset()


# A dedicated capture of the owning service is stronger proof than an
# aggregate inventory export, so absence is proven from the former when the
# corpus contains one before the cutoff.
AUTHORITATIVE_ORIGINS: dict[str, set[str]] = {
    "USER_PROFILE": {"customer_account_failover_replica_capture", "account_admin_portal"},
    "SEARCH_INDEX_ENTRY": {"customer_search_primary_capture", "search_index_admin"},
    "ANALYTICS_PROFILE": {"analytics_platform"},
    "SUPPORT_MESSAGE": {"support_platform"},
    "USER_EXPORT": {"export_service", "customer_export_service"},
    "BACKUP_ARCHIVE": {"backup_service"},
    "SECURITY_AUDIT_LOG": {"security_service", "security_audit_service"},
    "DATA_FLOW": {"integration_management_service", "integration_admin"},
}


class EvidenceIndex:
    def __init__(self, dataset: Path, identities: IdentityGraph):
        self.dataset = dataset
        self.identities = identities
        self.observations: list[Observation] = []
        self.activities: list[Activity] = []
        self.warnings: list[str] = []
        self.manifest: list[dict[str, str]] = []
        self.available_at: dict[str, datetime] = {}
        self.origin_by_file: dict[str, str] = {}
        # Which data categories each artefact structurally covers.  A snapshot
        # with an empty profile table still proves the account is not there.
        self.capabilities: dict[str, set[str]] = defaultdict(set)
        self.resource_subjects: dict[str, set[str]] = defaultdict(set)
        # Categories asserted by an artefact that names the record type, used
        # to correct weaker prefix-only guesses for the same resource.
        self.resource_categories: dict[str, set[str]] = defaultdict(set)
        self._load_manifest()
        self._load_activity()
        self._parse_files()
        self._propagate()

    # ------------------------------------------------------------------ load
    def _load_manifest(self) -> None:
        with (self.dataset / "evidence_files.csv").open(
            newline="", encoding="utf-8-sig"
        ) as handle:
            self.manifest = list(csv.DictReader(handle))
        for item in self.manifest:
            self.available_at[item["file_id"]] = parse_time(item["captured_at"])
            self.origin_by_file[item["file_id"]] = item.get("origin", "")

    def _load_activity(self) -> None:
        path = self.dataset / "system_activity.csv"
        if not path.exists():
            return
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                details = row.get("details") or ""
                subjects = self.identities.resolve_any(details)
                activity = Activity(
                    activity_id=row["activity_id"],
                    event_time=parse_time(row["event_time"]),
                    event_type=row["event_type"],
                    source_system=row.get("source_system", ""),
                    target_system=row.get("target_system", ""),
                    resource_id=row.get("resource_id", ""),
                    reported_result=row.get("reported_result", ""),
                    details=details,
                    subjects=frozenset(subjects),
                )
                self.activities.append(activity)
                if subjects:
                    self.resource_subjects[activity.resource_id].update(subjects)

    def _parse_files(self) -> None:
        for item in self.manifest:
            path = self.dataset / item["file_path"]
            if not path.exists():
                self._warn(f"missing evidence file {path}")
                continue
            suffix = path.suffix.lower()
            try:
                if suffix == ".json":
                    self._parse_json(path, item)
                elif suffix == ".sql":
                    self._parse_sql(path, item)
                elif suffix in {".log", ".txt"}:
                    self._parse_text(path, item)
                elif suffix in {".png", ".jpg", ".jpeg", ".pdf"}:
                    self._parse_media(path, item)
            except Exception as exc:  # keep going: one bad artefact must not sink the run
                self._warn(f"failed to parse {path.name}: {exc}")

    def _mark(self, evidence_id: str, category: str | None) -> None:
        """Record that an artefact structurally covers a data category.

        An empty table is still evidence of absence, so capability is tracked
        separately from the observations a file happens to emit.
        """

        if category:
            self.capabilities[evidence_id].add(category)

    def _warn(self, message: str) -> None:
        self.warnings.append(message)
        print(f"WARNING: {message}", file=sys.stderr)

    # -------------------------------------------------------------- observers
    def _add(
        self,
        *,
        system: str,
        resource: str,
        category: str,
        state: str,
        observed_at: object,
        evidence_id: str,
        keys: Iterable[object] = (),
        source: str = "",
        weak: bool = False,
    ) -> None:
        resource = _clean(resource)
        category = (category or "").upper()
        state = (state or "").upper()
        if not resource or not category or not state:
            return
        subjects: set[str] = set()
        for key in keys:
            if key is None:
                continue
            subjects |= self.identities.resolve_any(key)
        available = self.available_at.get(evidence_id, parse_time(observed_at))
        observation = Observation(
            # The plan references the logical owning service; replica/store
            # names are physical locations of the same record.
            system_id=canonical_system(system, category),
            resource_id=resource,
            category=category,
            state=STATE_ALIASES.get(state, state),
            observed_at=parse_time(observed_at),
            evidence_id=evidence_id,
            available_at=available,
            subjects=frozenset(subjects),
            source=source,
        )
        self.observations.append(observation)
        self.capabilities[evidence_id].add(observation.category)
        if not weak:
            self.resource_categories[resource].add(category)
        if subjects:
            self.resource_subjects[resource].update(subjects)

    # --------------------------------------------------------------- parsers
    def _parse_json(self, path: Path, item: dict[str, str]) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        default_ts = data.get("captured_at") or data.get("exported_at") or item["captured_at"]

        if isinstance(data.get("service_exports"), dict):
            self._parse_service_export(data, item, path)

        for snapshot in data.get("snapshots") or []:
            captured = snapshot.get("captured_at") or default_ts
            store = snapshot.get("data_store") or ""
            collection = snapshot.get("collection") or ""
            self._mark(item["file_id"], CATEGORY_BY_COLLECTION.get(collection))
            for record in snapshot.get("records") or []:
                self._collection_record(collection, record, captured, item, store)

        for record in data.get("records") or []:
            if not isinstance(record, dict):
                continue
            if data.get("collection"):
                self._mark(item["file_id"], CATEGORY_BY_COLLECTION.get(data["collection"]))
                self._collection_record(
                    data["collection"], record, default_ts, item, data.get("source", "")
                )
            else:
                self._direct_record(record, default_ts, item)

    def _parse_service_export(
        self, data: dict[str, Any], item: dict[str, str], path: Path
    ) -> None:
        default_ts = data.get("exported_at") or item["captured_at"]
        for system, groups in data["service_exports"].items():
            if not isinstance(groups, dict):
                continue
            for group, records in groups.items():
                group_category = _service_export_category(system, group)
                self._mark(item["file_id"], group_category)
                for record in records or []:
                    if not isinstance(record, dict):
                        continue
                    observed = record.get("observed_at") or default_ts
                    resource = record.get("resource_id", "")
                    payload = flatten(record)
                    category = group_category or category_for_resource(resource)
                    if not category:
                        continue
                    state = _service_export_state(system, category, payload)
                    self._add(
                        system=system,
                        resource=resource,
                        category=category,
                        state=state,
                        observed_at=observed,
                        evidence_id=item["file_id"],
                        keys=_walk_strings(record),
                        source=str(path),
                    )

    def _direct_record(
        self, record: dict[str, Any], default_ts: object, item: dict[str, str]
    ) -> None:
        resource = record.get("resource_id", "")
        category = (record.get("record_type") or "").upper()
        system = record.get("system") or SYSTEM_BY_CATEGORY.get(category, "")
        weak = False
        if not category:
            category = category_for_resource(resource) or ""
            weak = True
        if not category:
            return
        result = str(record.get("result", "")).upper()
        state = RESULT_STATE.get(result)
        if state is None:
            state = _state_from_result(result) or "PRESENT"
        observed = (
            record.get("recorded_at")
            or record.get("observed_at")
            or default_ts
        )
        self._add(
            system=system,
            resource=resource,
            category=category,
            state=state,
            observed_at=observed,
            evidence_id=item["file_id"],
            keys=_walk_strings(record),
            source=item["file_path"],
            weak=weak,
        )

    def _collection_record(
        self,
        collection: str,
        record: dict[str, Any],
        observed: object,
        item: dict[str, str],
        store: str = "",
    ) -> None:
        if not isinstance(record, dict):
            return
        collection = (collection or "").strip()
        payload = flatten(record)
        category = CATEGORY_BY_COLLECTION.get(collection)
        if category is None:
            category = category_for_resource(str(record.get("resource_id", ""))) or ""
        if not category:
            return
        system = store or SYSTEM_BY_CATEGORY.get(category, "")

        if category in {"USER_PROFILE", "SEARCH_INDEX_ENTRY", "SUPPORT_ATTACHMENT",
                        "USER_EXPORT", "MARKETING_PROFILE", "SECONDARY_IDENTIFIER",
                        "CACHE_ENTRY"}:
            state = "PRESENT"
        elif category in {"ANALYTICS_PROFILE", "PRODUCT_TELEMETRY"}:
            state = (
                "IDENTIFIABLE"
                if any(
                    not _is_null(payload.get(f))
                    for f in ("user_id", "customer_reference", "email", "phone", "email_hash")
                )
                else "ANONYMIZED"
            )
        elif category == "SUPPORT_MESSAGE":
            state = _support_state(payload)
        elif category == "DATA_FLOW":
            state = (
                "ACTIVE"
                if payload.get("enabled") in {True, 1, "1", "true", "TRUE"}
                else "DISABLED"
            )
        elif category == "BACKUP_ARCHIVE":
            state = (
                "ACTIVE"
                if payload.get("restore_allowed") in {True, 1, "1", "true", "TRUE"}
                else "BLOCKED"
            )
        elif category in {"SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD"}:
            state = "PRESENT"
        elif category == "ACCOUNT_TOMBSTONE":
            state = _tombstone_state(payload)
        elif category == "EMAIL_DELIVERY_LOG":
            state = "IDENTIFIABLE" if _EMAIL_RE.search(json.dumps(record)) else "REDACTED"
        else:
            return
        self._add(
            system=system,
            resource=record.get("resource_id", ""),
            category=category,
            state=state,
            observed_at=observed,
            evidence_id=item["file_id"],
            keys=_walk_strings(record),
            source=item["file_path"],
        )

    def _parse_sql(self, path: Path, item: dict[str, str]) -> None:
        connection = sqlite3.connect(":memory:")
        try:
            connection.executescript(path.read_text(encoding="utf-8", errors="replace"))
            tables = [
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            ]
            for table in tables:
                if table == "snapshot_scope":
                    continue
                category = _sql_table_category(table)
                self._mark(item["file_id"], category)
                cursor = connection.execute(f'SELECT * FROM "{table}"')
                columns = [description[0] for description in cursor.description]
                for values in cursor.fetchall():
                    record = dict(zip(columns, values))
                    if "record_json" in record:
                        try:
                            payload = json.loads(record["record_json"])
                        except (TypeError, json.JSONDecodeError):
                            continue
                        collection = record.get("collection_name") or table
                        store = record.get("origin_system") or ""
                        observed = record.get("updated_at") or item["captured_at"]
                        self._mark(item["file_id"], CATEGORY_BY_COLLECTION.get(collection))
                        self._collection_record(collection, payload, observed, item, store)
                        continue
                    if category is None:
                        continue
                    observed = record.get("updated_at") or item["captured_at"]
                    store = SYSTEM_BY_CATEGORY.get(category, "")
                    self._collection_record(table, record, observed, item, store)
        finally:
            connection.close()

    # ------------------------------------------------------------- text logs
    _KV_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)=("((?:\\.|[^"])*)"|\'([^\']*)\'|([^\s|,]+))')
    _TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)")
    _BRACKET_RE = re.compile(r"\[([^\]]+)\]")
    _LEVELS = {"DEBUG", "INFO", "WARN", "WARNING", "ERROR", "TRACE", "FATAL"}

    def _parse_text(self, path: Path, item: dict[str, str]) -> None:
        text = path.read_text(encoding="utf-8", errors="replace")
        if "SHIFT HANDOVER" in text.upper() or " | " in text and "- " in text:
            if self._parse_handover(text, item):
                return
        events: list[dict[str, Any]] = []
        for line in text.splitlines():
            parsed = self._parse_line(line)
            if parsed:
                events.append(parsed)
        self._emit_events(events, item, path)

    def _parse_handover(self, text: str, item: dict[str, str]) -> bool:
        pattern = re.compile(
            r"^-\s*([0-9T:\-Z]+)\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*(.+)$"
        )
        found = False
        for line in text.splitlines():
            match = pattern.match(line.strip())
            if not match:
                continue
            observed, system, resource, category, result, subject = (
                part.strip() for part in match.groups()
            )
            self._direct_record(
                {
                    "recorded_at": observed,
                    "system": system,
                    "resource_id": resource,
                    "record_type": category,
                    "result": result,
                    "subject_reference": subject,
                },
                observed,
                item,
            )
            found = True
        return found

    def _parse_line(self, line: str) -> dict[str, Any] | None:
        line = line.rstrip()
        if not line.strip():
            return None
        ts_match = self._TS_RE.match(line)
        if not ts_match:
            return None
        payload: dict[str, Any] = {"_timestamp": ts_match.group(1), "_line": line}

        json_start = line.find("{")
        if json_start != -1:
            try:
                decoded = json.loads(line[json_start:])
                if isinstance(decoded, dict):
                    payload.update({k: v for k, v in decoded.items() if not str(k).startswith("_")})
            except json.JSONDecodeError:
                pass

        for match in self._KV_RE.finditer(line):
            name = match.group(1)
            value = next((group for group in match.groups()[1:] if group is not None), "")
            payload.setdefault(name, value.replace('\\"', '"'))

        brackets = self._BRACKET_RE.findall(line)
        for token in brackets:
            token = token.strip()
            if token in self._LEVELS:
                continue
            if re.fullmatch(r"tr-[A-Za-z0-9\-]+", token):
                payload.setdefault("trace_id", token)
            elif re.fullmatch(r"[a-z0-9_]+", token) and token not in {"-"}:
                payload.setdefault("_bracket_service", token)

        if " | " in line:
            parts = [part.strip() for part in line.split(" | ")]
            if len(parts) >= 5:
                payload.setdefault("_bracket_service", parts[2])
                payload.setdefault("trace_id", parts[3] if parts[3].startswith("tr-") else "")
                payload.setdefault("event", parts[4])

        if "event" not in payload:
            match = re.search(r"\]\s*([a-z][a-z0-9_]+):", line)
            if match:
                payload["event"] = match.group(1)

        if "service" not in payload:
            for key in ("logger", "function", "_bracket_service"):
                if payload.get(key):
                    payload["service"] = payload[key]
                    break

        if not payload.get("trace_id"):
            for token in brackets + line.split():
                cleaned = token.strip("[](),")
                if re.fullmatch(r"tr-[A-Za-z0-9\-]+", cleaned):
                    payload["trace_id"] = cleaned
                    break

        if not payload.get("event"):
            return None
        return payload

    def _emit_events(
        self, events: list[dict[str, Any]], item: dict[str, str], path: Path
    ) -> None:
        trace_keys: dict[str, set[str]] = defaultdict(set)
        for event in events:
            trace = str(event.get("trace_id") or "")
            if not trace:
                continue
            for field_name in ("lookup_key", "match_key", "scan_key", "query",
                               "correlation_key", "subject_key", "subject_reference",
                               "subject_ref", "owner_key", "customer_email",
                               "requester_email", "matched_value"):
                value = event.get(field_name)
                if value and not _is_null(value):
                    trace_keys[trace].add(str(value))
            # Any identifier in the trace belongs to the one request it logs,
            # so a subject seen on a ``*_started`` line also links its
            # ``*_completed`` line.
            for value in event.values():
                if isinstance(value, str) and not value.startswith("_"):
                    if self.identities.resolve_any(value):
                        trace_keys[trace].add(value)

        for event in events:
            trace = str(event.get("trace_id") or "")
            keys: set[str] = set(trace_keys.get(trace, set()))
            for value in event.values():
                if isinstance(value, str) and not value.startswith("_"):
                    keys.add(value)
            self._event_observation(event, keys, item, path)

    def _event_observation(
        self,
        event: dict[str, Any],
        keys: Iterable[str],
        item: dict[str, str],
        path: Path,
    ) -> None:
        name = str(event.get("event") or "").casefold()
        resource = _clean(event.get("resource_id"))
        service = _clean(event.get("service"))
        observed = event.get("_timestamp") or item["captured_at"]

        if name == "record_lookup":
            category = str(event.get("record_type") or "").upper()
            self._direct_record(
                {
                    "recorded_at": observed,
                    "system": event.get("system", ""),
                    "resource_id": resource,
                    "record_type": category,
                    "result": event.get("result", ""),
                    "subject_reference": event.get("subject_reference", ""),
                },
                observed,
                item,
            )
            return

        if not resource:
            return
        if name.endswith("_started") or name in {
            "connection_acquired", "cache_lookup", "dependency_retry",
            "dependency_recovered", "batch_started", "export_started",
            # Diagnostics about a record are not observations of its type; a
            # marker/checkpoint line must not override the row's real category.
            "deletion_marker_check", "checkpoint_saved", "thumbnail_failed",
            "consumer_lag", "integrity_check", "cache_prime",
        }:
            return

        category: str | None = None
        state: str | None = None

        rows = _clean(event.get("rows"))
        status = _clean(event.get("http_status") or event.get("status_code"))
        result = _clean(event.get("result")).casefold()
        total_hits = _clean(event.get("total_hits") or event.get("hits"))
        absent = (
            rows in {"0"}
            or status in {"404"}
            or result in {"not_found", "missing", "miss", "none", "no_hit"}
            or total_hits in {"0"}
        )

        if "profile_lookup" in name:
            category = "USER_PROFILE"
            state = "ABSENT" if absent else "PRESENT" if (rows or status) else "PRESENT"
        elif "index_query" in name:
            category = "SEARCH_INDEX_ENTRY"
            present = result in {"hit", "found"} or (
                total_hits.isdigit() and int(total_hits) > 0
            ) or event.get("found") in {True, "true", "TRUE"}
            state = "PRESENT" if present and not absent else "ABSENT"
        elif "analytics_profile" in name:
            category = "ANALYTICS_PROFILE"
            direct = [event.get(f) for f in ("customer_reference", "email", "phone", "email_hash", "user_id")]
            identifiers = _clean(event.get("direct_identifiers"))
            if identifiers in {"0", "0.0"}:
                state = "ANONYMIZED"
            else:
                state = (
                    "IDENTIFIABLE"
                    if any(not _is_null(value) for value in direct)
                    else "ANONYMIZED"
                )
        elif "contact_lookup" in name:
            # A hash-only marketing contact row: attributable, so policy deletes it.
            category = "MARKETING_PROFILE"
            state = "PRESENT"
        elif "contact_query" in name:
            # Legacy contact indices hold the support attachment/contact row
            # itself (no shared conversation context), so policy deletes it.
            category = "SUPPORT_ATTACHMENT"
            state = "ABSENT" if absent else "PRESENT"
        elif "support_ticket_read" in name or "support_message" in name:
            category = "SUPPORT_MESSAGE"
            state = _support_state(event)
        elif "attachment_scan" in name or "attachment_read" in name:
            category = "SUPPORT_ATTACHMENT"
            state = "ABSENT" if absent else "PRESENT"
        elif "connector_config" in name or "connector_heartbeat" in name:
            category = "DATA_FLOW"
            enabled = str(event.get("enabled", "")).casefold()
            state = "ACTIVE" if enabled in {"true", "1"} else "DISABLED"
        elif "restore_policy" in name or "restore_candidate" in name or "backup" in name:
            category = "BACKUP_ARCHIVE"
            allowed = str(event.get("restore_allowed", "")).casefold() in {"true", "1"}
            eligible = str(event.get("eligible", "")).casefold() in {"true", "1"}
            blocked = str(event.get("deletion_block", "")).casefold() in {"true", "1"}
            state = "ACTIVE" if allowed or (eligible and not blocked) else "BLOCKED"
        elif "audit_record" in name or "audit_event" in name:
            category, state = "SECURITY_AUDIT_LOG", "PRESENT"
        elif "export" in name:
            category = "USER_EXPORT"
            available = str(event.get("available", "")).casefold()
            state = "ABSENT" if available in {"false", "0"} or absent else "PRESENT"
        elif "tombstone" in name or "deleted_customer" in name:
            category = "ACCOUNT_TOMBSTONE"
            state = _tombstone_state(event)
        else:
            category = category_for_resource(resource)
            if category is None:
                return
            state = "ABSENT" if absent else "PRESENT"
            self._add(
                system=service or SYSTEM_BY_CATEGORY.get(category, ""),
                resource=resource,
                category=category,
                state=state or "PRESENT",
                observed_at=observed,
                evidence_id=item["file_id"],
                keys=keys,
                source=str(path),
                weak=True,
            )
            return

        self._add(
            system=service or SYSTEM_BY_CATEGORY.get(category, ""),
            resource=resource,
            category=category,
            state=state or "PRESENT",
            observed_at=observed,
            evidence_id=item["file_id"],
            keys=keys,
            source=str(path),
        )

    # ------------------------------------------------------------ media (PDF/PNG)
    def _parse_media(self, path: Path, item: dict[str, str]) -> None:
        text = ""
        if path.suffix.lower() == ".pdf":
            try:
                from pypdf import PdfReader  # type: ignore

                text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
            except ImportError:
                self._warn(f"pypdf unavailable; skipping {path.name}")
                return
        else:
            executable = shutil.which("tesseract")
            if not executable:
                self._warn(f"tesseract unavailable; skipping {path.name}")
                return
            completed = subprocess.run(
                [executable, str(path), "stdout"], capture_output=True, text=True, check=False
            )
            if completed.returncode:
                self._warn(f"OCR failed for {path.name}: {completed.stderr.strip()}")
                return
            text = completed.stdout

        text = text.strip()
        if not text:
            self._warn(f"no text extracted from {path.name}")
            return

        resources = sorted({match.group(0) for match in _RESOURCE_RE.finditer(text)})
        subjects = self.identities.resolve_any(text)
        origin_category = ORIGIN_CATEGORY.get(item.get("origin", ""), "")
        self._mark(item["file_id"], origin_category)

        # An OCR/PDF page can flatten a multi-row table.  In that case the
        # identity-to-resource pairing is ambiguous, so no subject link is made
        # unless the artefact concerns a single person.
        safe_subjects = subjects if len(resources) <= 1 or len(subjects) <= 1 else set()
        keys = list(safe_subjects) if safe_subjects else []

        for resource in resources:
            category = category_for_resource(resource) or origin_category
            if not category:
                continue
            lowered = resource.casefold()
            if lowered.startswith("support_") and "attachment" in text.casefold():
                category = "SUPPORT_ATTACHMENT"
            if lowered.startswith("object_"):
                category = "SUPPORT_ATTACHMENT"
            self._mark(item["file_id"], category)
            state = _media_state(category, text, subjects)
            self._add(
                system=SYSTEM_BY_CATEGORY.get(category, item.get("origin", "")),
                resource=resource,
                category=category,
                state=state,
                observed_at=item["captured_at"],
                evidence_id=item["file_id"],
                keys=keys,
                source=item["file_path"],
            )

    # -------------------------------------------------------------- postprocess
    def _propagate(self) -> None:
        """Share subjects and category across observations of one resource."""

        for observation in self.observations:
            linked = self.resource_subjects.get(observation.resource_id)
            if linked and not observation.subjects:
                object.__setattr__(
                    observation, "subjects", frozenset(linked)
                )
            named = self.resource_categories.get(observation.resource_id)
            if named and len(named) == 1:
                (category,) = tuple(named)
                if observation.category != category:
                    object.__setattr__(observation, "category", category)
                    object.__setattr__(
                        observation,
                        "system_id",
                        canonical_system(observation.system_id, category),
                    )

    # ------------------------------------------------------------------ query
    def facts_for(
        self, user_id: str, cutoff: datetime
    ) -> list[Observation]:
        """Latest grounded state per record, one record per data category."""

        relevant = [
            observation
            for observation in self.observations
            if user_id in observation.subjects
            and observation.observed_at <= cutoff
        ]
        # Prefer artefacts that already existed at the audit time: a later
        # capture may still describe older events, but the auditor's first
        # choice is the evidence available then.  This is decided per record,
        # so a record that only a later capture mentions is still usable.
        grouped: dict[tuple[str, str], list[Observation]] = defaultdict(list)
        for observation in relevant:
            grouped[observation.key].append(observation)
        latest: dict[tuple[str, str], Observation] = {}
        for key, candidates in grouped.items():
            contemporaneous = [
                observation
                for observation in candidates
                if observation.available_at <= cutoff
            ]
            pool = contemporaneous or candidates
            latest[key] = max(pool, key=lambda obs: _order_key(obs))

        by_category: dict[str, Observation] = {}
        for observation in latest.values():
            current = by_category.get(observation.category)
            if current is None or _newer(observation, current):
                by_category[observation.category] = observation
        return sorted(
            by_category.values(), key=lambda obs: (obs.category, obs.system_id, obs.resource_id)
        )

    def latest_negative(
        self, user_id: str, category: str, cutoff: datetime
    ) -> Observation | None:
        candidates = [
            observation
            for observation in self.observations
            if user_id in observation.subjects
            and observation.category == category
            and observation.state == "ABSENT"
            and observation.observed_at <= cutoff
        ]
        return max(candidates, key=lambda obs: obs.observed_at) if candidates else None

    def evidence_covering(
        self, category: str, cutoff: datetime
    ) -> list[Observation]:
        """Observations of a category from any subject (used for absence proof)."""

        return [
            observation
            for observation in self.observations
            if observation.category == category
            and observation.observed_at <= cutoff
            and observation.available_at <= cutoff
        ]


STATE_ALIASES = {
    "FOUND": "PRESENT",
    "EXISTS": "PRESENT",
    "NOT_FOUND": "ABSENT",
    "DELETED": "ABSENT",
    "ENABLED": "ACTIVE",
    "STOPPED": "DISABLED",
    "DEIDENTIFIED": "ANONYMIZED",
}


def _order_key(observation: Observation) -> tuple:
    """Sort key for picking the authoritative observation of one record.

    Later event time wins; on a tie an observation that the record still exists
    wins (a replica captured after a primary deletion is drift, not proof the
    data is gone); remaining ties are broken deterministically by ids.
    """

    return (
        observation.observed_at,
        observation.positive,
        observation.evidence_id,
        observation.resource_id,
    )


def _newer(candidate: Observation, current: Observation) -> bool:
    return _order_key(candidate) > _order_key(current)


def _state_from_result(result: str) -> str:
    lowered = result.casefold()
    if any(token in lowered for token in ("not_found", "missing", "absent", "deleted")):
        return "ABSENT"
    if "anonym" in lowered or "deidentif" in lowered:
        return "ANONYMIZED"
    if "redact" in lowered:
        return "REDACTED"
    if "block" in lowered:
        return "BLOCKED"
    if "disabl" in lowered or "stopped" in lowered:
        return "DISABLED"
    if "active" in lowered or "enabl" in lowered:
        return "ACTIVE"
    return "PRESENT"


def _direct_identifiers(payload: dict[str, Any]) -> list[str]:
    found = []
    for field_name in _DIRECT_IDENTIFIER_FIELDS:
        value = payload.get(field_name)
        if not _is_null(value):
            found.append(str(value))
    return found


def _support_state(payload: dict[str, Any]) -> str:
    """Shared conversations keep context but must lose requester identifiers.

    ``customer_reference`` is the stable internal reference, which policy
    permits to remain; only direct identifiers make the row unsafe.
    """

    direct = [
        payload.get(name)
        for name in ("requester_name", "requester_email", "requester_phone",
                     "owner_email", "owner_phone", "customer_email", "email",
                     "phone", "email_hash", "full_name", "display_name", "name")
    ]
    if any(not _is_null(value) for value in direct):
        return "IDENTIFIABLE"
    text = " ".join(
        str(payload.get(name) or "")
        for name in ("message_text", "message_excerpt", "body", "content", "subject")
    )
    if _EMAIL_RE.search(text):
        return "IDENTIFIABLE"
    if len(digits(text)) >= 9:
        return "IDENTIFIABLE"
    return "REDACTED"


def _tombstone_state(payload: dict[str, Any]) -> str:
    identifiers = [
        payload.get(name)
        for name in ("name", "email", "phone", "email_hash", "full_name")
    ]
    if any(not _is_null(value) for value in identifiers):
        return "IDENTIFIABLE"
    return "REDACTED"


def _media_state(category: str, text: str, subjects: set[str]) -> str:
    lowered = text.casefold()
    if category == "DATA_FLOW":
        if "disabled" in lowered or "stopped" in lowered or "paused" in lowered:
            return "DISABLED"
        return "ACTIVE"
    if category == "BACKUP_ARCHIVE":
        if re.search(r"restore.{0,30}(blocked|disabled|denied)", lowered):
            return "BLOCKED"
        return "ACTIVE"
    if category in {"ANALYTICS_PROFILE", "PRODUCT_TELEMETRY", "EMAIL_DELIVERY_LOG"}:
        return "IDENTIFIABLE" if subjects else "ANONYMIZED"
    if category == "SUPPORT_MESSAGE":
        return "IDENTIFIABLE" if subjects else "REDACTED"
    if category == "ACCOUNT_TOMBSTONE":
        return "IDENTIFIABLE" if len(subjects) else "REDACTED"
    return "PRESENT"
