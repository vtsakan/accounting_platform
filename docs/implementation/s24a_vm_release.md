# S24A — VM Material UI release and GitHub update

The operator's local demo is now through 0020, with all 27 original tables,
accounts and MFA retained. The existing VM is already S24/0020, so this release
has **no database migration**. It changes web image and Caddy static directory
on the same active database, retaining pinned secrets, certificates and IAM.

The new release helpers and 15 stdlib guard tests are **Prepared**. No agent
tests/builds/Docker/SSH/GCP/GitHub push were executed. The completed operator
661-test/36-financial-case production proof remains unchanged. Its actual
application commit/image is reused; newer operator/document commits get a
separate deployment identity. No repeat production build/suite is needed.

## Operator sequence

Extract accounting-platform-S24A-VM.zip and run UPDATE_GITHUB_AND_VM.sh on the
laptop. It applies the Git-only patch, runs the new small guard suite, pushes
step/s24a-material-ui, publishes the existing verified image and deploys it.
After successful restore/public checks it commits and pushes only the five
generated public evidence files. It never rewrites main or completion tags.

The independent recovery copy defaults to
~/.config/totalaccounting/recovered-backup-age.key, outside Git, owner-only mode
600. Reuse the already recovered S10/S24 copy. If its path differs, set
ACCOUNTING_RECOVERY_IDENTITY to that existing absolute path before running the
batch. Do not generate, move or replace either existing identity.

Individual commands after the Git-only apply:

```bash
cd ~/accountant_cloud/accounting_v5/accounting-platform
export PATH="$HOME/.local/bin:$PATH"
PYTHONPATH=tools python3 -m unittest discover -s tools -p test_vm_material_release.py
git push -u origin step/s24a-material-ui
python3 tools/vm_material_release.py publish
python3 tools/vm_material_release.py deploy \
  --identity "$HOME/.config/totalaccounting/recovered-backup-age.key"
python3 tools/vm_material_release.py status
```

Publication reuses private/s24a-delivery.json and its original local production
image. It never calls image.build or verify_delivery.py. If that image was
pruned, stop and inspect availability rather than substitute an unverified
rebuild. OAuth material is confined to a temporary Docker configuration.

## Deployment behavior

The only target is accounting-514109/accounting-preview, europe-west1-b,
totalaccounting.duckdns.org. The host checks VM/disk identity, current source and
S10 backup binding, immutable image metadata, twenty unchanged migration files,
unchanged infrastructure, and actual running web database/secret binding. The
non-root secure production settings and private application/database ports stay
in place. No DuckDNS, secret-version, database-role or machine change is needed.

Image pull/static export happen while the old site is available. Both static
roots retain the old/new generations of hashed files, preserving cached pages
and rollback links without replacing manifests. Before switching web, a reboot
hold is installed, S10 timers pause and active jobs finish. Only web/Caddy stop.
Expect a brief maintenance window including the small off-VM restore rehearsal.

The source snapshot is collected after requests are quiesced, so ordinary use
before deployment cannot invalidate an old plan. Fresh encrypted GCS backups
are made before switching and with the new image binding afterwards. All public
table rows, including password/MFA/session/financial rows, must match before
public activation. The same PG container/start time and runtime signing/database
bytes must remain. No bootstrap, migrate, database clone, SQL repair or data
import is performed on the VM.

S10 retains its existing proven code/units/code_commit; only its preview metadata
changes. The exact new backup generation is restored to an isolated local PG17
container using the independent key copy, then every table fingerprint matches.
The VM is never a recovery target. Caddy then uses its existing certificate data
and domain. Public checks verify Greek Material login, trusted HTTPS, CSRF origins
and exact CSS/JS/mark bytes from the immutable image. S10 monitoring resumes.

## Interrupted attempt

```bash
python3 tools/vm_material_release.py status
python3 tools/vm_material_release.py resume \
  --identity "$HOME/.config/totalaccounting/recovered-backup-age.key"
```

Resume is for an S24A attempt awaiting restore/public checks. Preparation or
restore failure attempts an image-only rollback for availability. If status is
ui-rollback after fixing the cause, archive only that attempt journal and retry:

```bash
python3 tools/vm_material_release.py retry
python3 tools/vm_material_release.py deploy \
  --identity "$HOME/.config/totalaccounting/recovered-backup-age.key"
```

Explicit image rollback, including after public activation:

```bash
python3 tools/vm_material_release.py rollback
```

Rollback retains the **same current database**, including subsequent public
writes. It does not restore/rewind data, delete images or remove backups. If
rollback fails, retain the journal/hold and inspect the safe stage/reason. Do
not delete journals or run historical preview.py ship/demo_release.py/
vm_upgrade.py installers for this S24A release.

## Results and GitHub

Private files: private/vm-s24a-release.json, private/vm-s24a-restore.json,
private/vm-s24a-result.json; host journal:
/etc/accounting/s24a-ui-release-state.json. Keep them out of GitHub.

Only after successful deployment/restore/public checks, the tool updates:

- docs/implementation/evidence/S24A-VM-verification.json
- docs/implementation/state.md
- docs/implementation/steps.csv
- docs/implementation/traceability.csv
- docs/security/secret_scan_allowlist.csv

The last file adds only exact, validated public Git/image provenance hashes,
never credentials or broad exemptions. The batch commits/pushes these five
files. Browser login/MFA, responsive/dark-theme/client review and full S47/
requirement acceptance remain Pending. S25 is separate.
