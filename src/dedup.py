"""Duplicate detection for expense records."""

import logging
from difflib import SequenceMatcher
from pathlib import Path

from .utils import load_json, save_json

logger = logging.getLogger(__name__)


def _fuzzy_match(s1: str, s2: str) -> float:
    """Calculate similarity ratio between two strings."""
    if not s1 or not s2:
        return 0.0
    return SequenceMatcher(None, s1.lower().strip(), s2.lower().strip()).ratio()


def _amount_match(a1, a2, tolerance: float = 0.01) -> bool:
    """Check if two amounts are close enough."""
    try:
        return abs(float(a1) - float(a2)) <= tolerance
    except (TypeError, ValueError):
        return False


def _date_match(d1: str | None, d2: str | None) -> bool:
    """Check if two dates match."""
    if not d1 or not d2:
        return False
    # Normalize date strings
    d1 = d1.strip().replace("/", "-")
    d2 = d2.strip().replace("/", "-")
    return d1 == d2


def check_duplicate(
    record: dict,
    other_records: list[dict],
    fuzzy_threshold: float = 0.85,
    amount_tolerance: float = 0.01,
) -> dict | None:
    """Check if a record is a duplicate of any record in the comparison list.

    Duplicate criteria (ALL must match):
    - Same date
    - Same location/vendor (fuzzy match)
    - Same amount
    - Same merchant/vendor

    Returns the matching record if duplicate found, None otherwise.
    """
    for other in other_records:
        if other is record:
            continue

        # Chinese invoice: exact match on invoice_code + invoice_number
        if (
            record.get("invoice_code")
            and record.get("invoice_number")
            and other.get("invoice_code")
            and other.get("invoice_number")
        ):
            if (
                record["invoice_code"] == other["invoice_code"]
                and record["invoice_number"] == other["invoice_number"]
            ):
                return other
            continue  # If both have invoice codes but don't match, not duplicates

        # General duplicate: date + vendor + amount + currency must all match
        date_ok = _date_match(record.get("date"), other.get("date"))
        if not date_ok:
            continue

        amount_ok = _amount_match(
            record.get("amount"), other.get("amount"), amount_tolerance
        )
        if not amount_ok:
            continue

        vendor_ok = _fuzzy_match(
            str(record.get("vendor", "")), str(other.get("vendor", ""))
        ) >= fuzzy_threshold
        if not vendor_ok:
            continue

        # All criteria matched
        return other

    return None


def batch_dedup(
    records: list[dict],
    fuzzy_threshold: float = 0.85,
    amount_tolerance: float = 0.01,
) -> list[dict]:
    """Find duplicates within the current batch.

    Returns list of records that are duplicates (the later occurrence).
    Each duplicate record gets a '_duplicate_of' field added.
    Credit card transactions from different source files are excluded from 
    batch dedup (same vendor+amount on same day is common for separate rides).
    """
    duplicates = []
    for i, rec in enumerate(records):
        # Skip batch dedup between credit card transactions — 
        # same vendor/amount/date is common (e.g. multiple Uber rides)
        if rec.get("_is_credit_card"):
            # Only check against non-CC records for exact invoice match
            non_cc_before = [r for r in records[:i] if not r.get("_is_credit_card")]
            match = check_duplicate(rec, non_cc_before, fuzzy_threshold, amount_tolerance)
        else:
            match = check_duplicate(
                rec, records[:i], fuzzy_threshold, amount_tolerance
            )
        if match:
            rec["_duplicate_of"] = match.get("_source_file", "unknown")
            duplicates.append(rec)
    return duplicates


def history_dedup(
    records: list[dict],
    processed_path: Path,
    fuzzy_threshold: float = 0.85,
    amount_tolerance: float = 0.01,
) -> list[dict]:
    """Find duplicates against historical processed records.

    Returns list of records that match history.
    """
    history = load_json(processed_path)
    history_records = history.get("records", []) if isinstance(history, dict) else []
    if not history_records:
        return []

    duplicates = []
    for rec in records:
        match = check_duplicate(
            rec, history_records, fuzzy_threshold, amount_tolerance
        )
        if match:
            rec["_duplicate_of_history"] = match.get("_source_file", "unknown")
            duplicates.append(rec)
    return duplicates


def clear_history_for_period(
    processed_path: Path, person_name: str, year: int, month: int
):
    """Remove history records for a specific person+period before re-processing."""
    history = load_json(processed_path)
    if not isinstance(history, dict) or "records" not in history:
        return
    period_tag = f"{person_name}_{year}_{month:02d}"
    original = len(history["records"])
    history["records"] = [
        r for r in history["records"] if r.get("_period") != period_tag
    ]
    removed = original - len(history["records"])
    if removed:
        save_json(processed_path, history)
        logger.info(f"Cleared {removed} history records for {period_tag}")


def save_to_history(
    records: list[dict], processed_path: Path,
    person_name: str = "", year: int = 0, month: int = 0,
):
    """Append processed records to history for future dedup."""
    history = load_json(processed_path)
    if not isinstance(history, dict):
        history = {"records": []}
    if "records" not in history:
        history["records"] = []

    period_tag = f"{person_name}_{year}_{month:02d}" if person_name else ""
    for rec in records:
        # Only save key fields needed for dedup
        entry = {
            "date": rec.get("date"),
            "vendor": rec.get("vendor"),
            "amount": rec.get("amount"),
            "currency": rec.get("currency"),
            "invoice_code": rec.get("invoice_code"),
            "invoice_number": rec.get("invoice_number"),
            "_source_file": rec.get("_source_file"),
            "category_l1": rec.get("category_l1"),
            "processed_at": rec.get("_processed_at"),
            "_period": period_tag,
        }
        history["records"].append(entry)

    save_json(processed_path, history)
