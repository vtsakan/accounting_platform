# Google Cloud / DuckDNS parameter sheet

**S08 is Verified from operator execution; the selected VM already exists.** Read the [actual inventory](cloud_inventory.json) and [S08 operator instructions](google_cloud.md). Copy operative references into Git-ignored private/gcp.json with tools/cloud.py init; the public [parameter template](deployment_parameters.example.json) remains blank. Null means unknown, not a default to create. S09 deploys HTTPS and S10 proves off-VM restore.

## Confirmed and proposed choices

Google Cloud VM hosting and an initial DuckDNS hostname are user-confirmed. The planned application remains Django/PostgreSQL, Caddy/Gunicorn and Docker Compose. Greek frontend language is confirmed. Exact versions are checked at S03/S07.

The initial e2-standard-2/Ubuntu24.04 candidates were superseded by the user's actual lower-cost e2-medium/Ubuntu26.04.1 selection in Belgium. The regular non-Spot VM has 4 GB RAM, a 30-GB boot disk and separate retained 50-GB balanced data disk. The external static IPv4 is Premium tier. Shared-core capacity is not measured workload acceptance. Read the S08 inventory/runbook for actual storage, identity, cost assumptions and pending budget/operational inputs. A single VM has one failure domain; backups and a recovery rehearsal are required before live use.

## Inputs and owners

| Parameter group | Required values | Owner / needed by |
| --- | --- | --- |
| Project and spend | Project ID, billing enabled, budget and alert recipients | vtsakan / S08 |
| Location | Chosen EU region and zone, storage location and policy approval | Office owner + operator / S08 |
| Existing resources | Existing VM/network/disk details, or explicit new preview target | vtsakan / S08 |
| Administration | Google identity, OS Login/IAP policy or restricted SSH source, operator | vtsakan + operator / S08 |
| Compute/storage | VM name/type, disk sizes, persistent mount, disk retention and capacity alarms | Operator / S08 |
| Network | VPC/subnet, regional reserved IPv4 name/address; public HTTP/HTTPS only | Operator / S08 |
| Domain | Available owned DuckDNS subdomain, token secret reference, ACME contact | vtsakan / S08–S09 |
| Images and files | Artifact Registry repository, private document and backup bucket names | Operator / S08 |
| Runtime identity | Dedicated attached VM service account and least-privilege IAM policy | Operator / S08 |
| Secrets | Version references for Django, database, encryption key and DuckDNS token | Secret custodian / S08–S09 |
| Recovery | Backup retention, key custodian, recovery owner and tested procedure | Office owner + operator / S10 before live data |
| Ongoing service | Incident owner, restore owner and notification destination | vtsakan / S10, final at S31 |

Keep real secret values out of the parameter sheet, shell history, request logs and Git. Provisioning must use the selected environment; missing target values block cloud mutations, not local S03–S07 work. SMTP and government-service credentials are later S41/S49 inputs.

## Deployment rules to carry into S08–S10

Reserve a regional external IPv4 and attach it to the selected VM; set the DuckDNS A record to that address. DuckDNS offers an HTTPS token-authenticated update API. With a reserved address, repeated DNS updates are only necessary when the chosen address changes. Verify public DNS and remove stale IPv6 records before issuing a certificate; keep the token out of captured URLs and logs.

Use the VM's attached service account for Google API access and constrain access with IAM. Do not download a service-account JSON key. Keep documents/backups private, isolate PostgreSQL and Redis from public ingress, and preserve data disks on VM deletion. Record Caddy data, PostgreSQL data and uploaded-file locations explicitly. Add one worker and exactly one scheduler at S26, then reassess memory.

S09 must demonstrate certificate issuance and renewal, HTTP-to-HTTPS redirect and secure application settings. S10 must restore database, documents and required keys off the original VM. Template values and a successful container build are not deployment/recovery evidence.

## Official references reviewed 2026-11-07

- [Google Compute Engine machine families](https://docs.cloud.google.com/compute/docs/general-purpose-machines).
- [Reserve a static external IP](https://docs.cloud.google.com/vpc/docs/reserve-static-external-ip-address).
- [Compute Engine service accounts and scopes](https://docs.cloud.google.com/compute/docs/access/service-accounts).
- [DuckDNS HTTPS update specification](https://www.duckdns.org/spec.jsp).

Sizing, disk sizes and operational policies above are project recommendations; they remain subject to D06/D07 and measured release checks.
