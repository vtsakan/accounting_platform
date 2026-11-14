# S09 — totalaccounting DuckDNS HTTPS preview

Status: **Prepared** until the public checks and actual reboot check pass. Selected
hostname: `totalaccounting.duckdns.org`; reserved IPv4: `207.175.136.231`.
This is the existing `accounting-514109/accounting-preview` synthetic environment.
Do not recreate the VM, reformat the disk or attach PostgreSQL 15 data.

## 1. Register the hostname

Sign in at [DuckDNS](https://www.duckdns.org/), add `totalaccounting`, set its current
IPv4 to `207.175.136.231`, and leave IPv6 empty. DuckDNS confirms availability and
control; an NXDOMAIN response alone does not. Clear an old IPv6 record if present.
The laptop DNS gate requires exactly that A record and no AAAA record. A public DNS check on 09/11/2026 matched this A record with no AAAA; DuckDNS account ownership/control has not been independently observed.

A manually configured static address needs no DuckDNS updater or token. Caddy uses
its normal HTTP/TLS certificate challenges on ports 80/443 and renews automatically.
Keep the DuckDNS account token in your password manager; never paste it into chat,
Django settings, Git, command arguments or logs. No DNS challenge plugin is needed.

## 2. Apply, inspect and push the prepared implementation (laptop)

Use the pushed S08 branch as the base; do not start from main/S07.

```bash
cd ~/accountant_cloud/accounting_v5/accounting-platform
git fetch origin
git switch -c step/s09-https-duckdns origin/step/s08-google-cloud
git am --keep-cr ~/Downloads/accounting-platform-S09.patch
python3 tools/verify_s09.py
git push -u origin step/s09-https-duckdns
```

The offline verifier needs the existing Docker CLI/Compose plugin, without running
containers. It tests configuration/rejection safeguards and renders production
Compose. Optional `--caddy /path/to/caddy` validates with the pinned native Caddy.
This alone cannot complete S09. Keep unrelated local changes outside the release.

## 3. Configure and test the actual image (laptop)

```bash
python3 tools/preview.py configure
python3 tools/preview.py dns
python3 tools/verify_delivery.py --report private/s09-delivery.json
```

`configure` imports the actual S08 inventory, creates ignored `private/gcp.json` if
missing and prompts for a real certificate contact email. It writes mode-0600
`private/preview.json`, refuses to overwrite it, and does not retrieve secret values.
The configured Google identity must have access to the selected project, IAP/SSH
and Artifact Registry publishing. Use your existing `gcloud auth login` session.
`dns` must pass before deployment. If registration is pending, finish it in DuckDNS
and rerun this command; do not point the hostname elsewhere to bypass the gate.

`verify_delivery.py` is the current-source Docker gate. It builds from clean
committed source, verifies the same immutable image, PostgreSQL migrations,
non-root runtime, static export, health recovery and the strict financial suite.
The 26 reviewed financial failures remain expected; unrelated failures stop work.
It records its result in ignored private/s09-delivery.json and does not rewrite historical S07/S08 records. Publication refuses native-only proof or proof for a different image/commit. Do not use the historical S08
same-context verifier for S09: production MEDIA_ROOT deliberately changes the app
context. No dependency lock, model, business view or migration was changed.

## 4. Publish and deploy (laptop)

```bash
python3 tools/preview.py publish
python3 tools/preview.py ship
```

Publish uses a short-lived Google user token through Docker stdin and a temporary
credential directory. It records the full source commit, image ID, context digest
and Artifact Registry digest in private configuration. An immutable full-commit tag
must not be moved. If a previous publication of this commit already succeeded, its
content digest must match; do not delete/reassign the immutable tag to force a retry.
The VM has reader permission only and pulls that exact digest using its metadata
identity; no service-account key is exported.

Ship transfers a Git archive of the published commit, its hash and nonsensitive
private configuration via IAP to `~/accounting-s09-stage`. The root installer checks
VM identity, filesystem UUID, Docker storage root, public DNS, archive paths/types,
image labels/platform/UID and existing PostgreSQL version. Install operations lock
against concurrent installation. It rejects an unknown/non-17 data directory.
Captured command output is deliberately not reproduced when a credential-bearing
operation fails. Investigate the named stage in an administrative session; do not
enable SDK HTTP tracing or dump secret files/environment into chat.

Only Caddy publishes TCP 80/443. Gunicorn and PostgreSQL have no published ports and
use internal networks. Caddy has a separate egress network for certificate issuance.
Host metadata/API calls load pinned Secret Manager versions 1 into `/run/accounting`
on tmpfs. Files are mode 0400, individually bound read-only; only the application
UID owns the two application inputs. No plaintext password is in the Compose
environment. A host DOCKER-USER rule denies container access to VM metadata, while
host metadata requests remain available. TCP/UDP DNS on the same GCE resolver IP
is explicitly permitted ahead of that rejection so certificate lookups work.
The verifier checks both the active rules
and a real non-secret metadata request from Caddy. The default Docker iptables
backend is required; changing firewall backends is a separate reviewed operation.

The application uses `accounting_app`, without superuser/create-role/create-database/
replication/bypass-RLS capabilities. An initialization-only random PostgreSQL admin
password is disabled by explicit bootstrap. Host operators retain peer-authenticated
local administration with `sudo docker compose ... exec --user postgres db psql`.
The existing Secret Manager database credential belongs to the restricted app role.
SQL passwords use stdin and database statement logging is disabled. Startup never
imports data, creates human accounts or runs migrations; migration is an explicit
installer action. Repeated installs preserve existing data and refuse implicit
secret-version/hostname/database-identity changes.

## 5. Verify public HTTPS, then the real reboot

```bash
python3 tools/verify_s09.py --live --record
```

This checks DNS, the VM image/role/settings, certificate chain and hostname, HTTP
redirects, secure cookies, valid Greek login POST, valid-token foreign-origin denial,
missing-token denial, forwarded-header spoofing, Greek admin, exact exported static
bytes, denied direct private media and HTTPS readiness. External 5432/8000 must be
closed/filtered. A short-lived non-staff probe user is removed in a finally block;
its generated password is captured in memory only, never printed or recorded.
No real client data is used. The installer seeds explicitly named zero-value S09
synthetic records; verification only reads them and fails if they disappear.

The first passing public check saves `private/s09-before-reboot.json` and leaves
S09 Prepared. Perform a controlled reboot of this preview (brief outage expected):

```bash
gcloud compute ssh vasilistsakanikas@accounting-preview \
  --project=accounting-514109 --zone=europe-west1-b --tunnel-through-iap \
  --command='sudo reboot'
```

SSH can close with a nonzero exit during reboot. Reconnect after the VM is ready,
then run from the laptop:

```bash
python3 tools/verify_s09.py --live --after-reboot --record
```

This requires a changed VM boot ID and unchanged source image, certificate
fingerprint, synthetic record identities/values and static digest. It reruns public
login/TLS/isolation checks after boot. The baseline is never silently replaced;
a repeated pre-reboot check must match it. If a new release needs a baseline,
inspect/archive the previous private baseline explicitly before starting its check.
Only this complete gate marks S09 Verified. It records actual image references,
never a guessed commit or successful public deployment.

For an optional human administrator, connect with IAP and run the interactive
command on the VM:

```bash
sudo /usr/local/sbin/accounting-preview admin
```

Do not commit the account password. The current application still awaits S11–S16
office boundaries/MFA work; use synthetic records only.

## Persistent paths and boot behavior

| Path | Purpose |
| --- | --- |
| `/srv/accounting/postgres17` | PostgreSQL 17 cluster |
| `/srv/accounting/media` | Private app media; Caddy denies direct access |
| `/srv/accounting/caddy/data` | Certificates, keys and ACME account state |
| `/srv/accounting/caddy/config` | Caddy runtime state |
| `/srv/accounting/static/<commit>` | Same-image static export, read-only in Caddy |
| `/srv/accounting/release-config/<commit>.env` | Nonsensitive release inputs, root-only |
| `/opt/accounting/releases/<commit>` | Root-owned reviewed source bundle |
| `/etc/accounting/preview.json` | Root-only selected environment/release references |
| `/run/accounting` | Rehydrated temporary credential files; not disk-backed |

All binds disable automatic source-directory creation. Existing S08 Docker and
containerd mount guards remain. A Docker ExecStartPre loads secrets and the metadata
rule before container restart; accounting-preview.service resumes Compose after
Docker without migrations. A missing expected data UUID, secret version or existing
PGDATA stops startup. The installer changes the active boot configuration only after
successful migration/start/marker checks; a failed partial release can need explicit
operator recovery and is not an automatic database rollback. Do not rerun destructive
initialization commands to repair it. Once S10 exists, take and verify backups before
changes that can affect valuable data.

After the full gate passes, commit the updated evidence/state and push this branch.
Only then create the completion tag:

```bash
git add docs/implementation
git commit -m "docs: record S09 public HTTPS and reboot verification"
git push
git tag -a s09-complete -m "S09 HTTPS preview and reboot verified"
git push origin s09-complete
```

The image revision remains the original tested code commit even when a later
commit contains evidence. Local proof here uses Caddy 2.11.9 with an internal test
CA and native PostgreSQL 17.11; it cannot prove public ACME issuance, VM container
execution or reboot persistence. Automatic renewal is configured, not yet observed.
S10 must add encrypted off-VM backup/restore and monitoring before live data. No
availability SLA, incident-owner policy or full requirement acceptance is approved.

## Official references

- [DuckDNS specification](https://www.duckdns.org/spec.jsp)
- [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https)
- [Caddy reverse proxy headers](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#headers)
- [Caddy 2.11.9 release](https://github.com/caddyserver/caddy/releases/tag/v2.11.9)
- [Compose service secrets and file ownership](https://docs.docker.com/reference/compose-file/services/#secrets)
- [Docker DOCKER-USER firewall rules](https://docs.docker.com/engine/network/firewall-iptables/)
- [Artifact Registry short-lived authentication](https://cloud.google.com/artifact-registry/docs/docker/authentication)
- [Secret Manager integrity verification](https://cloud.google.com/secret-manager/docs/data-integrity)

## S09 deployment retry after the first operator attempt

The operator's current-source Docker gate passed for application commit
`git:70cf0d3dbc601163f33ae9c6f927605be50841aa`: 64 passed tests, 26 exact known
failures, zero unexpected outcomes. Publication returned the immutable Artifact
Registry digest recorded in evidence/S09-deployment-retry.json. SSH, sudo, the
five staged inputs and the expected data UUID were subsequently observed. No
accounting-preview containers were listed. The hidden original installer error
has not been identified; successful transfer does not prove successful setup.

Inspection reproduced a separate definite Compose bug: unquoted commas in a YAML
flow list split web/Caddy tmpfs options into five mounts. The corrected block list
keeps each mount and its options in one string. Offline checks now reject the
previous split form, missing protection flags and relative targets. Configuration
validation alone is still not Docker container execution.

Apply accounting-platform-S09-deployment-fix.patch on the existing S09 branch,
then use this laptop sequence. No new configure/publish operation is required:

```bash
cd ~/accountant_cloud/accounting_v5/accounting-platform
git am --keep-cr ~/Downloads/accounting-platform-S09-deployment-fix.patch
python3 tools/verify_s09.py
git push
python3 tools/preview.py ship --current-tools
```

`--current-tools` selects the clean current Git commit for the deployment archive
and bootstrap helpers. It requires its application context digest to equal the
already published image context. It never changes the published image's source
revision, registry digest or image ID. The operator commit is separately recorded
as private configuration's deployment_commit. Its release directory and environment
file use that operator commit; static export remains keyed to the image commit.
Image label checks still compare with the original application commit. A changed
application context or dirty tracked checkout stops the retry. An explicit later
publication clears this operator override for the new image.

Boot uses the selected immutable operator release. Public evidence and the reboot
baseline distinguish application and operator commits; both must persist. Original
source bundles are retained, without editing an earlier release in place. Normal
retries keep existing data and pinned secret versions. PostgreSQL 15/unknown data
and unexpected cloud/database identity remain rejected.

Labeled diagnostics identify source preparation, SSH, transfer, VM checks, runtime
material reads, registry login/pull, static export, Compose configuration, database
startup/migration and boot installation. When the VM installer fails, the laptop
relays only a bounded typed record: stage, exception class, reviewed literal reason,
program/exit code, HTTP status, errno and source module/line where available. It
never forwards raw provider bodies, SQL input, command arguments, private JSON,
credential output or arbitrary stderr. Secret Manager HTTP errors retain their
status without their URL, headers, body or token. Unknown/forged diagnostic fields
are discarded. Ordinary stdout remains parseable JSON.

After ship reports Started, run `python3 tools/verify_s09.py --live --record`, then
follow the controlled reboot instructions above. The fix is Prepared pending actual
operator retry, public HTTPS/login and reboot proof. S10 and real-data acceptance
remain gated. The 26 financial defects are unchanged.

## S09 image-identity follow-up

The retry at operator commit git:8f16ea5a57c218411707c6fdcbd73626378d2063 reached
image-identity after successful pull. A read-only VM probe confirmed the expected
manifest digest, RepoDigests reference, platform, UID, app revision and context.
The containerd store reports that manifest digest as Id. It differs from the
publication receipt's laptop build ID without implying a different artifact.

Apply accounting-platform-S09-image-identity-fix.patch after the deployment fix:

```bash
git am --keep-cr ~/Downloads/accounting-platform-S09-image-identity-fix.patch
python3 tools/verify_s09.py
git push
python3 tools/preview.py ship --current-tools
```

The pinned registry digest, expected build ID and application source are preserved.
The audit accepts only those publication identities and still requires the exact
registry reference, matching optional descriptor, Linux/amd64, UID 10001:10001,
source URL, application commit and context. Unrelated IDs, changed content bindings
or labels fail closed. Runtime evidence records the build, daemon and container
IDs separately. No Docker backend migration, expected-ID overwrite, rebuild or
republish is part of this fix. A successful ship must still be followed by the
public --live check and the actual --after-reboot gate before S09 is complete.
