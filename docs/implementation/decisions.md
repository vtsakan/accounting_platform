# Decision register

S01 seeds the existing D01 to D09 decisions from ACC-URS-001. Detailed options, feasibility evidence and review belong to S02. No new domain approval has been inferred.

Confirmed user constraints: one office per active accountant; Google Cloud VM deployment; an initial DuckDNS hostname.

## D01

Office and staff roles. Exactly one office per active accountant is confirmed. Several accountants per office and the owner/accountant permission matrix are proposed.

- Source owner and gate: Product owner G0.
- Status: One-office constraint confirmed; proposed role details pending S02.
- Resolution and evidence: not yet recorded.

## D02

Client scope and portal authority. Keep independent client records per office; confirm which representative may approve accountant grants and which staff may see office finances.

- Source owner and gate: Product owner and office owner G0 before WP1.
- Status: Pending S02 review.
- Resolution and evidence: not yet recorded.

## D03

Government access paths. Confirm service eligibility, delegation, credentials and technical access for each connector. No undocumented access method is assumed.

- Source owner and gate: Service account owner and developer G0 before connector commitment.
- Status: Pending S02 review.
- Resolution and evidence: not yet recorded.

## D04

Supported tax cases. Approve taxpayer types, tax years, form mappings, rounding and reference examples. A reviewed subset must be named before implementation.

- Source owner and gate: Accountant reviewer G0 outline and G5 final.
- Status: Pending S02 review.
- Resolution and evidence: not yet recorded.

## D05

Legacy ownership and cutover. Approve legacy user-to-office mapping, opening balance dates, paired transfers, invalid allocations and migration reconciliation totals.

- Source owner and gate: Office owner G2 before live migration.
- Status: Pending S02 review.
- Resolution and evidence: not yet recorded.

## D06

Scale and service targets. Confirm section 5 load, file limits, availability, recovery and accessibility targets against expected users and hosting budget.

- Source owner and gate: Product owner and operator G0 before sizing.
- Status: Pending S02 review.
- Resolution and evidence: not yet recorded.

## D07

Data and credential policy. Approve hosting region, secret access, retention per data category, key recovery, client-request handling and operational responsibilities.

- Source owner and gate: Office owner and operator Before R1 live use and R2 portal use.
- Status: Pending S02 review.
- Resolution and evidence: not yet recorded.

## D08

Financial policy. Confirm billing frequency, overpayments, refunds, corrections, agreement changes, opening balances and category treatment in office reports.

- Source owner and gate: Accountant reviewer G2 before finance acceptance.
- Status: Pending S02 review.
- Resolution and evidence: not yet recorded.

## D09

Product scope and staffing. Approve release sequence, Must/Should priorities, planning resources and contingency. Subscription charging and native mobile apps remain outside this baseline.

- Source owner and gate: Product owner G0.
- Status: Pending S02 review.
- Resolution and evidence: not yet recorded.

