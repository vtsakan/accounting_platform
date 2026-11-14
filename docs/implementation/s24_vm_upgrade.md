# S24 VM update — operator commands, Prepared tooling

The operator requested commands to update GitHub and the existing VM before
S25, and supplied the installed release inventory. S24 application tests are
operator-Verified: 656/656, all 36 finance cases and 922 boundary cases. Its
application context is retained. This deployment follow-up adds operator tools
only; it does not implement S25 or execute cloud/build/database actions for the
user. The new deployment tooling remains **Prepared**, with no agent-run tests,
Docker builds, migrations, VM calls or restore execution claimed.

## Observed starting point

| Item | Operator-reported value |
| --- | --- |
| Project / VM / zone | accounting-514109 / accounting-preview / europe-west1-b |
| Existing source | S14, commit ab9602592cb699684450bc4ee70438f80d30351f |
| Application image | europe-west1-docker.pkg.dev/accounting-514109/accounting-platform/web@sha256:04f9de7016ff1b579d2b6597d8bad3257f890ba3307d4bf9edd3e2fce1168991 |
| Existing release | /opt/accounting/releases/ab9602592cb699684450bc4ee70438f80d30351f |
| Accounting schema | 0001 through 0008, all applied |
| Runtime | Existing PostgreSQL17 data disk, Caddy, reserved IPv4 and DuckDNS hostname |
| Operations | Backup and monitoring timers enabled/active; last attempt succeeded |
| Data/account inventory | Read by the operator plan; not inferred from old S09 synthetic marker counts |

Do not reuse the S09 installer or S09→S14 clone/bootstrap flow. The current VM
already has office/account/MFA data. The new flow requires this exact observed
S14 image/schema, retains the existing secret versions, role, service account,
ports, image pins, backup recipient and cloud resources, and never bootstraps a
new owner or resets a password/MFA seed. Private media must still be empty under
the existing database-only backup policy; nonempty media stops for its own
recovery scope. Existing records that violate migration guards stop for review;
no amounts, AFMs, categories, ownership or historic status are automatically
repaired. Old cash opening dates remain unknown until explicitly reviewed in
the application; this update does not approve legacy balances or import data.

## How the cutover works

1. `configure` reads the installed private release metadata over IAP and chooses
   a distinct `accounting_s24_<random>` logical database in the existing cluster.
   It writes only ignored laptop configuration. No key material is transferred.
2. The operator runs `verify_delivery.py` against the clean committed current
   source. This is the production image/strict-suite/static/secret-scan gate;
   it does not replace the prior S24 receipt or touch the retained demo.
3. `publish` uses that exact production-image receipt and pins the registry
   digest. `plan` transfers the committed source bundle, validates source/target
   identities, pulls the image, exports static bytes, checks disk capacity and
   snapshots the original public tables. It prints counts/database names/image
   and a bound plan digest; no services or database contents change in this step.
4. `deploy --identity ...` validates the independent recovery copy, recipient,
   age version and local Docker before stopping the VM services. The source data
   must still match the plan. It pauses timers and waits for running backup/
   monitor work, sets a boot hold, then stops web/proxy for a maintenance outage.
5. A fresh encrypted off-VM backup succeeds first. The original database is
   cloned; the original is never migrated, dropped or restored over. All original
   tables match immediately before clone-only migration. Migrations 0009–0020
   execute with the restricted application role, not PostgreSQL administrator
   privileges. Old columns/rows/passwords/MFA are compared before/after; only
   normal new migration/content-type/permission rows may append. No financial
   cash/charge/allocation/refund or opening-date approval is inferred.
6. The new image starts privately against the upgraded clone. Settings/readiness
   and image identity are checked. Boot and backup routing are bound to the new
   image/database together; the same public age recipient and pinned secrets
   remain. A new encrypted backup is created before public traffic returns.
7. The laptop restores that exact new backup with the independent key into an
   isolated local PostgreSQL container, compares all public tables, and removes
   plaintext/container. Only its matching receipt then activates Caddy. HTTPS,
   Greek login, same-origin/CSRF probes, private database/web ports, metadata
   firewall and monitoring are checked. Backup/monitor timers resume with the
   new binding. Existing owner browser/MFA login is a separate operator check.

The original database, image/release and pre-change backup remain available.
Before public activation, failure attempts to restart the frozen original and
its backup routing while retaining the failed clone for inspection. Once the
new target may have human writes, automatic rollback is refused; it would hide
new work. The target and its backups are retained, with status/explicit recovery
rather than reverse migrations or discarded data. A failed attempt is never
silently overwritten by another deploy. S10 create-only VM bucket permissions,
private app/database ports and the original data disk remain intact.

## Laptop commands

Apply the accompanying source patch/helper and push the current S24 branch.
Then run each phase from the repository root, stopping on an error:

```bash
export PATH="$HOME/.local/bin:$PATH"
python3 tools/vm_upgrade.py configure
python3 tools/verify_delivery.py --report private/vm-s24-delivery.json
python3 tools/vm_upgrade.py publish
python3 tools/vm_upgrade.py plan
```

Inspect the printed source/clone names, current users/offices and target image.
The next explicit command executes the stored plan, including the maintenance
outage, cloned-database migrations, independent restore and activation:

```bash
python3 tools/vm_upgrade.py deploy \
  --identity "$HOME/.config/totalaccounting/recovered-backup-age.key"
python3 tools/vm_upgrade.py status
```

No live SMTP is enabled; all code/current policy checks still use synthetic
scope. Do not rerun configure to replace an existing configuration. Do not
change application source between production verification/publication/planning;
changed application bytes need their own delivery image proof. The retry below
can separately bind new operator tooling to an unchanged verified image.
Git/source-only package
apply never runs any of the commands above.

Private receipts are written under `private/vm-s24-*.json`; never commit them,
keys, runtime files, private invitations or recovery downloads. After successful
activation, sign in at https://totalaccounting.duckdns.org/login/ using the
existing owner/password/authenticator and inspect office/client/history screens.
Technical deployment is not full product/browser acceptance or real-data release.

## Interrupted work

```bash
python3 tools/vm_upgrade.py status
```

If state is `awaiting_off_vm_restore` or `needs_public_check`, the explicit
resume action redoes the exact backup restore and activation checks:

```bash
python3 tools/vm_upgrade.py resume \
  --identity "$HOME/.config/totalaccounting/recovered-backup-age.key"
```

Before any public target exposure only, an explicit abort restores the original
application/backup routing without deleting the clone:

```bash
python3 tools/vm_upgrade.py abort
```

After an automatic/explicit rollback the source and clone are retained. Inspect
the reported phase before a separately prepared retry; the stored attempt is
not reset or overwritten. Do not force the new source through the old S14 demo
installer, edit membership maps, reverse migrations, remove volumes or bootstrap
accounts. Public-source/future S25 implementation is outside this follow-up.

## S15 identity review and retained-attempt retry

The operator's production-image run passed all 656 tests, all 36 finance cases,
static/Greek/health checks and the secret scan (zero unreviewed findings).
Publication succeeded. The first clone migration stopped at S15 because entity
`2` has `invalid_afm`. The reported final state is `rolled_back_to_original`,
`original_database_unchanged: true`, `public_cutover_started: false` and
`hold_active: false`. The S14 source site and its backup routing were restored;
the failed clone and pre-change encrypted backup were retained. This is a data
review stop, not permission to change or bypass migration 0009.

First sign into the existing S14 application and review the record at
https://totalaccounting.duckdns.org/entity/2/edit/ . A real record needs its
correct actual AFM; a purely synthetic record with no AFM may leave that optional
field blank. Save the reviewed identity through the application. Do not invent
an identifier, clear a real identifier to make deployment pass, delete the
record/history, or paste personal identity values into chat or Git. The frozen
S15 rule accepts blank or a normalized nine-digit AFM and rejects duplicates in
the same office; this syntax check does not validate a tax identity externally.

Apply the retry source patch, commit/push it, then run on the laptop:

```bash
export PATH="$HOME/.local/bin:$PATH"
python3 tools/vm_upgrade.py retry
python3 tools/vm_upgrade.py plan --current-tools
python3 tools/vm_upgrade.py deploy \
  --identity "$HOME/.config/totalaccounting/recovered-backup-age.key"
python3 tools/vm_upgrade.py status
```

Stop at an error. `retry` archives only a completed unexposed rollback journal
under `/etc/accounting/s24-upgrade-history/<previous-clone>/` and the prior
laptop configuration under ignored `private/vm-s24-attempts/`. It requires the
original S14 web/proxy/backup binding and active timers, retains the failed
database unchanged and chooses a fresh clone name. An active attempt, boot hold
or possible new public writes blocks retry. The next plan takes a new snapshot
of the source, including any identity review explicitly saved by the operator.

`plan --current-tools` validates the exact retained production receipt against
the published image and current application-context digest. It reuses the
already published image while binding the separate operator release to the
current Git commit. Do not rerun `configure`, `publish` or the 656-test delivery
gate solely for this operator-only patch. Changed application bytes or a missing/
altered delivery receipt stop reuse. No current-source runtime proof is claimed
for these new operator helpers; their first operator execution remains Pending.

Planning now reads all source identities using the frozen S15 normalizer before
stopping any service. A failure prints record IDs/reason codes only, without
names or AFM values; it leaves the original site running. Review the indicated
record(s), then rerun `plan --current-tools` (not `retry` again). The unchanged
migration still independently validates the frozen clone. A successful plan
does not relax the existing backup, clone-preservation, restricted-role migration,
independent restore or public-cutover requirements. S25 remains separate.
