import io
import json
import logging
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal
from html.parser import HTMLParser
from types import SimpleNamespace
from unittest.mock import patch

from django import forms
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, SimpleTestCase, override_settings
from django.utils import formats, translation

from accounting.forms import AgreementForm, EntityForm, ExpenseForm, IncomeForm, TransferForm
from accounting.models import Entity
from core.config import boolean, env, integer, load_local_env
from core.locale import ATHENS, GreekMoneyField, athens_to_utc, format_euro, greek_date, parse_euro
from core.redaction import RedactingExceptionReporterFilter, RedactingFormatter, redact_text, register_secret

ROOT = Path(__file__).resolve().parents[2]


def production_env():
    return {"DJANGO_SECRET_KEY": secrets.token_urlsafe(64), "DJANGO_ALLOWED_HOSTS": "preview.example.test",
            "DJANGO_CSRF_TRUSTED_ORIGINS": "https://preview.example.test", "DB_NAME": "synthetic",
            "DB_USER": "synthetic", "DB_PASSWORD": secrets.token_urlsafe(32), "DB_HOST": "db"}


def load_profile(profile, values=None, code=None):
    # Profile probes own their configuration; Compose/local mail settings and
    # sender credentials must not cross into a different settings profile.
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("DJANGO_", "DB_", "AUTH_", "EMAIL_", "DEFAULT_FROM_EMAIL"))}
    environment.update(values or {})
    environment["DJANGO_SETTINGS_MODULE"] = "core.settings." + profile
    code = code or "import django; django.setup(); from django.conf import settings; print(settings.DEBUG)"
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=environment, capture_output=True, text=True)


class ConfigurationTests(SimpleTestCase):
    def test_server_entrypoints_default_to_fail_closed_production(self):
        environment = {key: value for key, value in os.environ.items() if not key.startswith(("DJANGO_", "DB_"))}
        for module in ("core.wsgi", "core.asgi"):
            with self.subTest(module=module):
                result = subprocess.run([sys.executable, "-c", "import " + module], cwd=ROOT, env=environment, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("DJANGO_SECRET_KEY", result.stderr)

    def test_test_and_production_do_not_load_local_env(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "env"
            path.write_text("invalid assignment\n")
            self.assertNotEqual(load_profile("local", {"DJANGO_ENV_FILE": str(path)}).returncode, 0)
            self.assertEqual(load_profile("test", {"DJANGO_ENV_FILE": str(path)}).returncode, 0)
            values = production_env()
            values["DJANGO_ENV_FILE"] = str(path)
            self.assertEqual(load_profile("production", values).returncode, 0)

    def test_production_supports_mounted_secret_files(self):
        with tempfile.TemporaryDirectory() as temp:
            values = production_env()
            for name in ("DJANGO_SECRET_KEY", "DB_PASSWORD"):
                path = Path(temp) / name.lower()
                path.write_text(values.pop(name) + "\n")
                values[name + "_FILE"] = str(path)
            self.assertEqual(load_profile("production", values).returncode, 0)
    def test_local_and_test_load_without_database_or_env_file(self):
        with tempfile.TemporaryDirectory() as temp:
            for profile in ("local", "test"):
                with self.subTest(profile=profile):
                    result = load_profile(profile, {"DJANGO_ENV_FILE": str(Path(temp) / "absent")})
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_production_requires_each_value(self):
        for name in production_env():
            with self.subTest(name=name):
                values = production_env()
                del values[name]
                result = load_profile("production", values)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(name, result.stderr)
                for secret_name in ("DJANGO_SECRET_KEY", "DB_PASSWORD"):
                    if secret_name in values:
                        self.assertNotIn(values[secret_name], result.stderr)

    def test_production_secure_flags_and_existing_auth_model(self):
        code = """import django,json; django.setup()
from django.conf import settings
print(json.dumps([settings.DEBUG, settings.SESSION_COOKIE_SECURE, settings.CSRF_COOKIE_SECURE,
settings.SECURE_SSL_REDIRECT, settings.SECURE_PROXY_SSL_HEADER, settings.AUTH_USER_MODEL,
settings.DATABASES['default']['ENGINE']]))"""
        result = load_profile("production", production_env(), code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [False, True, True, True, None, "auth.User", "django.db.backends.postgresql"])

    def test_production_rejects_insecure_or_malformed_values(self):
        cases = [("DJANGO_DEBUG", "true"), ("DJANGO_DEBUG", "yes"), ("DJANGO_SECRET_KEY", "replace-me"),
                 ("DJANGO_ALLOWED_HOSTS", "*"), ("DJANGO_ALLOWED_HOSTS", "https://example.test"),
                 ("DJANGO_CSRF_TRUSTED_ORIGINS", "http://preview.example.test"),
                 ("DJANGO_CSRF_TRUSTED_ORIGINS", "https://unrelated.example.test"),
                 ("DB_PORT", "not-a-port"), ("DB_PORT", "0")]
        for name, value in cases:
            with self.subTest(name=name, value=value):
                config = production_env()
                config[name] = value
                self.assertNotEqual(load_profile("production", config).returncode, 0)

    def test_proxy_trust_requires_explicit_configuration(self):
        values = production_env()
        values["DJANGO_TRUST_PROXY_HEADERS"] = "true"
        code = """import django; django.setup()
from django.test import RequestFactory
print(RequestFactory().get('/', HTTP_X_FORWARDED_PROTO='https').is_secure())"""
        self.assertEqual(load_profile("production", values, code).stdout.strip(), "True")
        del values["DJANGO_TRUST_PROXY_HEADERS"]
        self.assertEqual(load_profile("production", values, code).stdout.strip(), "False")

    def test_secret_file_and_conflicting_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "value"
            value = secrets.token_urlsafe(40)
            path.write_text(value + "\n")
            with patch.dict(os.environ, {"CHECK_SECRET_FILE": str(path)}, clear=True):
                self.assertEqual(env("CHECK_SECRET", required=True, secret=True), value)
                os.environ["CHECK_SECRET"] = value
                with self.assertRaises(ImproperlyConfigured):
                    env("CHECK_SECRET", secret=True)

    def test_unreadable_secret_file_has_safe_error(self):
        with patch.dict(os.environ, {"CHECK_SECRET_FILE": "/absent/private/location"}, clear=True):
            with self.assertRaisesMessage(ImproperlyConfigured, "Cannot read CHECK_SECRET_FILE"):
                env("CHECK_SECRET", required=True)

    def test_dotenv_is_not_shell_and_environment_takes_precedence(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "env"
            path.write_text('EXISTING=file\nLITERAL="$(echo should-not-run)"\nNAME="Εταιρεία # ένα"\n')
            with patch.dict(os.environ, {"EXISTING": "process"}, clear=True):
                load_local_env(path)
                self.assertEqual(os.environ["EXISTING"], "process")
                self.assertEqual(os.environ["LITERAL"], "$(echo should-not-run)")
                self.assertEqual(os.environ["NAME"], "Εταιρεία # ένα")

    def test_dotenv_rejects_duplicate_and_invalid_assignments(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "env"
            for value in ("A=one\nA=two\n", "export A=one\n", "A='unterminated\n"):
                path.write_text(value)
                with self.assertRaises(ImproperlyConfigured):
                    load_local_env(path)

    def test_local_generator_does_not_overwrite_and_uses_private_mode(self):
        from tools.init_local_env import create_local_env
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "env"
            create_local_env(path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            content = path.read_bytes()
            with self.assertRaises(FileExistsError):
                create_local_env(path)
            self.assertEqual(path.read_bytes(), content)


class LocaleTests(SimpleTestCase):
    def test_greek_utf8_and_afm_round_trip(self):
        original = {"name": "Γεώργιος – Εταιρεία Ωμέγα", "afm": "012345678"}
        self.assertEqual(json.loads(json.dumps(original, ensure_ascii=False).encode("utf-8").decode("utf-8")), original)
        self.assertEqual(EntityForm().fields["vat_number"].clean(original["afm"]), original["afm"])

    def test_decimal_greek_round_trip(self):
        for text, expected in [("1.234,56", "1234.56"), ("1234,56", "1234.56"), ("0,10", "0.10"),
                               ("-12,34", "-12.34"), ("1.234", "1234.00"), ("0", "0")]:
            with self.subTest(text=text):
                amount = parse_euro(text)
                self.assertEqual(amount, Decimal(expected))
                self.assertEqual(parse_euro(format_euro(amount, symbol=False)), amount)
        self.assertEqual(format_euro(Decimal("1234.56")), "1.234,56 €")

    def test_reject_ambiguous_or_overprecise_money(self):
        for value in ("12.34", "1,234.56", "1.23,45", "1,234", "NaN", "Infinity", "1e3", 1.25, True, "9" * 65):
            with self.subTest(value=str(value)[:20]):
                with self.assertRaises(ValidationError):
                    parse_euro(value)
        with self.assertRaises(ValidationError):
            format_euro(Decimal("1.234"))
        with self.assertRaises(TypeError):
            format_euro(1.25)

    def test_money_form_uses_decimal_text_control(self):
        field = GreekMoneyField(max_digits=12, decimal_places=2)
        self.assertEqual(field.clean("1.234,56"), Decimal("1234.56"))
        self.assertEqual(field.prepare_value(Decimal("1234.56")), "1.234,56")
        self.assertEqual(field.widget.input_type, "text")
        with self.assertRaises(ValidationError):
            field.clean("1234567890123,00")

    def test_spring_dst_gap_and_transition(self):
        with self.assertRaises(ValidationError) as raised:
            athens_to_utc(datetime(2026, 3, 29, 3, 30))
        self.assertEqual(raised.exception.code, "nonexistent_time")
        self.assertEqual(datetime(2026, 3, 29, 0, 59, tzinfo=timezone.utc).astimezone(ATHENS).strftime("%H:%M"), "02:59")
        self.assertEqual(datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc).astimezone(ATHENS).strftime("%H:%M"), "04:00")

    def test_autumn_dst_fold_is_explicit_and_round_trips(self):
        local = datetime(2026, 10, 25, 3, 30)
        with self.assertRaises(ValidationError) as raised:
            athens_to_utc(local)
        self.assertEqual(raised.exception.code, "ambiguous_time")
        first, second = (athens_to_utc(local, fold=fold) for fold in (0, 1))
        self.assertEqual((second - first).total_seconds(), 3600)
        for fold, instant in enumerate((first, second)):
            self.assertEqual(instant.astimezone(ATHENS).replace(tzinfo=None), local)
            self.assertEqual(instant.astimezone(ATHENS).fold, fold)

    def test_date_display_uses_athens_and_day_month_year(self):
        self.assertEqual(greek_date(date(2026, 11, 7)), "07/11/2026")
        self.assertEqual(greek_date(datetime(2026, 11, 6, 23, 0, tzinfo=timezone.utc)), "07/11/2026")
        with self.assertRaises(ValueError):
            greek_date(datetime(2026, 11, 7))
        self.assertEqual(formats.date_format(date(2026, 11, 7)), "07/11/2026")

    def test_html_date_value_remains_iso(self):
        field = AgreementForm().fields["start_date"]
        self.assertIn('value="2026-11-07"', str(field.widget.render("start_date", date(2026, 11, 7))))
        self.assertEqual(field.clean("07/11/2026"), date(2026, 11, 7))
        self.assertEqual(field.clean("2026-11-07"), date(2026, 11, 7))


class RedactionTests(SimpleTestCase):
    def test_registered_and_encoded_secret_removed_from_logs_and_tracebacks(self):
        from urllib.parse import quote
        value = secrets.token_urlsafe(32) + "+/="
        register_secret(value)
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        handler.setFormatter(RedactingFormatter("%(message)s"))
        logger = logging.Logger("s04-check")
        logger.addHandler(handler)
        logger.warning("Value %s; encoded %s", value, quote(value, safe=""))
        try:
            raise ValueError(value)
        except ValueError:
            logger.exception("Failure")
        self.assertNotIn(value, output.getvalue())
        self.assertNotIn(quote(value, safe=""), output.getvalue())
        self.assertIn("[REDACTED]", output.getvalue())

    def test_common_unknown_credential_syntax_redacted(self):
        value = secrets.token_urlsafe(32)
        examples = ["password=" + value, '"api_token": "' + value + '"', "Authorization: Bearer " + value,
                    "Cookie: sessionid=" + value + "; csrftoken=" + value,
                    "https://user:" + value + "@example.test/", '"Authorization": "' + value + '"']
        for line in examples:
            with self.subTest(line_type=line.split(':')[0][:15]):
                self.assertNotIn(value, redact_text(line))

    def test_exception_report_masks_post_and_settings(self):
        value = secrets.token_urlsafe(32)
        request = RequestFactory().post("/", {"password": value, "name": "Εταιρεία"})
        filter_ = RedactingExceptionReporterFilter()
        self.assertNotIn(value, str(filter_.get_post_parameters(request)))
        self.assertNotIn(value, str(filter_.cleanse_setting("DATABASES", {"PASSWORD": value})))


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden -= 1

    def handle_data(self, text):
        if not self.hidden:
            self.parts.append(text)


class FrontendTests(SimpleTestCase):
    def test_admin_choice_translation_preserves_codes_and_blank_option(self):
        from django.contrib import admin
        from accounting.admin import AgreementAdmin
        from accounting.models import Agreement
        field = Agreement._meta.get_field("agreement_type")
        original_codes = [code for code, label in field.formfield().choices]
        admin_field = AgreementAdmin(Agreement, admin.site).formfield_for_dbfield(field, RequestFactory().get("/"))
        self.assertEqual([code for code, label in admin_field.choices], original_codes)
        self.assertEqual(dict(admin_field.choices)["RECEIVABLE"], "Εισπρακτέα από πελάτη")

    @override_settings(ROOT_URLCONF="core.tests.urls")
    def test_server_error_page_does_not_expose_exception(self):
        response = Client(raise_request_exception=False).get("/s04-failure/", HTTP_ACCEPT_LANGUAGE="en")
        self.assertContains(response, "Προσωρινό πρόβλημα", status_code=500)
        self.assertNotContains(response, "Internal S04 fixture failure", status_code=500)

    def test_english_browser_and_cookie_still_receive_greek_login(self):
        client = Client()
        client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"
        response = client.get("/login/", HTTP_ACCEPT_LANGUAGE="en-US,en;q=0.9")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Language"], "el")
        self.assertContains(response, '<html lang="el">')
        self.assertContains(response, "Όνομα χρήστη")
        self.assertNotContains(response, ">Login<")

    def test_greek_builtin_validation_and_project_catalog(self):
        with translation.override("el"):
            self.assertEqual(translation.gettext("Active"), "Ενεργή")
            with self.assertRaises(ValidationError) as raised:
                forms.CharField().clean("")
            self.assertNotIn("required", str(raised.exception))
            for form in (ExpenseForm(), IncomeForm(), TransferForm(), AgreementForm(), EntityForm()):
                for field in form.fields.values():
                    self.assertNotRegex(str(field.label), r"[A-Za-z]{3,}")

    def test_csrf_and_not_found_are_greek_and_do_not_echo_input(self):
        response = Client(enforce_csrf_checks=True).post("/login/", {"username": "δοκιμή"}, HTTP_ACCEPT_LANGUAGE="en")
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Η ενέργεια δεν επιτρέπεται", status_code=403)
        response = self.client.get("/nonexistent-s04/", HTTP_ACCEPT_LANGUAGE="en")
        self.assertContains(response, "Η σελίδα δεν βρέθηκε", status_code=404)

    def test_all_staff_templates_render_greek_without_database(self):
        entity = Entity(pk=1, name="Εταιρεία Ωμέγα", vat_number="012345678", entity_type="CUSTOMER", phone_number="", email="")
        agreement = SimpleNamespace(pk=1, entity=entity, description="Υπηρεσίες", total_amount=Decimal("1234.56"),
            remaining_balance=Decimal("234.56"), start_date=date(2026, 11, 7), status="ACTIVE", agreement_type="RECEIVABLE",
            get_status_display=lambda: "Active", get_agreement_type_display=lambda: "Receivable (from Customer)")
        account = SimpleNamespace(pk=1, name="Ταμείο", current_balance=Decimal("1234.56"))
        tx = SimpleNamespace(transaction_date=date(2026, 11, 7), description="Είσπραξη", cash_account="Ταμείο", category="Υπηρεσίες", entity=entity, amount=Decimal("1234.56"), transaction_type="INCOME")
        user = SimpleNamespace(is_authenticated=True, username="λογιστής")
        context = {"entity": entity, "agreement": agreement, "agreements": [agreement], "transactions": [tx],
                   "standalone_transactions": [tx],
                   "customers": [entity], "suppliers": [entity], "cash_accounts": [account], "all_cash_accounts": [account],
                   "all_entities": [entity], "all_categories": [], "user": user}
        context["income_by_category"] = [{"category__name": "Υπηρεσίες", "total_amount": Decimal("1234.56")}]
        context["expense_by_category"] = [{"category__name": "", "total_amount": Decimal("1234.56")}]
        for name in ("total_income", "total_expense", "net_for_period", "accounts_receivable", "accounts_payable", "remaining_balance", "total_payments", "standalone_balance"):
            context[name] = Decimal("1234.56")
        for path in (ROOT / "accounting/templates/accounting").glob("*.html"):
            with self.subTest(template=path.name), translation.override("el"):
                form_type = (TransferForm if "transfer" in path.name else AgreementForm if "agreement" in path.name
                             else EntityForm if "entity" in path.name else ExpenseForm if "expense" in path.name else IncomeForm)
                form = form_type()
                for field in form.fields.values():
                    if isinstance(field, forms.ModelChoiceField):
                        field.queryset = field.queryset.none()
                rendered = render_to_string("accounting/" + path.name, {**context, "form": form})
                parser = VisibleText()
                parser.feed(rendered)
                self.assertNotRegex(" ".join(parser.parts), r"[A-Za-z]{3,}")
