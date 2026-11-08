# S06 financial regression baseline

S06 captures defects in the preserved legacy financial code. A Verified S06 means the failures are reproducible and tracked; it does **not** mean financial correctness or application acceptance. S19–S24 implement the principal fixes, with supporting model constraints at S18 and report reuse at S29. No business model, form, view, route or original migration changes in S06.

The prerequisite is the user's successful S05 Docker verification, pushed at `5a65a72906f7d3a5fccdcfd8aad0d0362a2bd7fa`. Its actual [S05 evidence](evidence/S05-verification.json) confirms build, migrations, tests, Greek HTTP login and persisted data after container recreation. A later port conflict on the normal development stack was resolved through the existing `WEB_PORT=8001` option; no service or database was removed.

## Observed baseline

On a fresh native PostgreSQL 17.11 cluster, the strict suite runs **78 tests**: **52 pass** and **26 exact known failures are reproduced**. There are no unexpected errors/failures/passes or skips. This includes the original 35 S04/S05 checks, seven regression-runner guard tests and 36 financial cases (26 failures plus 10 passing controls). Running the 36 financial cases under Django's ordinary runner returns exit code 1 with 26 assertion failures and no unexpected errors. Correct expectations have not been weakened to accept the buggy values.

| Legacy issue | Cases / count | Observed defect | Correct contract | Fix steps |
| --- | --- | --- | --- | --- |
| LEG-003 | BAL-001–003 / 3 | Dashboard balance is null when either aggregate side is empty | Opening 100 alone is 100; income 50 gives 150; expense 20 gives 80 | S19 |
| LEG-004 | TRF-001 / 1 | Transfer 1000 changes gross operating income/expense from 50/20 to 1050/1020; net stays 30 | Both gross operating totals stay 50/20 | S21; report selector reuse S29 |
| LEG-005 | SET-001–002 / 2 | Customer B or supplier B can settle 25 against A's agreement, leaving A with 75 | Reject the mismatch without financial writes; A still owes/is owed 100 | S23 |
| LEG-006 | AMT-001–008 / 8 | Zero/negative income, expense and transfer requests persist; direct ordinary model writes also persist | Positive amounts only, with no writes on rejection | S18 constraints; S20 cash; S21 transfers |
| LEG-007 | STA-001–002 / 2 | Reducing/deleting the legacy full receipt leaves COMPLETED despite outstanding 75/100 | Effective settlement status returns to ACTIVE | S23, S24 |
| LEG-008 | CAN-001 / 1 | Resaving a linked full receipt changes CANCELLED to COMPLETED | Explicit cancellation survives automatic settlement recomputation | S24 |
| LEG-009 | FLT-001–009 / 9 | Invalid dates/identifiers on the movement list and report return HTTP 500 | Bound field errors in a Greek validation response | S20; report reuse S29 |

[regression_cases.json](../../accounting/regression_cases.json) is the canonical test/requirement/fix mapping. [S06 verification](evidence/S06-verification.json) records actual results; [case evidence CSV](evidence/S06-regression-baseline.csv) exposes each required/observed value. [known_issues.csv](known_issues.csv) retains the source findings, keeps the reproduced financial defects Open and adds S06 evidence columns. The historical `runtime_verified_in_S01` field remains unchanged.

## Synthetic fixture and existing working controls

`accounting/tests_regressions.py` creates a small fixture in `setUpTestData`: one generated-password user, two clearly labelled customers, two suppliers, two cash accounts, a category and receivable/payable agreements of 100. AFMs `000000011`–`000000014` are deliberately synthetic markers. Money uses Decimal, input uses Greek comma decimals and dates are fixed at 15/01/2026. No fixture file is loaded into the normal development database; Django creates a separate test database and rolls back each test.

The ten passing financial controls exercise mixed balances, same-client partial settlement (100 minus 25 = 75), initial full settlement, paired transfer 1000 with balances 1000/1100, second-leg rollback under an injected failure, rejection of a same-account transfer, invalid text amounts for all three posting forms and rejection of a payable agreement on the income form. Cancelling 1/1 seed movements prevent the separate null-aggregate defect from masking the transfer balance control. The injection targets only the second write inside the existing atomic transfer view; the real database rollback is checked.

These controls establish what already works on the named paths. They do not establish office isolation, idempotent retries, concurrent allocation limits, reversal attribution or the future 120 receipt / 100 charge / 20 credit scenario. Those features and their acceptance tests remain in their assigned steps. One office per active accountant remains the S11/S12/S16 contract. Static inspection also found English product-generated transfer descriptions in the preserved add_transfer_view; S21 must replace that copy under UR-LOC-01. S06 adds no new UI and does not claim complete Greek release acceptance.

The receipt update/deletion probes deliberately demonstrate legacy defects inside rolled-back tests. They are not new user actions or approval of mutable posted records. S24 must adapt these tests to linked reversals/replacements while preserving the outstanding amount/status expectations.

## Run the checks

For daily checks on the running local development stack:

```bash
python3 tools/dev.py test
```

This invokes Django with the strict `accounting.regression_runner.FinancialRegressionRunner`, the core tests, PostgreSQL integration checks and financial cases. Expect `OK (expected failures=26)` for this baseline, with 78 tests run. The 26 remain financial defects, not passing business outcomes.

For a clean, disposable local Docker verification and evidence update:

```bash
python3 tools/verify_s06.py --record
```

The verifier uses a new random `accounting-s06-check-*` project, generated private credentials and port zero to obtain an unused loopback web port. It builds, proves the database is empty before migrations, applies all 20 migrations, runs both the strict and ordinary-runner checks and cleans up only its own containers/network/volume. It also checks the dependency locks, catalog, original business-code identity and source/history secret scan. The normal `.env`, port 8001 and development volume are not selected. Full source history, Python 3.10+ with venv, package-download access and a local Docker Engine/Compose plugin are required.

`--record` writes the S06 verification JSON, case-evidence CSV, steps and state only after verification succeeds. A plain run prints the result without changing state. The current supplied evidence was produced by:

```text
python3 tools/verify_s06.py --native-bin /absolute/path/to/postgresql/17/bin --record
```

Native mode uses its own temporary UTF-8/SCRAM PostgreSQL 17 cluster over loopback TCP. It can verify S06's PostgreSQL test-capture gate because S05's Docker gate is already independently Verified. It explicitly records `docker_execution_this_step: false`; it does not claim a new Docker image run. The package provenance is retained in [S05 native provenance](evidence/S05-native-provenance.json).

To inspect the raw failures on the local development stack (an intentional nonzero exit):

```bash
python3 tools/dev.py test-raw
```

Use the strict runner for CI in S07. The S06 verifier is a historical snapshot check and also protects the unchanged legacy source; later feature commits use their own verifier and the updated regression runner/registry.

## Keep future fixes visible

The strict runner recognises only `KnownFinancialMismatch` from the registered case after the test has matched the specific observed legacy value. An unrelated assertion, changed failure pattern or runtime exception fails normally. Known cases that pass become **unexpected successes**, which fail the command and require investigation. Tracked skips and broad `@expectedFailure` are rejected. Seven guard tests demonstrate these distinctions. All seven defect groups must remain represented; missing or duplicated cases fail full verification.

When a planned fix makes a case pass, inspect the actual behavior and linked requirement first. Remove the legacy mismatch path or keep the correct assertion, set that case's registry outcome to `pass`, record the fix/retest evidence and close the appropriate issue only when all of its cases are resolved. Do not delete the case, accept the old incorrect value as the desired result or mark a runtime error as expected. Historical S06 evidence remains the baseline.

Malformed-filter tests require a successful validation response (HTTP 200 or 400), Greek content and field errors exposed through `filter_form` in the template context. A report/list crash is recognised only with the original date/identifier exception type. S20 may adapt the view-context access if it introduces equivalent typed field validation; the no-server-error and visible validation contract remains unchanged.

## Acceptance and next step

All 71 user and 14 quality acceptance statuses remain Pending, including QT-03/QT-14. D01–D09 policy approvals are unchanged. No live messages, connectors, client data or cloud resources were used. Next is **S07**, the production image and delivery checks. **The Google Cloud VM is needed at S08, after S07 is verified.**

Official test-runner extension contracts: [Django 5.2 advanced testing](https://docs.djangoproject.com/en/5.2/topics/testing/advanced/) and [Python 3.12 unittest results](https://docs.python.org/3.12/library/unittest.html).
