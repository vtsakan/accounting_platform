# CR-008 — Classified attachments on the main client card

Selected on22 November2026 after actual CR007 Verified1140/36 and the retained
worker gate, recorded by the operator in02e3907. This is a separate manual staff
feature; full S38/S39/portal/versioning and all85 acceptance records stay Pending.

The user explicitly selected a common office classification catalogue PLUS a
free description per attachment. Add PDF, legacy DOC, DOCX and raster images
on the main counterparty card; a record with both roles uses the same section.

* Upload one file at a time, maximum25,000,000 bytes; category is required,
  description optional with1,000-character maximum. Record server date and
  uploader; never accept submitted office, user, scan result or storage key.
* Show/filter/paginate file metadata on the card. Active same-office owners and
  accountants can upload, download and change classification/description.
* Only the owner creates/changes/retires shared categories and removes files.
  Retiring a category preserves historical labels and prevents new use.
* Archive blocks new uploads and metadata edits, retaining old downloads.
  Existing owner-only client deletion also removes all sealed bytes and private
  filenames/descriptions, while preserving value-free action identities.
* Content-based validation runs with bounded CPU/memory/time in a child process.
  A real local/private ClamD scan with current signatures must finish clean
  before a file enters accepted storage. Unavailable/infected/incomplete scans
  leave no accepted bytes. Password-protected, macro-bearing, active embedded
  and unsupported vector documents are not accepted.
* Store bounded AES-GCM-sealed bytes in the database, purpose/office/client/file
  bound to the retained external signing material. Metadata lists do not load
  payloads. File edits never replace bytes. No public URLs, filesystem paths,
  portal sharing, connector retrieval, email attachments or silent replacement.
* Downloads are one-click CSRF-protected POSTs with fresh office/client checks,
  immutable actor audit, forced attachment response and no-store/nosniff headers.
  GETs remain read-only. Existing finance, notes and tasks are unchanged.

Preparation must preserve all34 old migrations, the original1140 test-method
ASTs and assertions, dependency pins, actual14 prior receipt/binding files,
human accounts/MFA and current CR005 VM/GitHub. Add only0035/0036. The operator
gate must pass the complete new production-image suite,36 financial cases,
actual scanner/EICAR and all permitted format probes, restricted-role migrations,
encrypted database restore with separately recovered key and original file hashes,
and the retained real monthly-worker gate. Native checks are not run by agent.

The existing VM has no approved scanner capacity. Its later rollout requires
a separately selected scanner/resource/recovery plan; this change does not
resize, provision, deploy, publish or grant public file access.
