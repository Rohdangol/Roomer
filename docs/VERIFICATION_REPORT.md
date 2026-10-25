# Local verification — 25 October 2026

Branch: `feature/agreement-consent-approval`. No commit, push or merge performed.

## Results

- Django system check: passed.
- Migration consistency (`makemigrations --check --dry-run`): no changes detected.
- Migration plan: every existing migration is applied locally, including rentals
  0002. No migration was created, applied, reset or faked during this pass.
- Relevant tests: 135 unique tests passed across the initial run and failure-only
  reruns. Initial run: 105 passed, 30 test methods failed (9 assertion failures and
  22 errors, including two failed subtests in one method). First rerun: 27 passed,
  3 failed. Final rerun: those 3 passed. No selected tests were skipped.
- Eleven tests for the superseded separate Owner-finalization agreement flow were
  deliberately excluded: AgreementWorkflowTests (10) and concurrent-finalization
  conflict test (1). Current v2 consent/Admin approval, reservation concurrency,
  legacy upgrade preservation and concurrent submission checks ran instead.
  A broad-suite pass is not claimed; the retired tests still need replacement or
  removal before using unqualified full-suite results.
- Changed Python syntax and 11 changed JavaScript files: syntax checks passed.
- Whitespace review passed. Changed/untracked text inspection found no credential
  patterns or accidental private/uploaded files. This is not a specialist security
  audit. `.env` and private/upload directories are untracked/ignored.

## Isolation and coverage

The runner used a unique `test_roomer_final_<process>` PostgreSQL database with an
explicit assertion that its name differs from development. Django created and
destroyed only this test database. FileFields used in-memory storage or existing
test temporary directories. External geocoding was blocked/mocked and email used
Django's test backend. Before/after fingerprints confirmed development model
records, `.env`, uploads and private identity files were unchanged.

Coverage included role access, participant ownership, request validation and
cancel/reapply, duplicate submission, atomic acceptance/reservation/draft,
version-specific consent/revision/read-only rules, staff approval/return,
activation/completion/idempotency/conflicts, geographic eligibility/inclusive
boundaries/weighted scoring/card-to-details consistency, independent All Available
Rooms, saved-room visibility/history/scoping and notification recipient scoping.

An essential new notification HTTP regression checks Tenant/Owner/Admin read-one
and read-all JSON responses, unread counts, foreign-record rejection, POST-only
behavior, CSRF and normal form fallback. The other fixes update outdated tests:
current-date publication fixtures, current dashboards/routes, removed placeholders,
geographic location credit, independent catalogue, reserved/idempotent acceptance,
existing submission notifications and superseding pending listing revisions.
No production business rule or implementation was changed to satisfy old tests.

## Before the next commit

`rentals/migrations/0002_agreementreview_alter_rentalagreement_options_and_more.py`
is applied locally but still untracked: include it with its model/service changes.
Preserve and leave `accounts/static/accounts/images/roomer.ai` untracked.
No current selected-test failures or migration blockers remain.

## Browser checks still required

1. In separate Tenant/Owner/Admin sessions, exercise their own lists/details and
   verify action visibility; try another participant's URL.
2. Submit via the request modal, then cancel/reapply. Accept as Owner, edit/send
   the draft with consent, request a revision as Tenant, reconfirm and approve or
   return it as Admin. Check double clicks and user-facing validation messages.
3. Autocomplete using keyboard and touch; confirm the marker/radius circle and
   match popover. Open an outside-radius room from All Available Rooms and verify
   it remains readable/requestable without match UI. Test Reset and pagination.
4. Mark notifications read while scrolled: panel stays open, badge updates and
   failed requests offer Retry. Verify Escape/focus return, horizontal row arrows,
   swiping versus save actions, neighbour modal and mobile layout.

No browser automation, live Photon/SMTP delivery, OS scheduler installation or
real-data end-to-end mutation was performed. Scheduler services and management
command transitions were exercised with isolated test dates, not a running OS job.

## Final base/recommendation commit review

- Rechecked Django system checks, migration consistency and applied status:
  passed, no missing migrations, and rentals.0002 is applied locally. Include
  its migration file in the commit for other checkouts.
- Reused the 135-test workflow verification above. Later focused, isolated
  checks passed for navbar/repeated-search ID and score equality, legacy
  location setup, onboarding coordinate persistence, and Profile location
  changes followed by immediate navbar point/filter restoration.
- Updated three stale stylesheet assertions to the consolidated roomer.css,
  and the shared auth branding assertion to the existing logo asset. All three
  affected test methods passed; the shared-layout method passed after correcting
  its obsolete placeholder assertion. No broad suite was run for this review.
- Consolidated CSS was visually compared on nine representative auth, Tenant,
  Owner and Admin pages at desktop/mobile widths during the CSS task. This does
  not verify interactive maps: Leaflet CDN JavaScript did not load in that preview.
  Subsequent preference/autocomplete changes have no claimed browser validation.
- Changed/new file review found no credential patterns, private uploads, caches,
  environment files or generated demo assets. Only the supplied verified.png
  is a new image asset. roomer.ai remains untracked and unchanged.
- Shared handoff: use roomer.css and template scope hooks for future styles;
  use the existing preference services for explicit selected-point saves; keep
  geographic recommendation boundaries separate from All Available Rooms;
  preserve version-specific agreement consent and Admin approval services.

The earlier "Before the next commit" section describes the pre-review state;
the requested commit now includes rentals.0002. Other installations should run
`python manage.py migrate` and retain the every-minute
`python manage.py activate_scheduled_agreements` scheduler job.
