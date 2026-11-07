# S01 source inventory

Reviewed on 2026-11-07. The authoritative input is `accountant_v6.zip`, whose root is `accountant_v3`. No existing Git history or remote is included in that archive. The new local source baseline is `3bb4c0240a48ee31ddbb19a26698bc25b3c79486` on `main`.

## Source preservation

The original archive is retained unchanged as the private reference and is already saved as `accountant_v6.zip`. Its SHA-256 is `d2bce8470dd1a3fab2907745f55c17f4ee087d1caf49673c1b42827d6743dd96`. The complete archive has 1396 files. The working export contains 38 source files: 35 byte-identical files, two configuration files with three embedded secret values cleared, and an ignore file protecting private/runtime inputs. The bundled environment, bytecode and SQL backup are excluded. No model, form, view, template, route or migration is changed.

`source_manifest.csv` records every original archive member, checksum, disposition and working checksum. `source_redactions.json` identifies redaction locations without values. The original archive, database payload and compiled caches are never included in the handoff package.

## Runtime and dependencies

- Declared framework: Django 5.2.5 in a 364-line environment-wide dependency freeze.
- Database: PostgreSQL backend; the source Compose definition declares `postgres:15` and only a `db` service.
- Python version for the new build is a planning decision; no dependency installation has been performed in S01.
- Interface: Django templates and Bootstrap 5.3.3; 17 templates.
- Configuration: legacy DEBUG=True, en-us and UTC. Source credentials were present and are cleared in the working export. The full settings split and production checks belong to S04/S07.
- Delivery gaps: no application Dockerfile, web service, reverse proxy, worker, scheduler or backup tooling in the supplied source.
- `accounting/tests.py` contains no implemented tests. S01 performs static and handoff-integrity checks only.

## Business models

| Model | Expected default table name | Declared fields |
|---|---|---|
| Entity | accounting_entity | entity_type, name, vat_number, tax_office, address, city, postal_code, phone_number, email, created_at, updated_at |
| CashAccount | accounting_cashaccount | name, opening_balance, is_active |
| Category | accounting_category | name, parent |
| Agreement | accounting_agreement | agreement_type, entity, description, total_amount, start_date, status, created_at, updated_at |
| Transaction | accounting_transaction | transaction_date, transaction_type, amount, description, remarks, cash_account, category, entity, agreement, transfer_id, created_at, updated_at |

Table names above are inferred from Django's unchanged app/model names and absence of a custom db_table. No database has been inspected. There is no Office or AccountantProfile, no separate charge/allocation schema, and no client portal or external-source dataset.

## Migration history

- `0001_initial`: CreateModel CashAccount, CreateModel Entity, CreateModel Category, CreateModel Agreement, CreateModel Transaction. SHA-256 `9a7bdd7e986f6fad6e3d46f77e5b415b2550a3469fb676294c92f78b0d6e7edd`.
- `0002_transaction_agreement_alter_agreement_status_and_more`: AddField transaction, AlterField agreement, AlterField transaction, AlterField transaction. SHA-256 `a0f2e06b564441a5e369789c446a3c0cf2847b855d781bdd682f13d6a32aaf0e`.

The second migration depends on `accounting.0001_initial`. Both migration files and the application label `accounting` are preserved. No migration has been executed, deleted or regenerated in S01.

## Routes

There are 15 application view functions, each decorated with login_required; login alone does not provide office isolation. There are 17 accounting route entries and 2 root route entries.

| Source | Route | Target | Name |
|---|---|---|---|
| core/urls.py:7 | `admin/` | `admin.site.urls` |  |
| core/urls.py:9 | `/` | `include('accounting.urls')` |  |
| accounting/urls.py:7 | `login/` | `auth_views.LoginView.as_view(template_name='accounting/login.html')` | login |
| accounting/urls.py:8 | `logout/` | `auth_views.LogoutView.as_view()` | logout |
| accounting/urls.py:9 | `/` | `views.dashboard_view` | dashboard |
| accounting/urls.py:10 | `transactions/` | `views.transaction_list_view` | transaction-list |
| accounting/urls.py:11 | `customers/` | `views.customer_list_view` | customer-list |
| accounting/urls.py:12 | `suppliers/` | `views.supplier_list_view` | supplier-list |
| accounting/urls.py:13 | `expense/add/` | `views.add_expense_view` | add-expense |
| accounting/urls.py:14 | `income/add/` | `views.add_income_view` | add-income |
| accounting/urls.py:15 | `entity/add/` | `views.add_entity_view` | add-entity |
| accounting/urls.py:16 | `entity/<int:pk>/` | `views.entity_detail_view` | entity-detail |
| accounting/urls.py:17 | `report/` | `views.summary_report_view` | summary-report |
| accounting/urls.py:18 | `entity/<int:pk>/edit/` | `views.edit_entity_view` | edit-entity |
| accounting/urls.py:19 | `agreements/` | `views.agreement_list_view` | agreement-list |
| accounting/urls.py:20 | `agreement/<int:pk>/` | `views.agreement_detail_view` | agreement-detail |
| accounting/urls.py:21 | `agreement/add/` | `views.add_agreement_view` | add-agreement |
| accounting/urls.py:22 | `agreement/<int:pk>/edit/` | `views.edit_agreement_view` | edit-agreement |
| accounting/urls.py:23 | `transfer/add/` | `views.add_transfer_view` | add-transfer |

## Feature boundary

The existing source supplies client/supplier identity, cash accounts/categories, cash entry and transfer screens, agreements, a dashboard and a summary report. These are source capabilities with known defects, not passed requirements. The TaxPilot-style additions are allocated by the 70 user requirements. Their status and the 14 quality requirements remain Pending in `traceability.csv`.

Government retrieval is conditional on demonstrated authorised contracts. AADE registry, myDATA and VIES are planned in S49 to S54. TAXISnet profile, AADE debt and e-EFKA notices remain conditional in S60 to S62. The public competitor demo is not evidence of a production adapter. Forecast rules need approved taxpayer/year cases in S55 before implementation.

## Findings and verification limits

`known_issues.csv` contains 15 open findings with evidence and assigned steps. Source inspection in S01 agrees with the baseline's reported issues. Prior synthetic SQLite results are historical evidence, not newly executed PostgreSQL results. The application has not been started and no business data, migration or cloud resource has been changed.

See `module_map.md`, `source_inventory.json` and `migration_inventory.json` for the structured inventory.
