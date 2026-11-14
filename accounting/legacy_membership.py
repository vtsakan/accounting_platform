"""Review-bound, complete user mappings. This never imports business records."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from .membership import create_accountant_profile
from .models import AccountantProfile, Office


def fail(message):
    raise ValidationError(message, code="invalid_mapping")


def inventory():
    return {"users": list(get_user_model().objects.order_by("pk").values(
                "id", "username", "is_active", "is_staff", "is_superuser")),
            "offices": [{"id": str(o.pk), "name": o.name, "is_active": o.is_active}
                        for o in Office.objects.only("id", "name", "is_active").order_by("pk")]}


def fingerprint(value):
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def template():
    current = inventory()
    return {"schema": 1, "inventory": current, "inventory_sha256": fingerprint(current),
            "reviewed_by": "", "reviewed_at": "",
            "mappings": [{"user_id": u["id"], "username": u["username"], "office_id": "", "role": ""}
                         for u in current["users"]], "excluded_users": []}


def load_mapping(path):
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                fail("Το αρχείο περιέχει διπλό πεδίο JSON.")
            result[key] = value
        return result
    with Path(path).open("rb") as source:
        raw = source.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        fail("Το αρχείο αντιστοίχισης είναι πολύ μεγάλο.")
    try:
        def invalid_constant(value):
            raise ValueError("Non-finite JSON value")
        return json.loads(raw, object_pairs_hook=unique_keys, parse_constant=invalid_constant)
    except (ValueError, UnicodeError):
        fail("Το αρχείο αντιστοίχισης δεν είναι έγκυρο JSON.")


def reviewed_plan(document):
    keys = {"schema", "inventory", "inventory_sha256", "reviewed_by", "reviewed_at", "mappings", "excluded_users"}
    if not isinstance(document, dict) or set(document) != keys or type(document["schema"]) is not int or document["schema"] != 1:
        fail("Η δομή της αντιστοίχισης δεν είναι έγκυρη.")
    reviewer = document["reviewed_by"]
    if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 200:
        fail("Απαιτείται το όνομα του ελεγκτή της αντιστοίχισης.")
    try:
        reviewed = datetime.fromisoformat(document["reviewed_at"])
        if reviewed.tzinfo is None or reviewed > datetime.now(timezone.utc):
            raise ValueError
    except (TypeError, ValueError):
        fail("Απαιτείται έγκυρη ημερομηνία ελέγχου με ζώνη ώρας.")
    current = inventory()
    if document["inventory"] != current or document["inventory_sha256"] != fingerprint(current):
        fail("Η απογραφή άλλαξε. Εξαγάγετε και ελέγξτε νέα αντιστοίχιση.")
    users = {u["id"]: u for u in current["users"]}
    offices = {o["id"]: o for o in current["offices"]}
    seen, planned = set(), []
    for kind, fields in (("mappings", {"user_id", "username", "office_id", "role"}),
                         ("excluded_users", {"user_id", "username", "reason"})):
        rows = document[kind]
        if not isinstance(rows, list):
            fail("Οι αντιστοιχίσεις πρέπει να είναι λίστα.")
        for row in rows:
            if not isinstance(row, dict) or set(row) != fields or type(row["user_id"]) is not int:
                fail("Μία εγγραφή αντιστοίχισης δεν είναι έγκυρη.")
            user_id = row["user_id"]
            if user_id in seen or user_id not in users or row["username"] != users[user_id]["username"]:
                fail("Υπάρχει διπλός, άγνωστος ή αμφίσημος χρήστης.")
            seen.add(user_id)
            existing = AccountantProfile.objects.filter(user_id=user_id).first()
            if kind == "excluded_users":
                if not isinstance(row["reason"], str) or not row["reason"].strip() or len(row["reason"]) > 500 or existing:
                    fail("Ο αποκλεισμός απαιτεί αιτιολογία και χρήστη χωρίς προφίλ.")
                continue
            try:
                office_id = str(uuid.UUID(row["office_id"]))
            except (ValueError, AttributeError, TypeError):
                fail("Το αναγνωριστικό γραφείου δεν είναι έγκυρο.")
            if office_id not in offices or not offices[office_id]["is_active"] or not users[user_id]["is_active"]:
                fail("Η αντιστοίχιση απαιτεί γνωστό ενεργό χρήστη και γραφείο.")
            if row["role"] not in AccountantProfile.Role.values:
                fail("Ο ρόλος δεν είναι έγκυρος.")
            if existing and (str(existing.office_id) != office_id or existing.role != row["role"] or not existing.is_active):
                fail("Το υπάρχον προφίλ διαφέρει από την αντιστοίχιση.")
            planned.append({"user_id": user_id, "office_id": office_id, "role": row["role"], "exists": bool(existing)})
    if seen != set(users):
        fail("Κάθε χρήστης χρειάζεται αντιστοίχιση ή ρητό αιτιολογημένο αποκλεισμό.")
    return planned


@transaction.atomic
def backfill(document, *, apply=False):
    # Fixed locking order matches the service; validation repeats under these
    # locks. Snapshot changes/new users force review; no partial writes survive.
    list(Office.objects.select_for_update().order_by("pk").values_list("pk", flat=True))
    list(get_user_model().objects.select_for_update().order_by("pk").values_list("pk", flat=True))
    planned = reviewed_plan(document)
    if apply:
        for row in sorted(planned, key=lambda row: row["user_id"]):
            create_accountant_profile(user_id=row["user_id"], office_id=row["office_id"], role=row["role"])
    return {"status": "Applied" if apply else "Dry run", "mapped": len(planned),
            "would_create": sum(not row["exists"] for row in planned),
            "already_matching": sum(row["exists"] for row in planned),
            "excluded_without_business_access": len(document["excluded_users"]),
            "mapping_sha256": fingerprint(document), "database_changed": apply and any(not r["exists"] for r in planned)}
