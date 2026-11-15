# S24A — retained local demo upgrade

The operator's retry now authenticates successfully and stops at the exact
schema guard: **12 applied migrations, 20 required**. The retained local demo
is still at S18/0012. The successful 661-test S24A production-image gate used a
disposable database; it did not upgrade this demo. The separate VM is already
at S24 and is not a target of this helper.

The new operator tool is **Prepared**, not executed by the implementation agent.
It adds no models, migrations, financial logic, assertions or dependency changes.
Existing S24A verification/state/traceability files are preserved.

## Operator command

After applying the accompanying Git-only patch on step/s24a-material-ui:

```bash
cd ~/accountant_cloud/accounting_v5/accounting-platform
export PATH="$HOME/.local/bin:$PATH"
python3 tools/upgrade_local_s24a.py --port 8003
```

The command accepts only the retained accounting-client-demo project on a local
Docker Engine and the verified S24A application context. It verifies that the
existing db container and .env agree, and that web uses that same local database
and original Django secret. The named database volume must already exist. It
does not create another project, database volume, account, identity or password.

The operator workflow is:

1. Read the applied migration names; accept the exact existing prefix from
   0012 through 0020. A database already at 0020 goes straight to preview.
2. Check the existing age 1.3.2 identity/recipient from private/operations.json;
   retain the previously confirmed independent recovery copy.
3. Build the local development image, then stop only this project's web.
4. Take a bounded, consistent custom PostgreSQL dump plus .env and snapshot
   manifest on private tmpfs. Encrypt outside Git under
   ~/.config/totalaccounting/local-demo-backups/s18-before-s24a.*/backup.tar.age.
5. Decrypt the new archive back to tmpfs, compare all three file digests, and
   remove plaintext. Compare current source tables with the dump snapshot before
   migration. This is a decryption/integrity check, not a full restore rehearsal.
6. Explicitly apply the unchanged migrations in a one-off local web container
   whose entrypoint is Python, bypassing automatic development startup migration.
7. Compare all original columns/rows across every pre-existing public table.
   Password, MFA, office, membership, session and financial rows must match.
   Django migration/content-type/permission tables may append normal new rows;
   their original rows still must match. Legacy opening dates stay unknown and
   newly introduced financial tables must contain no inferred postings.
8. Call preview_s24a.py only after those checks pass, serving localhost:8003.

The private journal is private/s24a-local-upgrade.json. It contains status and
backup/preservation metadata, never a password or recovery key. Backups remain
outside Git and are never removed automatically. The .env file, credentials and
recovery key are read but never rewritten.

## Failure and recovery

Each migration retains its original atomic guards. If a later migration fails,
earlier forward migrations may already have committed. The tool keeps web
stopped, the database volume and encrypted backup intact. It does not bootstrap
users, repair legacy data, reverse migrations or restore automatically. Report
the safe stage/reason; keep the backup. An interrupted/failed migration attempt
without its preservation receipt blocks another upgrade or normal preview until
that attempt and its original backup have been reviewed. Do not delete the
private journal or weaken this guard to bypass an incomplete preservation check.
If migration succeeded but web startup failed, rerun the ordinary preview helper
after resolving that startup issue; no repeat production suite is required.

This workflow intentionally applies the selected demo upgrade in place after
its backup check. It does not use or modify the historical VM clone installer.
Only the operator may execute it. Technical local execution and actual browser
MFA/responsive/dark-theme review remain Pending until reported. S25 and full S47
accessibility acceptance remain separate.
