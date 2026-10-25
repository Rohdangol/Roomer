# Agreement workflow handoff for Shru

Branch: feature/agreement-consent-approval. Prepared for the requested base and
recommendation commit. Canonical rules: [RENTAL_WORKFLOWS.md](RENTAL_WORKFLOWS.md).

Shared edits: rentals models/services/forms/views/admin/management command;
listings/services.py reservation/availability guard;
accounts URL additions; existing party/Admin agreement templates and shared
rental styles. One new rentals.0002 migration; never rewrite rentals.0001.

Apply `.\venv\Scripts\python.exe manage.py migrate` after review. Grant staff
view_rentalagreement, change_rentalagreement and approve_rentalagreement; Admin
review buttons are wired in the existing custom Agreement Details interface.
Party forms require consent/terms_id; reasons are required for changes/return.
Future custom views must call the same services, never update consent/status
columns directly. Services own transactions, lock ordering and version checks.

The existing every-minute activate_scheduled_agreements command now performs
activation AND completion. Legacy workflow=1 is excluded; do not infer approval
or reschedule/convert legacy records silently. Local audit found no agreements
and one accepted request, which is left untouched. Accepted legacy requests
without agreements can be explicitly prepared after resolving any conflict.

No early termination or accepted-request cancellation policy exists. Those
buttons/transitions remain absent. Preserve reservations while revisions wait.


Validation: Django system check and missing-migration check passed. Migration
plan contains only rentals.0002. Eleven focused isolated PostgreSQL checks passed
across targeted runs: consent/history, staff/ownership/CSRF, concurrent acceptance
and approval, date boundaries/catch-up, legacy upgrade preservation and listing
reservation guards. No broad suite or browser checks were performed. The migration is applied locally as of the final pre-commit check; other
checkouts must run the migrate command above.
