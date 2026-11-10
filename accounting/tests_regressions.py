"""S06: synthetic PostgreSQL contracts for the unchanged legacy finance paths.

KnownFinancialMismatch is still a failing assertion under Django's ordinary
runner. Only the explicit accounting runner recognises its exact legacy shape.
Legacy edit/delete probes here are diagnostics, not approved correction flows;
S24 replaces their adapter with attributable reversal/replacement operations.
"""

from datetime import date
from decimal import Decimal
import secrets
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.urls import reverse

from accounting.models import Agreement, CashAccount, Category, Entity, Transaction
from accounting.regression_runner import assert_financial_equal, regression_case
from accounting.membership import create_accountant_profile, create_office

DAY = date(2026, 1, 15)


class FinancialRegressionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        if connection.vendor != "postgresql" or connection.pg_version // 10000 != 17:
            raise AssertionError("S06 financial evidence requires real PostgreSQL 17")
        cls.user = get_user_model().objects.create_user("s06-synthetic-accountant", password=secrets.token_urlsafe(32))
        create_accountant_profile(user_id=cls.user.pk, office_id=create_office(name="ΔΟΚΙΜΑΣΤΙΚΟ ΓΡΑΦΕΙΟ S06").pk,
                                  role="accountant")
        cls.customer_a = Entity.objects.create(name="ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΕΛΑΤΗΣ Α S06", entity_type="CUSTOMER", vat_number="000000011")
        cls.customer_b = Entity.objects.create(name="ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΕΛΑΤΗΣ Β S06", entity_type="CUSTOMER", vat_number="000000012")
        cls.supplier_a = Entity.objects.create(name="ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΡΟΜΗΘΕΥΤΗΣ Α S06", entity_type="SUPPLIER", vat_number="000000013")
        cls.supplier_b = Entity.objects.create(name="ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΡΟΜΗΘΕΥΤΗΣ Β S06", entity_type="SUPPLIER", vat_number="000000014")
        cls.source = CashAccount.objects.create(name="ΔΟΚΙΜΑΣΤΙΚΟ ΤΑΜΕΙΟ Α S06", opening_balance=Decimal("100.00"))
        cls.destination = CashAccount.objects.create(name="ΔΟΚΙΜΑΣΤΙΚΟ ΤΑΜΕΙΟ Β S06", opening_balance=Decimal("100.00"))
        cls.category = Category.objects.create(name="ΔΟΚΙΜΑΣΤΙΚΕΣ ΥΠΗΡΕΣΙΕΣ S06")
        cls.receivable = Agreement.objects.create(entity=cls.customer_a, agreement_type="RECEIVABLE",
            description="ΔΟΚΙΜΑΣΤΙΚΗ ΣΥΜΦΩΝΙΑ ΠΕΛΑΤΗ S06", total_amount=Decimal("100.00"), start_date=DAY)
        cls.payable = Agreement.objects.create(entity=cls.supplier_a, agreement_type="PAYABLE",
            description="ΔΟΚΙΜΑΣΤΙΚΗ ΣΥΜΦΩΝΙΑ ΠΡΟΜΗΘΕΥΤΗ S06", total_amount=Decimal("100.00"), start_date=DAY)

    def setUp(self):
        self.client.force_login(self.user)

    def movement(self, amount, direction="INCOME", *, account=None, agreement=None):
        return Transaction.objects.create(transaction_date=DAY, transaction_type=direction,
            amount=Decimal(amount), description="ΔΟΚΙΜΑΣΤΙΚΗ ΚΙΝΗΣΗ S06", cash_account=account or self.source,
            category=self.category, entity=self.customer_a if direction == "INCOME" else self.supplier_a,
            agreement=agreement)

    def post_cash(self, direction, amount, *, entity=None, agreement=None, same_account=False):
        if direction == "transfer":
            data = {"transfer_date": DAY.isoformat(), "amount": amount,
                    "from_account": self.source.pk, "to_account": self.source.pk if same_account else self.destination.pk,
                    "description": "ΔΟΚΙΜΑΣΤΙΚΗ ΜΕΤΑΦΟΡΑ S06"}
        else:
            data = {"transaction_date": DAY.isoformat(), "amount": amount, "cash_account": self.source.pk,
                    "description": "ΔΟΚΙΜΑΣΤΙΚΗ ΚΙΝΗΣΗ S06", "category": self.category.pk,
                    "entity": (entity or (self.customer_a if direction == "income" else self.supplier_a)).pk,
                    "agreement": agreement.pk if agreement else ""}
        return self.client.post(reverse("add-" + direction), data, HTTP_ACCEPT_LANGUAGE="en-US,en")

    def balances(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        return {account.pk: account.current_balance for account in response.context["cash_accounts"]}

    def agreement_state(self, agreement):
        response = self.client.get(reverse("agreement-detail", args=[agreement.pk]))
        self.assertEqual(response.status_code, 200)
        return response.context["remaining_balance"], response.context["agreement"].status

    def assert_rejected(self, response, field="amount"):
        self.assertIn(response.status_code, (200, 400))
        self.assertEqual(response.headers["Content-Language"], "el")
        self.assertIn(field, response.context["form"].errors)

    @regression_case("BAL-001")
    def test_empty_account(self):
        assert_financial_equal(self, self.balances()[self.source.pk], Decimal("100.00"), legacy=None)

    @regression_case("BAL-002")
    def test_income_only(self):
        self.movement("50.00")
        assert_financial_equal(self, self.balances()[self.source.pk], Decimal("150.00"), legacy=None)

    @regression_case("BAL-003")
    def test_expense_only(self):
        self.movement("20.00", "EXPENSE")
        assert_financial_equal(self, self.balances()[self.source.pk], Decimal("80.00"), legacy=None)

    @regression_case("TRF-001")
    def test_transfer_excluded_from_operating_totals(self):
        self.movement("50.00"); self.movement("20.00", "EXPENSE")
        self.assertEqual(self.post_cash("transfer", "1.000,00").status_code, 302)
        response = self.client.get(reverse("summary-report"))
        self.assertEqual(response.status_code, 200)
        values = tuple(response.context[field] for field in ("total_income", "total_expense", "net_for_period"))
        assert_financial_equal(self, values, (Decimal("50.00"), Decimal("20.00"), Decimal("30.00")),
                               legacy=(Decimal("1050.00"), Decimal("1020.00"), Decimal("30.00")))

    def cross_counterparty(self, direction):
        agreement = self.receivable if direction == "income" else self.payable
        other = self.customer_b if direction == "income" else self.supplier_b
        before = Transaction.objects.count()
        response = self.post_cash(direction, "25,00", entity=other, agreement=agreement)
        self.assertIn(response.status_code, (200, 302, 400))
        observed = Transaction.objects.count() - before, self.agreement_state(agreement)[0]
        assert_financial_equal(self, observed, (0, Decimal("100.00")), legacy=(1, Decimal("75.00")))
        self.assert_rejected(response, "agreement")

    @regression_case("SET-001")
    def test_cross_counterparty_income(self):
        self.cross_counterparty("income")

    @regression_case("SET-002")
    def test_cross_counterparty_expense(self):
        self.cross_counterparty("expense")

    def nonpositive_cash(self, direction, amount):
        before = Transaction.objects.count()
        response = self.post_cash(direction, amount)
        self.assertIn(response.status_code, (200, 302, 400))
        has_error = response.status_code in (200, 400) and "amount" in response.context["form"].errors
        observed = Transaction.objects.count() - before, has_error
        assert_financial_equal(self, observed, (0, True), legacy=(2 if direction == "transfer" else 1, False))
        self.assert_rejected(response)

    @regression_case("AMT-001")
    def test_income_zero(self):
        self.nonpositive_cash("income", "0,00")

    @regression_case("AMT-002")
    def test_income_negative(self):
        self.nonpositive_cash("income", "-1,00")

    @regression_case("AMT-003")
    def test_expense_zero(self):
        self.nonpositive_cash("expense", "0,00")

    @regression_case("AMT-004")
    def test_expense_negative(self):
        self.nonpositive_cash("expense", "-1,00")

    @regression_case("AMT-005")
    def test_transfer_zero(self):
        self.nonpositive_cash("transfer", "0,00")

    @regression_case("AMT-006")
    def test_transfer_negative(self):
        self.nonpositive_cash("transfer", "-1,00")

    def nonpositive_model(self, amount):
        before = Transaction.objects.count()
        try:
            with transaction.atomic():
                self.movement(amount)
        except (IntegrityError, ValidationError):
            pass
        assert_financial_equal(self, Transaction.objects.count() - before, 0, legacy=1)

    @regression_case("AMT-007")
    def test_model_zero(self):
        self.nonpositive_model("0.00")

    @regression_case("AMT-008")
    def test_model_negative(self):
        self.nonpositive_model("-1.00")

    @regression_case("STA-001")
    def test_reduced_receipt_reopens_agreement(self):
        receipt = self.movement("100.00", agreement=self.receivable)
        self.assertEqual(self.agreement_state(self.receivable), (Decimal("0.00"), "COMPLETED"))
        receipt.amount = Decimal("25.00"); receipt.save()
        assert_financial_equal(self, self.agreement_state(self.receivable), (Decimal("75.00"), "ACTIVE"),
                               legacy=(Decimal("75.00"), "COMPLETED"))

    @regression_case("STA-002")
    def test_deleted_receipt_reopens_agreement(self):
        receipt = self.movement("100.00", agreement=self.receivable)
        self.assertEqual(self.agreement_state(self.receivable), (Decimal("0.00"), "COMPLETED"))
        receipt.delete()
        assert_financial_equal(self, self.agreement_state(self.receivable), (Decimal("100.00"), "ACTIVE"),
                               legacy=(Decimal("100.00"), "COMPLETED"))

    @regression_case("CAN-001")
    def test_transaction_resave_preserves_cancellation(self):
        receipt = self.movement("100.00", agreement=self.receivable)
        self.receivable.refresh_from_db()
        self.receivable.status = "CANCELLED"; self.receivable.save()
        receipt = Transaction.objects.get(pk=receipt.pk)
        receipt.save()
        self.receivable.refresh_from_db()
        assert_financial_equal(self, self.receivable.status, "CANCELLED", legacy="COMPLETED")

    def invalid_filter(self, screen, field):
        self.client.raise_request_exception = False
        value = "2026-02-30" if field == "start_date" else "invalid-date" if field == "end_date" else "invalid-id"
        response = self.client.get(reverse("transaction-list" if screen == "list" else "summary-report"),
                                   {field: value}, HTTP_ACCEPT_LANGUAGE="en-US,en")
        self.assertEqual(response.headers["Content-Language"], "el")
        if response.status_code == 500:
            self.assertIsNotNone(response.exc_info)
            self.assertIsInstance(response.exc_info[1], (ValueError, ValidationError))
            assert_financial_equal(self, "server_error", "field_validation", legacy="server_error")
        self.assertIn(response.status_code, (200, 400))
        try:
            form = response.context["filter_form"]
        except (KeyError, TypeError):
            self.fail("Invalid filters must expose their field errors in filter_form")
        self.assertIn(field, form.errors)

    @regression_case("FLT-001")
    def test_invalid_list_start_date(self):
        self.invalid_filter("list", "start_date")

    @regression_case("FLT-002")
    def test_invalid_list_end_date(self):
        self.invalid_filter("list", "end_date")

    @regression_case("FLT-003")
    def test_invalid_list_cash_account(self):
        self.invalid_filter("list", "cash_account")

    @regression_case("FLT-004")
    def test_invalid_list_category(self):
        self.invalid_filter("list", "category")

    @regression_case("FLT-005")
    def test_invalid_list_entity(self):
        self.invalid_filter("list", "entity")

    @regression_case("FLT-006")
    def test_invalid_report_start_date(self):
        self.invalid_filter("report", "start_date")

    @regression_case("FLT-007")
    def test_invalid_report_end_date(self):
        self.invalid_filter("report", "end_date")

    @regression_case("FLT-008")
    def test_invalid_report_cash_account(self):
        self.invalid_filter("report", "cash_account")

    @regression_case("FLT-009")
    def test_invalid_report_category(self):
        self.invalid_filter("report", "category")

    @regression_case("CTL-001")
    def test_mixed_account_balance(self):
        self.movement("50.00"); self.movement("20.00", "EXPENSE")
        self.assertEqual(self.balances()[self.source.pk], Decimal("130.00"))

    @regression_case("CTL-002")
    def test_partial_settlement(self):
        self.assertEqual(self.post_cash("income", "25,00", agreement=self.receivable).status_code, 302)
        self.assertEqual(self.agreement_state(self.receivable), (Decimal("75.00"), "ACTIVE"))

    @regression_case("CTL-003")
    def test_full_settlement(self):
        self.assertEqual(self.post_cash("income", "100,00", agreement=self.receivable).status_code, 302)
        self.assertEqual(self.agreement_state(self.receivable), (Decimal("0.00"), "COMPLETED"))

    @regression_case("CTL-004")
    def test_transfer_moves_1000(self):
        self.source.opening_balance = Decimal("2000.00"); self.source.save()
        # Nonzero cancelling movements keep LEG-003 from masking this control.
        for account in (self.source, self.destination):
            self.movement("1.00", account=account); self.movement("1.00", "EXPENSE", account=account)
        before = set(Transaction.objects.values_list("pk", flat=True))
        self.assertEqual(self.post_cash("transfer", "1.000,00").status_code, 302)
        legs = list(Transaction.objects.exclude(pk__in=before))
        self.assertEqual(len(legs), 2)
        self.assertEqual({leg.transfer_id for leg in legs}, {legs[0].transfer_id})
        self.assertEqual({(leg.cash_account_id, leg.transaction_type, leg.amount) for leg in legs},
                         {(self.source.pk, "EXPENSE", Decimal("1000.00")), (self.destination.pk, "INCOME", Decimal("1000.00"))})
        balances = self.balances()
        self.assertEqual((balances[self.source.pk], balances[self.destination.pk]), (Decimal("1000.00"), Decimal("1100.00")))

    @regression_case("CTL-005")
    def test_failed_second_transfer_leg_rolls_back(self):
        before = Transaction.objects.count()
        real_create = Transaction.objects.create
        calls = 0

        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise IntegrityError("Synthetic S06 second-leg failure")
            return real_create(*args, **kwargs)

        with patch("accounting.views.Transaction.objects.create", side_effect=fail_second):
            with self.assertRaises(IntegrityError):
                self.post_cash("transfer", "1.000,00")
        self.assertEqual(calls, 2)
        self.assertEqual(Transaction.objects.count(), before)

    @regression_case("CTL-006")
    def test_same_account_transfer_is_rejected(self):
        response = self.post_cash("transfer", "25,00", same_account=True)
        self.assert_rejected(response, "__all__")
        self.assertEqual(Transaction.objects.count(), 0)

    def invalid_amount_text(self, direction):
        response = self.post_cash(direction, "μη έγκυρο ποσό")
        self.assert_rejected(response)
        self.assertEqual(Transaction.objects.count(), 0)

    @regression_case("CTL-007")
    def test_invalid_income_text_is_rejected(self):
        self.invalid_amount_text("income")

    @regression_case("CTL-008")
    def test_invalid_expense_text_is_rejected(self):
        self.invalid_amount_text("expense")

    @regression_case("CTL-009")
    def test_invalid_transfer_text_is_rejected(self):
        self.invalid_amount_text("transfer")

    @regression_case("CTL-010")
    def test_receipt_cannot_select_payable(self):
        response = self.post_cash("income", "25,00", agreement=self.payable)
        self.assert_rejected(response, "agreement")
        self.assertEqual(Transaction.objects.count(), 0)
