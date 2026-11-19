# S31A — ενημέρωση υπάρχοντος preview VM και GitHub

Κατάσταση πηγαίου κώδικα: **Prepared**. Η ενημέρωση ζητήθηκε ρητά από τον
χειριστή στις 19/11/2026. Το GitHub που ελέγχθηκε βρίσκεται στο S24A,
`8776216da1bb39cf4d24c00f31b216e9fd856ccd`. Το πραγματικό επαληθευμένο S31
του υπολογιστή, `39a088ab36970ebe839624b28521adaf9f72d9fb`, δεν υπάρχει ακόμη
στο GitHub. Το πακέτο δημοσιεύει αυτό το ιστορικό, μαζί με τα τοπικά πραγματικά
receipts και τις τέσσερις δεσμεύσεις ιστορικού. Δεν τα αντικαθιστά με αντίγραφα
της προετοιμασίας. Η ενημέρωση του VM/remote δεν έχει εκτελεστεί από τον agent.

Διορθωμένη έκδοση μετά το πραγματικό APPLY stop: ο γενικός έλεγχος καθαρού
Git είχε κληθεί πριν καταγραφούν τα τέσσερα αρχεία του `verify_s31 --record`.
Πλέον προηγούνται ακριβής έλεγχος των application bytes και validation των
αποτελεσμάτων/ιστορικού. Καταγράφονται μόνο τα τέσσερα ήδη επιτρεπόμενα αρχεία
και μετά εκτελείται ο ίδιος αυστηρός έλεγχος committed context. Το ίδιο ισχύει
πριν από publication. Άσχετες αλλαγές ή διαφορετικός κώδικας σταματούν τη
διαδικασία. Η προηγούμενη προσπάθεια δεν έφτασε σε build/push/VM.

Το S31 πέρασε 848/848 tests, 36/36 οικονομικά σενάρια, 48 host contracts,
πραγματικό Redis/worker, migration/cycle/performance/recovery. Επαναχρησιμοποιούμε
την ίδια τοπική εικόνα `sha256:6795deceab7250e41f1465e792cde0efe818d89060e134ef7588ae2df04959eb`
με application revision `605c6a5534fe9ad96185b8c2e1473ce41e406834` και context
`sha256:a3dbff49144c7072f8308ab50ca96f4c9ddb36c56eb873593b216dce2111329c`.
Δεν γίνεται νέο build ή επανάληψη του ήδη περασμένου γενικού suite.

## Μία εκτέλεση από τον υπολογιστή

Αποθηκεύστε το ZIP στα Downloads και τρέξτε:

```bash
bash <<'SH'
set -euo pipefail
unzip -o ~/Downloads/accounting-platform-S31A-VM-GitHub-record-fix.zip \
  -d ~/Downloads/accounting-platform-S31A-VM-GitHub-record-fix
cd ~/accountant_cloud/accounting_v5/accounting-platform
bash ~/Downloads/accounting-platform-S31A-VM-GitHub-record-fix/UPDATE_GITHUB_AND_VM.sh
SH
```

Προϋποθέσεις είναι τα ίδια λειτουργικά Git/GitHub, gcloud/IAP, τοπικό Docker,
age 1.3.2 και τα υπάρχοντα δικαιώματα Artifact Registry και ανάγνωσης backups.
Η ανεξάρτητη ήδη ανακτημένη ταυτότητα προεπιλέγεται σε
`~/.config/totalaccounting/recovered-backup-age.key`, χωριστά από την κύρια
ταυτότητα. Αν η υφιστάμενη ανεξάρτητη αντιγραφή βρίσκεται αλλού, ορίστε
`ACCOUNTING_RECOVERY_IDENTITY` στην απόλυτη διαδρομή της. Δεν δημιουργούμε,
αντικαθιστούμε ή δημοσιεύουμε κλειδιά. Η γνωστή κύρια διαδρομή αναζητείται στα
υπάρχοντα αγνοούμενα `private/vm-s24-operations.json`, `demo-operations.json`,
`operations.json`, με τον ίδιο backup recipient.

Ο πρώτος έλεγχος είναι μόνο Git/αρχεία. Επαληθεύει το ακριβές επιτυχές S31
receipt, 592 προστασίες, τις πραγματικές δεσμεύσεις ιστορικού και το ίδιο image
context. Καταγράφει μόνο τις τέσσερις γνωστές αλλαγές του `verify_s31 --record`
αν δεν έχουν ήδη γίνει commit. Άσχετες τοπικές αλλαγές διατηρούνται και σταματούν
την εκτέλεση πριν από publication. Το APPLY δημιουργεί branch
`step/s31a-preview-upgrade`, προσθέτει μόνο το tooling/τεκμηρίωση και μια νέα
γραμμή S31A. Δεν εκτελεί Docker, migrations ή cloud. Μετά τρέχουν οι 22 μικροί
stdlib guard έλεγχοι από τον χειριστή.

Το GitHub ενημερώνεται πρώτα με όλο το πραγματικό ιστορικό S25–S31 και το
παρόν tooling. Γίνεται fetch και έλεγχος ancestry/secret scan, έπειτα κανονικό
push στο branch και fast-forward στο main. Δεν γίνεται force push, reset,
αυτόματο merge ή παράκαμψη προστασίας branch. Ανεξάρτητο remote commit ή
branch protection σταματά τη διαδικασία χωρίς αντικατάσταση ιστορικού.
Το τελικό πραγματικό VM receipt ανεβαίνει μόνο μετά την ολοκλήρωση των ελέγχων.
Ο scanner χρησιμοποιεί προσωρινό περιβάλλον με το υπάρχον κλειδωμένο
`requirements-tools.txt`. Μπορεί να χρησιμοποιηθεί υπάρχον αντίστοιχο Python με
`ACCOUNTING_TOOLS_PYTHON`. Η πολιτική scanner και τα παλιά reviews παραμένουν ίδια.

## Ακριβές περιβάλλον και πορεία αναβάθμισης

Στόχος είναι αποκλειστικά το υφιστάμενο **synthetic preview**:
`accounting-514109/accounting-preview`, `europe-west1-b`,
`https://totalaccounting.duckdns.org`. Ελέγχονται το instance ID, UUID δίσκου,
mount, Docker root, παλιά εικόνα S24A, 20 migrations, pinned secrets, backup
binding και ενεργοί timers. Κρατιούνται domain, TLS δεδομένα, IAM, δικαιώματα
DB, PostgreSQL container/start time και όλα τα παλιά αρχεία migrations.

Το VM είναι e2-medium με 4 GB RAM και shared CPU. Ο προέλεγχος απαιτεί διαθέσιμη
μνήμη/χώρο χωρίς αλλαγή machine type ή δίσκων. Το ξεχωριστό override ορίζει
τέσσερις sync web workers, όριο web 1 GiB/2 CPU, και τις υπάρχουσες ρυθμίσεις
DB 768 MiB, worker 512 MiB, scheduler 192 MiB, Redis 192 MiB, Caddy 256 MiB.
Τα όρια υπηρεσιών δεν εξασφαλίζουν αντίστοιχο φυσικό CPU. Το αποτέλεσμα του
τοπικού S31 με DB 1 GiB δεν είναι μετρημένη αποδοχή αυτού του VM. Εδώ ελέγχονται
πραγματικές υπηρεσίες/διαδικασίες και health, χωρίς εισαγωγή συνθετικού load
dataset στην υπάρχουσα βάση. Η αποδοχή χωρητικότητας D06 παραμένει Pending.

Η εικόνα ανεβαίνει και τραβιέται με αμετάβλητο registry digest. Static assets
εξάγονται από την ίδια εικόνα, διατηρώντας παλιές hashed διαδρομές. Το παλιό site
μένει διαθέσιμο μέχρι να ολοκληρωθούν οι προέλεγχοι και το pull.

Στο σύντομο διάστημα συντήρησης σταματούν Caddy/web και παύουν οι S10 timers.
Αφού τελειώσουν τα ενεργά operations, λαμβάνεται **νέο παγωμένο** snapshot της
πραγματικής βάσης· η συνήθης χρήση πριν από αυτό δεν ακυρώνει παλιό snapshot.
Δημιουργείται κρυπτογραφημένο GCS backup και νέο, μοναδικό DB clone. Η αρχική
βάση παραμένει ανέπαφη στον ίδιο PostgreSQL. Μόνο το clone μεταβαίνει 20→26
με τον restricted application role. Συγκρίνονται όλες οι παλιές στήλες/γραμμές,
κωδικοί, MFA, sessions και οικονομικά δεδομένα. Μόνο προσθήκες metadata IDs
επιτρέπονται· οι δέκα νέοι επιχειρησιακοί πίνακες πρέπει να είναι κενοί.
Τα υπάρχοντα encrypted MFA seeds αποκρυπτογραφούνται χωρίς εγγραφή ή εμφάνιση.

Το candidate web ξεκινά χωρίς δημόσιο proxy/jobs και με `restart: no`.
Ακολουθεί κρυπτογραφημένο backup του clone. **Και τα δύο** ακριβή GCS backup
generations αποκρυπτογραφούνται με το ανεξάρτητο κλειδί και επαναφέρονται σε
απομονωμένο τοπικό PG17.11 εκτός VM, με πλήρη συμφωνία όλων των πινάκων.
Τα recovery containers και plaintext διαγράφονται από τον υπάρχοντα owned
S10 μηχανισμό. Η VM δεν αποτελεί restore target.

Μόνο τότε ενεργοποιούνται Redis με retained AOF, worker concurrency=1,
ακριβώς ένας scheduler με DB singleton lease και τέσσερις πραγματικοί Gunicorn
workers. Δεν δημιουργούνται fee plans/charges κατά τη migration. Οι flags
background jobs/fee automation επιτρέπουν τις λειτουργίες S26–S30 στο preview·
νέα αυτοματοποίηση χρέωσης εξακολουθεί να απαιτεί τις κανονικές ρητές ενέργειες
και την υπάρχουσα εξουσιοδότηση της εφαρμογής.

Οι δημόσιοι έλεγχοι επαληθεύουν έγκυρο HTTPS/hostname, readiness, ελληνική
Material login, CSRF origins και ακριβή CSS/JS/SVG bytes από την ίδια εικόνα.
Οι backup/monitoring timers επανέρχονται. Το reboot resume χρησιμοποιεί το
ίδιο overlay/jobs profile και δεν εκτελεί migrations ή bootstrap. Ένα hold
πριν από activation απαγορεύει αυτόματο ξεκίνημα του candidate μετά από reboot.

## Διακοπή, συνέχεια και αποτελέσματα

```bash
cd ~/accountant_cloud/accounting_v5/accounting-platform
export PATH="$HOME/.local/bin:$PATH"
python3 tools/preview_s31_release.py status
python3 tools/preview_s31_release.py resume
```

Πριν από activation αποτυχία restore επιχειρεί επιστροφή της διαθεσιμότητας
στην παλιά βάση/εικόνα. Το clone και τα backups διατηρούνται. Διατίθεται επίσης
`python3 tools/preview_s31_release.py abort`, αποκλειστικά πριν από πιθανές
νέες εγγραφές. Μετά την έναρξη jobs/public activation το εργαλείο αρνείται
επιστροφή στην παλιά βάση: διατηρεί τον τρέχοντα clone, journal και backups.
Χρησιμοποιήστε status/resume για τον ίδιο στόχο. Δεν διαγράφονται journals,
βάσεις ή volumes και δεν γίνονται αντίστροφα migrations. Νέα απόπειρα μετά
από ολοκληρωμένο rollback χρειάζεται έλεγχο της αιτίας και νέο διακριτό clone.

Αν ολοκληρωθεί το VM αλλά αποτύχει μόνο το τελικό GitHub push:

```bash
python3 tools/preview_s31_release.py record
```

Τα ιδιωτικά αρχεία είναι `private/vm-s31-preview.json`, `vm-s31-restored.json`,
`vm-s31-result.json`, `vm-s31-github-scan.json`. Το root journal βρίσκεται στο
`/etc/accounting/s31-preview-state.json`. Δεν ανεβαίνουν σε GitHub. Δημοσιεύεται
μόνο το νέο `docs/implementation/evidence/S31A-VM-verification.json` και η
συγκεκριμένη S31A κατάσταση/γραμμή βημάτων. Παλιά receipts, bindings, οι 85
acceptance statuses και όλα τα κριτήρια παραμένουν αμετάβλητα.

Μετά την επιτυχία δοκιμάστε στο browser σύνδεση **με τον υπάρχοντα λογαριασμό
και MFA** και τους τιμοκαταλόγους, μηνιαίες χρεώσεις, οικονομικές αναφορές και
PDF/CSV. Η συγκεκριμένη αναβάθμιση παραμένει preview. Αποδοχή πραγματικού
πρώτου γραφείου, D05/D06/D07/G2, πραγματικά έγγραφα και πλήρεις απαιτήσεις
δεν εγκρίνονται από τα τεχνικά αποτελέσματα.
