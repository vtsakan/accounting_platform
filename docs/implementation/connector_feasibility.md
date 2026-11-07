# Connector feasibility — S02

Reviewed 2026-11-07 using official provider material. The evidence register is [connector_feasibility.json](connector_feasibility.json), including source links, review limits, eligibility, required accounts, sample evidence and unresolved questions for all six connectors. This is a documentary assessment; **no live call or client authorisation has been demonstrated**.

| Connector | Planning disposition | Implementation gate |
| --- | --- | --- |
| AADE basic business registry | Documented registration route; office eligibility and service credentials required | S49 contract, S51 retrieval |
| myDATA | Documented ERP REST route; API registration and client authority required | S49 contract, S52 ingestion, S54 portal configuration |
| VIES | Public validation route identified; technical schema still to inspect | S49 contract, S53 valid/invalid/unavailable outcomes |
| Full TAXISnet profile | Conditional; approved private-application route not established | Block S60 retrieval until evidence exists |
| AADE debt statement | Conditional; approved private-application route not established | Block S61 retrieval until evidence exists |
| e-EFKA notice | Conditional; approved private-application route not established | Block S62 retrieval until evidence exists |

The last three dispositions express a limitation of the reviewed evidence, not a claim that the providers offer no possible route. Published portal functionality, private client consent and public-sector interoperability documentation are different forms of evidence. None alone proves this application's permitted unattended access.

## S49 evidence gate

For each connector, capture the current official contract/version and schema checksum, eligible account type, authorised client scope, authentication, required fields, rate limits and error outcomes. Obtain redacted or synthetic fixtures and record their provenance. Keep live credentials outside Git; refer to scoped connection and secret identities. Test revocation, mismatched clients, retries, pagination and failures before enabling production access.

The AADE developer ZIP and VIES WSDL were located but their contents were not inspected by the document retrieval tool. Do not treat either contract as pinned. The myDATA ERP specification reviewed was v2.0.2; recheck it at S49 rather than freezing a future integration to today's page.

Unsupported retrieval must show a Greek unavailable/authorisation message under UR-LOC-01. Synthetic responses can test a parser but never pass live-access acceptance. A manual document upload, where permitted by the document module, must retain its manual provenance and never be reported as a successful government retrieval. Resolve each conditional requirement explicitly at S63; it is not silently waived by completing S02.
