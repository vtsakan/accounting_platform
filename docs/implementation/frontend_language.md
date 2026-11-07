# Greek frontend implementation guide

Required by [CR-001 / UR-LOC-01](../requirements/CR-001-Greek-frontend.md). This is the implementation contract for every user-facing feature. The current S01 application has not yet been translated.

## S04 foundation

Use Django's `LANGUAGE_CODE = 'el'`, restrict `LANGUAGES` to Greek, enable `USE_I18N` and `USE_TZ`, and use `TIME_ZONE = 'Europe/Athens'`. Add `LocaleMiddleware` after session middleware and before common middleware. Set HTML `lang="el"`. Treat language selection as Greek even with `Accept-Language: en`; do not expose an English switcher. Use project gettext catalogs for reusable copy, lazy translations for model/form metadata and plural-aware messages for counts. Compile catalogs during the image build and verify Django's built-in auth/admin/validation translations as well as custom messages. [Official Django 5.2 translation guide](https://docs.djangoproject.com/en/5.2/topics/i18n/translation/).

Inventory all 17 templates listed in `source_inventory.json`, `accounting/forms.py`, model choice/field labels, view messages and authentication pages. Translate as the settings and feature steps touch them. Bootstrap alone does not translate labels, accessibility attributes or JavaScript widgets. Verify date-picker labels, table pagination, charts, confirmation prompts and background-job status text explicitly.

Use UTF-8 throughout and render dates as `DD/MM/YYYY`. Render monetary values consistently with Greek separators, for example `1.234,56 €`. Validate Greek decimal input deliberately; do not perform money arithmetic with display strings or floating-point values. QR-07 retains its date/time, AFM and daylight-saving checks; exact input parsing is implemented and tested in S04/S05 and the relevant finance steps.

## Initial copy glossary

These labels are implementation defaults. The requirement for Greek is confirmed; the accountant may refine terminology without changing the underlying financial model.

| Concept | Greek label |
| --- | --- |
| Dashboard | Επισκόπηση |
| Office / office owner / accountant | Λογιστικό γραφείο / Υπεύθυνος γραφείου / Λογιστής |
| Client / supplier / counterparty | Πελάτης / Προμηθευτής / Συναλλασσόμενος |
| Cash accounts / categories | Ταμεία / Κατηγορίες |
| Agreement / charge | Συμφωνία / Χρέωση |
| Receipt / payment / allocation | Είσπραξη / Πληρωμή / Αντιστοίχιση πληρωμής |
| Internal transfer / reversal | Εσωτερική μεταφορά / Αντιλογισμός |
| Outstanding amount / unallocated credit | Ανεξόφλητο ποσό / Αδιάθετο πιστωτικό υπόλοιπο |
| Balance / opening balance | Υπόλοιπο / Αρχικό υπόλοιπο |
| Tasks / calendar / deadline | Εργασίες / Ημερολόγιο / Προθεσμία |
| Files / documents / requests | Αρχεία / Έγγραφα / Αιτήματα |
| Client portal / access grant | Πύλη πελάτη / Εξουσιοδότηση πρόσβασης |
| VAT forecast / income-tax forecast | Εκτίμηση ΦΠΑ / Εκτίμηση φόρου εισοδήματος |
| Presumptive expenses | Τεκμήρια |
| Save / cancel / search / download | Αποθήκευση / Ακύρωση / Αναζήτηση / Λήψη |
| Sign in / sign out / recover password | Σύνδεση / Αποσύνδεση / Ανάκτηση κωδικού |
| Required field | Το πεδίο είναι υποχρεωτικό. |
| Invalid value | Ελέγξτε την τιμή του πεδίου. |
| Empty list | Δεν βρέθηκαν εγγραφές. |
| Access denied | Δεν έχετε πρόσβαση σε αυτή την ενέργεια. |
| Service unavailable | Η υπηρεσία δεν είναι διαθέσιμη αυτή τη στιγμή. |

## Outcome wording

| Outcome | Greek copy and meaning |
| --- | --- |
| Mail queued | Σε αναμονή |
| SMTP submission accepted | Υποβλήθηκε στον διακομιστή αλληλογραφίας — does not claim recipient delivery |
| Mail failed / uncertain submission | Απέτυχε / Αβέβαιη υποβολή — uncertainty requires review before resend |
| Connector awaiting access | Απαιτείται εξουσιοδότηση |
| Conditional connector unavailable | Η σύνδεση δεν είναι ακόμη διαθέσιμη. |
| VIES invalid / unavailable | Μη έγκυρος αριθμός ΦΠΑ / Ο έλεγχος δεν ήταν διαθέσιμος — distinct outcomes |
| Forecast unsupported | Η συγκεκριμένη περίπτωση δεν υποστηρίζεται ακόμη. |

Keep user messages separate from internal diagnostic codes. Show a safe Greek message and an optional support reference; preserve technical diagnostics only in protected logs.

## AT-LOC-01 release checklist

For each implemented module, review a representative full journey with Greek names and an English browser preference. Cover labels, accessible names, positive/zero/plural counts, empty states, invalid input, denied access, expired sessions and service failures. Inspect product-authored emails and PDF/export headings. Check at 375, 768 and 1440 CSS pixels alongside S47 accessibility work. Preserve English brands and original user/provider content. Record actual paths, screenshots or test results at S31, S47/S48 and S63; a documentation check alone never passes application acceptance.
