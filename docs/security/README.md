# Source secret scanning

Run the pinned tooling environment's Python with `tools/scan_secrets.py`. It scans the candidate source (tracked files plus unignored new files) and unique historical Git blobs reachable from local refs. The scanner uses `detect-secrets` with online token verification disabled. It emits paths, detector names, line numbers and fingerprints, never matched values.

`secret_scan_allowlist.csv` contains reviewed non-secret fingerprints only: public Bootstrap integrity digests, immutable source/document hashes and Git commit identities. Entries are exact detector/fingerprint pairs, not blanket path exclusions. A new finding fails the check. Review the source before adding any exception; an exposed credential must be revoked/rotated and removed rather than accepted as a non-secret. Do not paste its value into evidence or an issue.

The scan is heuristic and covers UTF-8 text; it does not inspect binary documents or establish that every possible credential format is detectable. It checks version-controlled history independently of ignore patterns. S03 also verifies that no private/runtime payload is tracked and that the previously redacted working settings remain empty. No credential value was present in the controlled Git baseline, so S03 records no Git-exposure rotation requirement.
