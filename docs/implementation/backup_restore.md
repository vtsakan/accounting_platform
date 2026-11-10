# S10 — encrypted backup, recovery and operating checks

Status: **Prepared** until the operator gate below passes on the selected resources.
Base: pushed `s09-complete`, commit `eced8ea70e26f410ce2d234e41169d3fc05f529b`.
S09 public HTTPS and actual reboot are Verified in the unchanged S09 evidence.
S10 introduces no application accounts. Regular office/accountant onboarding
remains S11–S14; the user elected to wait for that workflow.

## Scope and recovery objectives

Reuse `accounting-514109/accounting-preview` in `europe-west1-b`, the retained
`/srv/accounting` disk and private EU bucket `accounting-514109-backups`.
The tested application image and its context digest remain unchanged. There is
no database migration, application rebuild, Caddy/Docker restart or extra VM.

Backups run at 02:15 and 14:15 UTC with up to 30 seconds of jitter. An initial
timer trigger runs 30–60 seconds after installation. PostgreSQL 17 exports one
read-only repeatable-read snapshot. Table fingerprints and `pg_dump --snapshot`
use that same snapshot, so concurrent committed writes cannot produce a false
restore comparison. Dump/archive work is bounded to a 256-MiB custom dump;
plaintext stays on tmpfs and is removed on success and failure. Review capacity
before increasing this synthetic-preview limit.

The proposed RPO is 24 hours and RTO eight hours. This step measures one synthetic
recovery and verifies the schedule, backup age, failure detection and alert path.
It does **not** accept those objectives for an unknown production dataset or
approve an availability SLA. All 85 full requirement acceptances remain Pending.

The current private media directory must be empty. The backup refuses nonempty
media instead of omitting files silently. S38 must add document/object recovery,
consistency rules and a restoration demonstration before document use.

## Encryption and authority

The reviewed operator tool is age 1.3.2, Linux amd64, pinned by the official asset
SHA-256 in `infrastructure/operations/age-pin.json`. `tools/install_age.py` validates
the checksum and extracts only age and age-keygen. Application dependency locks
and the production image are unaffected.

Generate the decryption identity on the laptop, outside Git, and retain an
independent recovery copy in a password manager or offline storage. Only its
public X25519 recipient is copied to the VM. The VM cannot decrypt backups and
retains its bucket-level `roles/storage.objectCreator` permission. Operator Google
authentication downloads backups on the laptop; no service-account JSON key is
created. Recovery uses the independently retrieved identity file, with the primary
identity unavailable if necessary. Keep the laptop's ignored `private/operations.json`
and a recovery copy of the resource configuration under independent operator control.

Each complete backup consists of:

- `s10/v1/<UTC>-<random>.tar.age`: encrypted database.dump, manifest.json and
  recovery.json. The manifest includes snapshot time, source image/deployment,
  checksums and every public table's count/content fingerprint. Recovery
  configuration includes pinned Secret Manager version references, not payloads.
- A matching `.receipt.json`: routing/integrity metadata only, in the same private
  bucket. It contains no table rows, key material, passwords, operator names or
  email addresses. Recovery can discover this receipt while the original VM is
  unavailable. A ciphertext without its completed receipt is ignored.

Uploads use `ifGenerationMatch=0`, unique names and checked size/CRC32C responses.
Laptops download an exact object generation and verify SHA-256 and CRC32C before
age authentication/decryption. Tampering or a wrong key stops recovery.
An uncertain upload is reported as a failed attempt; the last confirmed success
is preserved. The VM never lists, reads, overwrites or deletes backup objects.

Setup requires an explicit preview retention choice, 7–90 days (suggested 30).
The lifecycle deletion rule applies only to live objects under `s10/v1/`.
Objects become eligible after that age; deletion is asynchronous and existing
seven-day soft deletion is additional. This is a preview cleanup policy, not an
immutable retention lock, financial record policy or legal retention decision.
Unknown existing lifecycle rules are rejected for review instead of overwritten.

## 1. Apply and push on the laptop

Extract the delivered patch into Downloads, then:

```bash
cd ~/accountant_cloud/accounting_v5/accounting-platform
git fetch origin --tags
git switch -c step/s10-backup-restore s09-complete
git am --keep-cr ~/Downloads/accounting-platform-S10.patch
python3 tools/verify_s10.py
git push -u origin step/s10-backup-restore
```

Use the clean committed checkout for installation. Offline `--record` changes
tracked evidence, so do not use it between the patch commit and installation.
The final live verification records evidence after the source has been installed.

## 2. Configure keys, named operators and the preview policy

Install the checksum-pinned encryption tool on your Linux amd64 laptop:

```bash
python3 tools/install_age.py
export PATH="$HOME/.local/bin:$PATH"
python3 tools/operations.py configure
```

The primary identity defaults to `~/.config/totalaccounting/backup-age.key`, mode
0600. Key generation reserves its path exclusively and never replaces an existing
key. Before confirming custody, save its contents or file to independent protected
storage. Do not paste key contents into chat. Setup retains the primary if stopped;
rerunning configure reuses it. A separate recovery copy must later be retrieved to
a different private file outside the repository for the restore command.

The wizard records the incident owner, restore owner, key custodian, alert email,
synthetic retention choice and confirmation time in ignored mode-0600 configuration.
These are explicit operator inputs. Current project/DNS/secret-version references
come from S08/S09. No DuckDNS token, SMTP password or app account is requested.

Review the exact resource plan locally, then apply it:

```bash
python3 tools/operations.py cloud-plan
python3 tools/operations.py cloud
python3 tools/operations.py install
```

`cloud-plan` writes `private/s10-cloud-plan.json`; it changes no cloud resource.
`cloud` enables Monitoring, adds only `roles/monitoring.metricWriter` for the
selected VM identity at project level, configures the scoped lifecycle and creates
one email channel, eight numeric metric descriptors, one external HTTPS readiness
check and nine alert policies. The existing backup bucket IAM is retained.
Replays reuse exact matching resources; conflicting/duplicate definitions stop.
Complete any notification-channel verification requested by Google Cloud.

`install` transfers a committed source archive through IAP, validates the VM,
mounted UUID and active S09 configuration, installs the pinned age binary on the
VM, and installs only the operations wrapper and two systemd timers. It does not
change the active app release or its database. A separate operations source commit
is recorded; the original app and S09 deployment revisions are retained.

## 3. Observe the initial scheduled backup

After the first timer run (normally within a minute), inspect:

```bash
python3 tools/operations.py status
python3 tools/operations.py latest
```

Require a successful backup receipt, a successful inactive backup service, enabled/
active timers and `scheduled_backup_trigger_observed: true`. `latest` independently
finds a complete receipt in Cloud Storage and saves `private/s10-backup-receipt.json`.
Status also verifies effective VM create-only permissions and actual denied
read/list operations. Stale/missing backup age and a failed last attempt are separate
measurements; a failed attempt never resets the age of the last confirmed backup.

To run the same systemd backup service on demand:

```bash
python3 tools/operations.py backup
python3 tools/operations.py monitor
```

If a timer/service fails, inspect bounded diagnostics on the VM:

```bash
sudo systemctl status accounting-backup.timer accounting-backup.service --no-pager
sudo journalctl --namespace=accounting-ops -u accounting-backup.service -n 60 --no-pager
sudo /usr/local/sbin/accounting-operations status
```

Do not enable SDK HTTP tracing or print environment/secret/key files. Diagnostics
relay the stage, exception type and HTTP status; provider bodies and credentials
are omitted. Operator logs have a separate journal namespace capped at 16 MiB with
14-day retention. Existing application/container log rotation is unchanged.

## 4. Restore off the VM using the recovered key copy

Retrieve the separately stored identity into a different private laptop file,
for example `~/.config/totalaccounting/recovered-backup-age.key`, and set mode 0600.
Use your normal local Docker Engine and Google operator session:

```bash
python3 tools/operations.py restore \
  --identity ~/.config/totalaccounting/recovered-backup-age.key
```

The command discovers/downloads the newest complete receipt using laptop auth;
it needs no SSH connection to the source VM. To restore an explicitly saved receipt:

```bash
python3 tools/operations.py restore \
  --identity ~/.config/totalaccounting/recovered-backup-age.key \
  --receipt private/s10-backup-receipt.json
```

Recovery starts a randomly named digest-pinned PostgreSQL 17 container on the
laptop. It has no network, published ports, host data binds or persistent volume;
PGDATA uses tmpfs. Linux `/dev/shm` must also have at least 529 MiB plus the
encrypted file size free for the bounded recovery workspace. The actual encrypted
payload and all public table fingerprints are checked. The container and plaintext
are removed afterwards. `private/s10-restore.json` records scope, elapsed time,
snapshot age, source generation and results; it contains no decryption key.

An older backup can be restored for disaster recovery, but a backup older than
24 hours cannot complete the S10 freshness gate. Recovery testing never replaces
the preview database and never creates a human application account.

## 5. Verify external observation and notification delivery

The host publishes readiness, certificate lifetime, worst root/data disk usage,
available-memory-derived usage, backup age, last attempt, heartbeat and a bounded
alert-test metric every five minutes. Policies observe backups older than 20 hours,
failed attempts, disk above 80%, memory above 85%, certificate lifetime below 14
days, failed readiness, missing telemetry for 15 minutes and failed public HTTPS.
The external check and metric-absence policy continue independently of the VM.
Queue monitoring is deferred until the worker/scheduler at S26.

Request one explicit notification test at the destination you configured:

```bash
python3 tools/operations.py alert-test
```

This emits a test value for at most 15 minutes without stopping the app or breaking
a backup. Wait for its email (subject/policy: `Λογιστική — δοκιμή ειδοποίησης S10`).
Google metric ingestion and policy evaluation can take several minutes. Configure
channel verification or inspect Monitoring if the expected message does not arrive.
After actually receiving it:

```bash
python3 tools/verify_s10.py --live --confirm-alert-received --record
```

The live gate requires an actual timer trigger, successful uploaded backup, VM
permission denials, fresh host observations, active matching cloud policies,
ingested heartbeat/test values, a passing external uptime sample, trusted public
TLS and a complete off-VM Docker restore using the recovered key copy. The flag
records the operator's observed email receipt; configuration alone cannot prove it.
Only the complete gate reports **Verified** and makes S11 eligible. If ingestion
is pending, rerun after it arrives; do not change evidence to bypass a gate.

Then record this milestone:

```bash
git add docs/implementation
git commit -m "docs: record S10 scheduled backup restore and alert verification"
git push
git tag -a s10-complete -m "S10 encrypted backup isolated restore and operating checks verified"
git push origin s10-complete
```

## Incident and release procedure

The configured incident owner checks the alert and readiness first, then service
state, mounted UUID, disk/memory and backup age. The restore owner selects a
known complete backup; the key custodian retrieves the independent identity.
Keep existing data/disks while investigating. A full source-VM outage cannot be
repaired by an on-host process: use the external alert and laptop recovery path.

For a lost VM, prove the download/decrypt/isolated restore first. Rebuild only an
explicitly selected recovery environment using the S08/S09 runbooks. Restore the
restricted application DB role and pinned Secret Manager material through the
authorised custodian; SQL dumps do not include cluster login roles/passwords.
The encrypted recovery configuration records resource and version references.
If original signing/database secrets are unavailable, establish reviewed new
versions and reconfigure the app; do not silently substitute them. Caddy can
reissue a certificate after controlled DNS cutover. Off-VM document and full
host-replacement rehearsals remain future gates; this command is a database drill.

Before a future application release, take a fresh backup and complete an isolated
restore for its dataset. Record the app image, explicit migration plan and rollback
decision. Coordinate an operations configuration update with any changed active
release: S10 deliberately refuses a different S09 configuration. An old operations
binding is not silently applied to a new deployment. A database migration rollback
must be reviewed; restoring data requires a selected maintenance/recovery target,
not an automatic startup action. Keep the last working release and backups.

## Evidence and official references

`evidence/S10-verification.json` separates local safeguard/native proof from live
execution. Local native proof restored all 16 public tables, including Greek text
and exact decimals, after a concurrent source write. It rejected wrong keys,
altered ciphertext, changed recovered rows and oversized dumps, and verified
snapshot transactions and plaintext cleanup. It used PostgreSQL 17.11 and the
verified age 1.3.2 release. It does not claim GCS, Docker, timer or email execution.

- https://www.postgresql.org/docs/17/app-pgdump.html
- https://www.postgresql.org/docs/17/app-pgrestore.html
- https://github.com/FiloSottile/age/releases/tag/v1.3.2
- https://github.com/FiloSottile/age/blob/main/README.md
- https://docs.cloud.google.com/storage/docs/json_api/v1/objects/insert
- https://docs.cloud.google.com/storage/docs/request-preconditions
- https://docs.cloud.google.com/storage/docs/lifecycle
- https://docs.cloud.google.com/monitoring/uptime-checks
- https://docs.cloud.google.com/monitoring/api/ref_v3/rest/v3/projects.timeSeries/create
- https://docs.cloud.google.com/monitoring/alerts/policies-in-json
