import json
import os
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounting.legacy_membership import fingerprint, load_mapping
from accounting.legacy_ownership import backfill, template


class Command(BaseCommand):
    help = "Export an explicit business-record ownership review template, or validate/apply a complete reviewed mapping. Default: dry run."

    def add_arguments(self, parser):
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument("--export-template", type=Path)
        source.add_argument("--mapping", type=Path)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--expected-sha256", help="Exact mapping digest printed by the reviewed dry run; required to apply")

    def handle(self, *args, **options):
        try:
            if options["export_template"]:
                if options["apply"] or options["expected_sha256"]:
                    raise CommandError("Template export cannot apply a mapping.")
                path = options["export_template"]
                root = Path(settings.BASE_DIR).resolve()
                resolved = path.resolve()
                if resolved.is_relative_to(root) and not resolved.is_relative_to(root / "private"):
                    raise CommandError("Keep reviewed ownership mappings in ignored private/ or outside the repository.")
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with open(path, "x", opener=lambda name, flags: os.open(name, flags, 0o600)) as output:
                    output.write(json.dumps(template(), ensure_ascii=False, indent=2) + "\n")
                result = {"status": "Exported for review", "database_changed": False}
            else:
                document = load_mapping(options["mapping"])
                if options["apply"] and options["expected_sha256"] != fingerprint(document):
                    raise CommandError("Apply requires the exact mapping SHA-256 from the reviewed dry run.")
                result = backfill(document, apply=options["apply"])
        except ValidationError as error:
            raise CommandError(" ".join(error.messages)) from None
        except (OSError, ValueError):
            raise CommandError("Cannot read/write the mapping file; inspect its path and format locally.") from None
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
