"""Maintenance-only, complete reviewed ownership mapping for the five old tables."""
from datetime import datetime, timezone
import json
import uuid

from django.db import connection, transaction

from .legacy_membership import fail, fingerprint
from .models import Agreement, CashAccount, Category, Entity, Office, Transaction

MODELS = {model._meta.model_name: model for model in (Entity, CashAccount, Category, Agreement, Transaction)}
ENTITY_FIELDS = ('id','entity_type','name','vat_number','tax_office','address','city','postal_code',
                 'phone_number','email','created_at','updated_at','office_id')
LINKS = (("category", "parent_id", "category"), ("agreement", "entity_id", "entity"),
         ("transaction", "cash_account_id", "cashaccount"), ("transaction", "category_id", "category"),
         ("transaction", "entity_id", "entity"), ("transaction", "agreement_id", "agreement"))


def source():
    rows, snapshot = {}, []
    for name, model in MODELS.items():
        # This is the S12 historical mapping contract, not later workspace data.
        for row in model.objects.order_by("pk").values(*(ENTITY_FIELDS if name == 'entity' else ())):
            key = (name, row["id"])
            rows[key] = row
            original = {k: v for k, v in row.items() if k != "office_id"}
            digest = fingerprint(json.loads(json.dumps(original, default=str)))
            snapshot.append({"model": name, "id": row["id"], "label": row.get("name", row.get("description", "")), "sha256": digest})
    offices = [{"id": str(o.pk), "name": o.name, "is_active": o.is_active} for o in Office.objects.only("id", "name", "is_active").order_by("pk")]
    return rows, {"records": snapshot, "offices": offices}


def template():
    rows, inventory = source()
    return {"schema": 1, "inventory": inventory, "inventory_sha256": fingerprint(inventory),
            "reviewed_by": "", "reviewed_at": "",
            "assignments": [{"model": name, "id": key, "office_id": str(row["office_id"]) if row["office_id"] else ""}
                            for (name, key), row in rows.items()]}


def reviewed_plan(document):
    required = {"schema", "inventory", "inventory_sha256", "reviewed_by", "reviewed_at", "assignments"}
    if not isinstance(document, dict) or set(document) != required or type(document["schema"]) is not int or document["schema"] != 1:
        fail("Η δομή της αντιστοίχισης εγγραφών δεν είναι έγκυρη.")
    if not isinstance(document["reviewed_by"], str) or not document["reviewed_by"].strip() or len(document["reviewed_by"]) > 200:
        fail("Απαιτείται ελεγκτής για την ιδιοκτησία των εγγραφών.")
    try:
        reviewed = datetime.fromisoformat(document["reviewed_at"])
        if reviewed.tzinfo is None or reviewed > datetime.now(timezone.utc):
            raise ValueError
    except (ValueError, TypeError):
        fail("Απαιτείται έγκυρη ημερομηνία ελέγχου με ζώνη ώρας.")
    rows, current = source()
    if document["inventory"] != current or document["inventory_sha256"] != fingerprint(current):
        fail("Τα αρχικά δεδομένα άλλαξαν. Απαιτείται νέα απογραφή και έλεγχος.")
    if not isinstance(document["assignments"], list):
        fail("Οι αντιστοιχίσεις εγγραφών πρέπει να είναι λίστα.")
    known_offices = {row["id"] for row in current["offices"]}
    assigned = {}
    for row in document["assignments"]:
        if not isinstance(row, dict) or set(row) != {"model", "id", "office_id"} or type(row["id"]) is not int or not isinstance(row["model"], str):
            fail("Μία εγγραφή αντιστοίχισης δεν είναι έγκυρη.")
        key = (row["model"], row["id"])
        if key not in rows or key in assigned:
            fail("Υπάρχει διπλή ή άγνωστη εγγραφή.")
        try:
            office = str(uuid.UUID(row["office_id"]))
        except (ValueError, TypeError, AttributeError):
            fail("Το αναγνωριστικό γραφείου δεν είναι έγκυρο.")
        previous = rows[key]["office_id"]
        if office not in known_offices or (previous and str(previous) != office):
            fail("Η ιδιοκτησία είναι άγνωστη ή διαφέρει από την υπάρχουσα εγγραφή.")
        assigned[key] = office
    if set(assigned) != set(rows):
        fail("Κάθε υπάρχουσα εγγραφή χρειάζεται ρητή αντιστοίχιση γραφείου.")
    for child, field, parent in LINKS:
        for (name, key), row in rows.items():
            if name == child and row[field] is not None and assigned[(child, key)] != assigned[(parent, row[field])]:
                fail("Οι συνδεδεμένες εγγραφές έχουν αντικρουόμενη ιδιοκτησία.")
    groups, unique = {}, set()
    for key, row in rows.items():
        office = assigned[key]
        if key[0] == "transaction":
            token = str(row["transfer_id"])
            if token in groups and groups[token] != office:
                fail("Οι συνδεδεμένες κινήσεις μεταφοράς χρειάζονται το ίδιο γραφείο.")
            groups[token] = office
        value = row.get("vat_number") if key[0] == "entity" else row.get("name") if key[0] == "cashaccount" else None
        if value not in (None, ""):
            token = (key[0], office, value)
            if token in unique:
                fail("Υπάρχουν διπλές μη κενές τιμές ΑΦΜ ή ονόματα ταμείων στο ίδιο γραφείο.")
            unique.add(token)
    return rows, assigned


@transaction.atomic
def backfill(document, *, apply=False):
    if connection.vendor != "postgresql":
        fail("Απαιτείται PostgreSQL για την αντιστοίχιση.")
    tables = ["accounting_office"] + sorted(model._meta.db_table for model in MODELS.values())
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout = '10s'")
        cursor.execute("LOCK TABLE " + ", ".join(tables) + " IN SHARE ROW EXCLUSIVE MODE")
    rows, assigned = reviewed_plan(document)
    pending = [key for key, row in rows.items() if row["office_id"] is None]
    if apply:
        for name, key in pending:
            MODELS[name].objects.filter(pk=key, office_id__isnull=True).update(office_id=assigned[(name, key)])
    return {"status": "Applied" if apply else "Dry run", "records": len(rows), "would_assign": len(pending),
            "already_matching": len(rows) - len(pending), "mapping_sha256": fingerprint(document),
            "database_changed": bool(apply and pending)}
