# S08 — Google Cloud foundation

The user executed the preview setup on 8–9 November 2026. The mounted data disk,
Docker persistence after reboot, IAP administration, metadata credentials, private
storage access and denied-access checks are Verified from the operator output.
[Resource inventory](cloud_inventory.json) and [execution evidence](evidence/S08-verification.json)
record the actual scope. This is infrastructure verification; HTTPS deployment is
S09 and a recoverable off-VM backup is S10. Use synthetic data through the release gates.

## Selected environment

The selected project is `accounting-514109`, VM `accounting-preview`, zone
`europe-west1-b` in Belgium. The user's existing biomedical/research project is
outside this scope. The VM is a regular `e2-medium` with 4 GB RAM. Its two shared
vCPUs provide about one sustained vCPU in aggregate; it is not the original
two-full-vCPU/8-GB `e2-standard-2` candidate. Capacity remains subject to measurement.

The actual host is Ubuntu 26.04.1 LTS amd64. Docker's official Ubuntu support list
includes 26.04. The application still runs its S03/S07 pinned Python 3.12.16 image;
the host's Python 3.14 administrative runtime does not change application dependencies.
The reserved address is currently Premium tier. No Standard-tier switch was made.

## Adopt the existing setup on the laptop

Run from the accounting-platform checkout on the laptop, using the same Google
administrator account as Cloud Shell. `gcloud auth login` is for the laptop/Cloud
Shell administrator. The VM uses its attached identity; no service-account JSON
key or user OAuth credential is installed on the VM for the workload.

```bash
python3 tools/cloud.py init \
  --project=accounting-514109 \
  --ssh-user=vasilistsakanikas \
  --data-uuid=22415b2c-1e1b-4e39-9ce5-5fb0c19dd663 \
  --django-version=1 --postgres-version=1

python3 tools/cloud.py inspect --project=accounting-514109
python3 tools/verify_s08.py
```

`init` creates Git-ignored `private/gcp.json` with mode 0600 and records the active
administrator identity locally. It refuses to overwrite an existing file. The
public example is a configurable starting point, not a command to purchase new
resources. Keep deployment inputs and numeric secret-version references in the
private file. It contains references, never secret payloads. `inspect` reads the
cloud configuration, including the reserved address, selected resource IAM and
absence of user-managed service-account keys. It does not change GCP resources.
The new inspector/provisioner have offline safeguard tests but have not themselves
been executed against GCP in the implementation workspace; the recorded live proof
comes from the user's earlier Cloud Shell/VM commands.

`verify_s08.py` needs Python 3.12+ and Bash, with no additional dependencies, Docker
Engine or GCP credentials. It checks the offline safeguards, shell syntax, unchanged
application context, operator evidence and 85 still-Pending acceptance records.
`--record` updates only its repository-check subsection; it cannot fabricate cloud
execution or convert an unexecuted cloud step into Verified.

## Provisioning reference

The current resources already exist. The following is a repeatable reconstruction
reference, not an additional deployment instruction for the existing VM:

```bash
python3 tools/cloud.py apply --project=accounting-514109
```

The command requires an explicit project matching the private configuration and
existing enabled billing. It enables the named APIs and creates only missing named
resources in that selected project: user-managed VM service account, custom VPC,
IPv4 subnet, three firewall rules, retained data disk, regional IPv4 reservation,
regular VM, private buckets, immutable Docker repository and secret containers.
Existing incompatible VM/network/disk/region/identity settings stop the command.
It does not create projects, resize machines, migrate Docker data, change billing,
replace a VM or automatically stop an existing VM. An incomplete existing disk
attachment or wrong identity is repaired using explicit operator commands.

All gcloud invocations specify the project. Commands are argument arrays rather
than interpolated shell code. Resource names and locations are validated. IAM is
added per bucket/repository/secret, and existing unexpected VM roles stop the tool.
Bucket privacy and immutable tags are set idempotently. Existing secret versions
are kept; only a secret with no versions receives an initial random payload through
stdin. No automatic signing-key/database-password rotation occurs on rerun. Empty
resource lists are handled in Python, avoiding the harmless filter warnings seen
during the first manual creation.

Before reconstructing in another authorised project, set that project explicitly,
review every private parameter, recheck quota/pricing and confirm the exact Ubuntu
image still exists. The observed image name is historical, not a rolling alias.
Partial provisioning is retained on error for inspection; there is no destructive
automatic rollback or deletion of persistent resources.

## Host storage and Docker

The scripts in `infrastructure/` run as root **inside the selected VM**. They check
the hostname and selected disk/mounted filesystem. They do not install the application.
The existing host already passed its manual setup and reboot proof.

```bash
# Existing formatted data disk: validate/mount; never reformat ext4.
sudo bash infrastructure/prepare_data_disk.sh accounting-preview accounting-data 50

# Existing correct Docker layout: inspect only and return without changing it.
sudo bash infrastructure/bootstrap_docker.sh \
  accounting-preview 22415b2c-1e1b-4e39-9ce5-5fb0c19dd663
```

The disk script uses `/dev/disk/by-id/google-accounting-data`, verifies the whole
disk size/type and rejects the root disk. A signature-free, unmounted new disk is
formatted only with the separate `--format-blank` option. Existing ext4 is reused;
a conflicting fstab entry or nonempty unmounted destination stops the script.
fstab uses the filesystem UUID and `defaults,discard,nofail 0 2`. `nofail` allows
host boot for repair; both container runtimes additionally require the data mount
and execute a UUID guard before starting, preventing use of the bare boot directory.

Docker uses `/srv/accounting/docker`; containerd uses `/srv/accounting/containerd`.
The Docker data-root setting alone does not relocate the separate containerd image
store on fresh Docker 29 installations. The host script preserves the vendor TOML
configuration, changes its top-level root and uses `containerd config migrate`.
It obtains packages from Docker's signed Ubuntu repository on a fresh host, blocks
package-triggered service startup until configuration is ready, then installs the
mount dependencies/guard. A fresh-host package install selects the then-current
stable packages; observed versions are recorded in the inventory. Package update
policy is separate from the application's unchanged hashed dependency locks.

The script refuses an unrelated existing Docker/containerd layout rather than
moving data automatically. On a failed fresh install the services may stay masked;
inspect/fix the configuration and mount guard before unmasking/restarting them.
Rootless Docker, a Docker TCP listener and Docker-group membership are not configured.
Use `sudo docker` for administration. No swap was provisioned; remeasure headroom
before S26 introduces workers and a scheduler.

## Identity, ingress and secret handling

| Scope | VM service-account grant |
| --- | --- |
| Document bucket | `roles/storage.objectUser` |
| Backup bucket | `roles/storage.objectCreator` |
| Docker repository | `roles/artifactregistry.reader` |
| Each signing/database secret | `roles/secretmanager.secretAccessor` |
| Project | No role binding shown by the final operator policy query |

The attached identity is `accounting-vm` with the `cloud-platform` OAuth scope;
resource IAM limits actual access. The default Compute identity/read-only scopes
were replaced using a stop/set-service-account/start sequence before the successful
metadata and API checks. No project Editor/Owner/Storage Admin grant was made to
the VM identity. A user-managed-key inventory read is an extra check in the new
inspector; the original manual workflow did not export a service-account key.

Public ingress is TCP 80/443, targeted to `http-server`/`https-server`. TCP 22 is
limited to IAP's `35.235.240.0/20` and the `accounting-preview` tag. The final effective
firewall output contains exactly those three ingress rules. SSH from the laptop
over IAP works. The observed SSH mechanism used metadata keys; OS Login was not
independently verified. IAP restriction, rather than a claimed OS Login setup,
satisfies this checkpoint's administration choice.

Both buckets use uniform bucket IAM, enforced public access prevention, Standard
storage and seven-day soft deletion. That recovery setting is not a business
retention policy, a bucket retention lock or immutable-backup acceptance. The VM
can create a new uniquely named backup object but cannot read/list/overwrite/delete
one. An administrator performs restores and cleanup. Backup automation, encryption,
retention expiry, separately recoverable keys and the off-VM rehearsal remain S10.

The two current secrets have user-managed payload replication in `europe-west1`,
enabled numeric version 1 and per-secret VM read access. This uses the global
Secret Manager API with selected payload storage; it does not claim all regional
in-use/in-transit sovereignty guarantees of regional secrets. DuckDNS token storage
and its operator-only use follow the selected S09 DNS method. Application credential
encryption keys are introduced with their actual consumers/format and recovery plan.
The product settings already accept mounted `_FILE` secret inputs; the production
secret loader and restricted runtime mounts are S09 work.

## Access replay and cleanup

The optional replay is separate from the offline verifier. Copy the private config
and `tools/cloud.py`/`tools/probe_s08_vm.py` securely to the VM, preserving config
mode 0600, and run there:

```bash
python3 tools/probe_s08_vm.py --config private/gcp.json
```

It verifies the expected metadata project/VM/account, reads pinned secret versions
without printing payloads, tests registry listing/reported permissions and performs
synthetic storage operations with generation preconditions. Anonymous reads may
be blocked by either 401 or 403. Authenticated IAM-denial checks require 403; 401,
404, 412, rate limits and server failures do not pass those checks. The initial
inline test incorrectly required 403 for an anonymous request. Its corrected run
passed with 401 for anonymous requests and 403 for the VM's forbidden operations.

The replay uses unique objects under `s08-verification/`. It deletes its document
object and reports the backup object/generation for exact administrator cleanup
from Cloud Shell/laptop. On failure it reports any created objects needing cleanup.
Never recursively delete the bucket. The operator has already removed the backup
object from the recorded successful run. The actual Docker image pull will be
verified when the application image is published at S09; registry listing alone
is not a demonstrated image pull.

## Cost assumptions and open operational inputs

The creation console quoted USD 26.91/month for the selected VM and USD 3.00 for
the 30-GB balanced boot disk, at about 730 running hours. At the reviewed balanced
disk rate (about USD 0.10/GiB-month), the separate 50-GB disk adds about USD 5.00.
An in-use standard-VM external IPv4 at USD 0.005/hour adds about USD 3.65.
That gives an **indicative USD 38.56/month** fixed baseline, not an invoice or cap.
Recheck the actual regional SKUs in the billing currency. Traffic, object storage,
soft-deleted objects, requests, image storage, snapshots, secret accesses, tax and
any other project usage are additional. Stopping a VM does not remove disk/IP costs;
an unattached reserved IPv4 can cost more. No commitment, Spot plan, load balancer,
Cloud SQL instance or NAT gateway was purchased by these steps.

Monthly budget amount, alert recipients, measured workload and incident/restore/key
custodians remain D06/D07 inputs. No alert setup or policy approval is invented.
Set a project-scoped budget and recipients before unattended operation; an alerts-only
budget does not cap spending. Business retention and recovery objectives still need
their policy/rehearsal gates before real data. These open release inputs do not
invalidate the observed synthetic infrastructure checks.

## Official references reviewed 2026-11-09

- [Compute creation and service identities](https://docs.cloud.google.com/compute/docs/access/create-enable-service-accounts-for-instances)
- [IAP TCP forwarding](https://docs.cloud.google.com/iap/docs/using-tcp-forwarding)
- [Persistent disk formatting/mounting](https://docs.cloud.google.com/compute/docs/disks/format-mount-disk-linux)
- [Docker Ubuntu support/install](https://docs.docker.com/engine/install/ubuntu/)
- [Docker/containerd storage roots](https://docs.docker.com/engine/daemon/)
- [Storage object roles](https://docs.cloud.google.com/iam/docs/roles-permissions/storage)
- [Public access prevention: 401/403](https://docs.cloud.google.com/storage/docs/public-access-prevention)
- [Secret replication](https://docs.cloud.google.com/secret-manager/docs/choosing-replication)
- [Secret-level IAM](https://docs.cloud.google.com/secret-manager/docs/access-control)
- [Artifact Registry IAM](https://docs.cloud.google.com/artifact-registry/docs/access-control)
- [Disk pricing](https://cloud.google.com/compute/disks-image-pricing)
- [External IPv4 pricing](https://cloud.google.com/vpc/network-pricing)
- [Billing budget alerts](https://docs.cloud.google.com/billing/docs/how-to/budgets)
