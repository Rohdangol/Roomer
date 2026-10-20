# Roomer shared workflows

**Rental implementation update:** the later authorized request/agreement rules,
implemented services, statuses, permissions and scheduler setup are documented in
[RENTAL_WORKFLOWS.md](RENTAL_WORKFLOWS.md). That document supersedes the deferred
rental sections below, including optional-message and unresolved-lifecycle notes.

Read with DATA_MODEL.md. Confirmed requirements come from the supplied specification/ER/wireframes and the user's later decisions. The latest instruction authorizes the first-phase listings/preferences/notifications implementation; verification-history and rental/calculation sections remain future contracts.

## Phase one and role boundaries

Phase one: listing publication/revisions, amenities/photos, tenant preferences and in-app notifications. Requests, agreements, rental records and known-roommate requests are documented only. No discovery/matching of strangers, custom dashboard/module implementation, or rent-estimation formula is authorized by this planning step.

- Tenant: view eligible published listings, maintain own preferences, read own notifications. Existing tenant access does not require identity approval.
- Owner: manage own listings/revisions and submit identity; owner identity approval remains required before normal home/owner access, and before listing publication submission. Cannot approve own listing/verification.
- Admin: active Django staff with appropriate model permissions, not a public third role choice. Review verification/listing revisions. Historical party records must survive normal suspension/deactivation.
- Account suspension (`is_active`), identity status, listing availability and revision approval are independent states. Navigation is not permission enforcement; every future view/service must authorize its user and target record.

## Existing account and verification flow

Registration -> ordinary Tenant/Owner user -> login. Login destinations: Tenant area; approved Owner area; unapproved owner verification; staff Admin entry. Unknown/wrong/inactive credentials use the same generic error. Username remains internal; Django admin username login is retained. Logout is CSRF-protected POST only.

Confirmed target flow: first submission creates pending attempt 1; admin pending -> approved/rejected with reviewer/time and append-only review audit; rejection needs a reason. Resubmission after rejection creates a new pending attempt and updates the stable record's current_attempt under a lock. Never overwrite old documents, decisions or reasons. Pending/approved attempts cannot be replaced. Every authorized review submission is audited: applied reviews update status; stale/invalid attempts preserve the decision and show the appropriate validation error. Historical documents remain private downloads identified by immutable attempt ID.

Current implementation remains one mutable record with destructive FK deletion semantics. Extend it using DATA_MODEL.md's preservation plan: keep stable record IDs, backfill surviving submission/review values and unchanged document paths into immutable history, add current_attempt and protect historical party references. Verify before switching callers or retiring redundant columns. Previously overwritten history cannot be fabricated. This specification implements no migrations and does not duplicate status on an OwnerProfile.

## Listing creation and first publication

1. Owner creates stable RoomListing plus draft ListingRevision; operational status initially inactive is a technical proposal, not yet an implemented default.
2. Edit complete content, including amenities/photos, in the draft. All management timestamps remain read-only. First photo by position is the cover.
3. Owner submits: validate owner identity, ownership, required fields, complete content and upload policy; lock listing and freeze revision; draft -> pending. Submission expresses intention to publish. Require 1–10 photos, <=5 MB each, verified/decoded as nonanimated JPEG/PNG/WebP; drafts may have none. Reject SVG, animation and invalid/mismatched content.
4. Admin reviews the immutable snapshot with model permission: pending -> approved/rejected. First approval records reviewer/time, atomically sets published_revision/publication timestamp and makes it available, with no extra activation step. Recheck publication/photo requirements. Rejection records reason/time and never sets published_revision.
5. Public visibility requires approved published_revision + available + not archived + active owner. Approval does not clear archive/suspension restrictions; records remain hidden if otherwise ineligible.

No user-provided owner/reviewer/status/timestamp/published-pointer values may bypass these services. No public listing before initial approval.

## Editing an already published listing

Confirmed substantive changes: price, location, availability date/details, amenities, photos, and rules. Proposed safe interpretation: all editable revision content is reviewed, avoiding accidental unreviewed publication of title/description/capacity changes.

1. Copy published content, amenity associations and photo references into a new draft/version. Do not mutate the approved snapshot.
2. Edit draft only. Files referenced by the approved snapshot stay intact. Draft revisions are never used by public search/detail pages.
3. Submit draft -> pending under listing lock. Proposed rule: one draft and one pending revision at most; pending content cannot change.
4. While pending, the previous approved version stays publicly visible if its operational availability allows it. Never hide it merely because a revision is pending, and never mix old/new fields.
5. Approve: validate/review submitted version, lock listing/revision, atomically swap published_revision and audit timestamps. Old snapshot remains retained.
6. Reject: keep published_revision unchanged; retain rejected snapshot/reason. Further corrections create another draft rather than overwriting rejection history.

An admin decision must identify the submitted version and reject stale review submissions. Subsequent revision approval must not reactivate a previously published listing deactivated while pending; automatic availability applies to first approval only. Whether new details may contradict an active tenancy needs a future rental-module decision; agreed rental terms never change automatically.

## Activation, deactivation, archive and occupancy

Confirmed: available -> inactive is allowed; inactive -> available is allowed; activation/deactivation alone does not require another approval. No activation may expose unapproved content. Deactivation of an occupied listing under an active agreement is forbidden, including admin management actions.

Confirmed archive/suspension rules and technical enforcement:
- Activation uses existing published approved content; it cannot approve a draft or activate an archived listing before restore.
- Owner changes operational availability only on own listing. Admin deactivation for policy violations is supported by wireframe p26, but may not evade occupancy protection.
- Active-agreement transitions later own occupied status; users must not set occupied through arbitrary field edits.
- Owner may archive own listings; admin with management permission may archive listings. Retain archive time/actor/origin. Archive hides without deleting history or changing approval. Persist admin origin independently of later actor-role changes.
- Owner may restore an own owner-origin archive; admin must clear an admin-origin archive. Restore clears archive metadata and sets availability to inactive, preserving approval/published revision. Further activation/publication requires eligibility. An admin-imposed restriction cannot be cleared by the owner.
- Suspending an owner hides their listings and blocks new applications without changing approval, availability or archive states. Unsuspension restores visibility only when otherwise eligible; it does not activate inactive listings or publish drafts.

**Confirmed phase-one safeguard:** until rental agreements exist, block deactivation and archival of every occupied listing for owner and admin alike. Do not expose occupied-state changes or fake an always-false agreement check. Once agreements are implemented, enforce the active-agreement restriction using the same listing lock as rental activation/deactivation/review; do not claim completed rental integration in phase one.

## Preference setup and room matching

Tenant creates/edits one own preference record, saving required location, maximum budget, room type and furnishing plus optional amenities together. No selected amenities means no amenity preference, not an incomplete record. Missing preference record means not configured. Validate coordinates and positive budget; fixed choices/catalog are in DATA_MODEL.md. This decision supersedes the source's compulsory-amenities statement.

Matching is dynamically ranked with `0.30L + 0.30B + 0.15A + 0.15R + 0.10F`. It is not a rent estimator. No stored Recommendation entity. Score normalization, factor calculations and optional-amenity scoring remain unresolved; do not invent a zero penalty or weight redistribution. Preference storage can proceed independently of calculation.

## Rent estimation (deferred)

The supplied workflow says to store the suggested amount, method/model version and generation timestamp, never change actual monthly rent, and never assume ML exists. It supplies no calculation method, dataset, coefficients or model artifact. The wireframes do not provide one either.

Document the suggestion as unavailable until a genuine method is agreed. A listing with only actual monthly_rent remains fully usable. Do not generate dummy suggestions or reuse room-matching scores as prices. When implemented later, calculate for a specified input revision and persist an immutable estimate/audit record.

## Rental requests and known-roommate requests (deferred)

Confirmed future flow:
1. Active Tenant requests an eligible available room; capture the published content revision and optional known roommate details.
2. Block duplicate pending requests for the same tenant/listing; validate `1 + occupants included` against capacity.
3. Listing Owner reviews the entire request, including roommate details; may accept/reject the rental request and approve/reject roommate requests. No roommate account is necessary.
4. Accepted request may proceed to an agreement. Request acceptance is not itself tenant/owner agreement acceptance.

Outstanding before implementation: required message/move-in fields; cancellation/expiry/reapplication transitions; whether accepting reserves availability; whether all proposed roommates must be approved; when a tenant may add/change roommates; handling multiple accepted requests. Do not infer these from screenshot example dates or generic status filters.

## Agreements and occupancy history (deferred)

Accepted request -> owner prepares immutable agreed rent, deposit, dates, terms, roommates and due-day terms -> both parties accept the same version -> active -> completed. pending/active/completed are supported by wireframes; rejection/cancellation/early termination rules are not defined.

- Validate listing/tenant/owner against request, approved roommates against the same request, capacity, positive rent/nonnegative deposit and valid dates.
- Activation requires both acceptance timestamps, eligible parties/listing and no overlapping active agreement. Lock listing before checking/activating so competing decisions cannot both succeed.
- Define interval boundaries/open-ended dates and a PostgreSQL constraint before implementing overlap enforcement; not merely an unlocked `.exists()` check.
- Agreement terms are snapshots. A listing revision or changed asking price cannot mutate an active/historical agreement.
- Active agreement -> occupied listing; move-in/move-out tracked by RentalRecord. Completion/release timing and future booking versus current occupancy semantics remain unresolved.
- Existing occupancy restriction applies to normal and admin deactivation. Referenced users/listings/requests/agreements/roommates must be protected from hard deletion.

## Notifications

Persist recipient/title/message/read flag/timestamp for real supported events. Future wireframe examples include request submitted/accepted, agreement ready/finalized; do not implement those events before their workflows exist. Phase-one listing/verification decisions may notify their affected owner using committed outcomes.

Notification creation must occur in the same transaction as its database decision, or after a successful commit; never notify an approval that rolled back. Reading/mark-all-read scopes by the authenticated recipient, uses CSRF-protected state-changing requests, and cannot alter other users' notifications. Existing computed verification hints must not masquerade as persisted unread counts. Shared messages remain transient Django messages.

## Required service contracts for future views/admin

The phase-one services now live in `listings/services.py`, `preferences/services.py`, and `notifications/services.py`. Verification-history and rental service rows below are deferred, not implemented functions:

| Contract | Must enforce |
|---|---|
| published_listings() | Read approved snapshots with available/not-archived/active-owner eligibility; never pending fields. |
| create_listing()/save_listing_draft() | Active owner, own target, fixed choices/required content, immutable published snapshot, version allocation and amenity/photo changes together. |
| submit_listing_revision() | Verified owner, own draft, validation, frozen snapshot, uniqueness of pending submission. |
| review_listing_revision() | Admin permission, pending/stale version and photo check; atomic pointer swap; first approval available, later approvals preserve availability/archive. |
| change_listing_availability(actor, listing_id, action) | Actions activate/deactivate/archive/restore; actor/ownership, approval eligibility, archive-origin protection, restore to inactive and occupied-state guard until agreement integration. |
| save_tenant_preference() | Active tenant, own record, four required factors plus optional amenities saved atomically. |
| submit_verification_attempt()/review_verification_attempt() | Stable-record lock, immutable submission/review audit, current pointer ownership, valid transitions and private historical downloads. |
| mark_notifications_read(actor, notification_id=None) | Recipient-only mutation; omitted ID means own unread records; future views require CSRF-protected POST. |
| future request/roommate/agreement services | Party ownership, supported transition, capacity, required approvals/acceptances, listing locks and overlap/history rules. |

Future public views and basic/custom admin mutations must use these contracts; calling ModelForm.save(), QuerySet.update() or bulk updates directly must not bypass them. Database constraints supplement, not replace, role/object authorization. Lock in consistent order (listing, revision/request/agreement); publish pointers, statuses, joins and audit metadata must be updated transactionally. File operations need explicit retention/rollback handling because filesystem writes are not rolled back by database transactions.

Implementation usage for the two developers:
- `create_listing(actor, **details)` returns the initial draft revision. `create_listing_draft(actor, listing_id)` copies published (or last rejected) content into a new version.
- `save_listing_draft(actor, revision_id, details, amenity_ids=None)` accepts only content fields; omitted amenities preserve associations and an empty list clears them. Use `add_listing_photo`, `remove_listing_photo`, and `reorder_listing_photos` for draft photo mutations.
- Submission and review must use `submit_listing_revision` and `review_listing_revision`; the revision ID identifies the frozen submitted version. These narrow locked services intentionally use QuerySet.update for transitions because normal save() rejects submitted-record edits.
- Availability changes go through `change_listing_availability`; never set occupied manually in public/admin views. Agreements must later integrate a real active-agreement check with the existing lock, replacing the phase-one conservative occupied guard.
- Browse through `published_listings()` and render only `published_revision` and its amenity/photo associations. Apply the same eligibility to future new applications and photo downloads.
- Preference service requires all four mandatory factors; coordinates are optional as a pair (omitted values default to null); omitted/empty amenities mean no preference. `create_notification` is an internal workflow helper, not a public creation endpoint.
- Basic admin registrations are view-only; they inspect records without introducing add/edit/delete paths that bypass services. Existing account/verification admin behavior is unchanged.

## Decision status

All five phase-one questions are resolved: automatic first publication, suspension-based visibility, photo limits/actual-content validation and optional amenities, archive-origin protection/restore to inactive, and immutable submission/review history. Technical structures remain labelled as proposals in DATA_MODEL.md, not implemented code.

Nonblocking deferred decisions: rent-estimation method; matching formulas including optional-amenity scoring; detailed request/roommate/agreement/occupancy lifecycle above. Resolve before implementing those calculations/modules; do not guess in phase one.


## Find Rooms nearby search (agreed)

Tenant map selection supplies latitude/longitude through GET parameters. Nearby
search defaults to 2 km; supported radius choices are 1, 2 and 5 km. Use Haversine
spherical distance (mean Earth radius 6371 km), including rooms at the boundary.
Combine with text location, budget, room type, furnishing and all selected
amenities before counting/pagination. Read coordinates only from the eligible
published revision. Exclude missing coordinates only when a point is selected;
normal search remains unchanged without a point. Validate paired finite
coordinates within latitude -90..90 / longitude -180..180 and the allowed radius
server-side. Preserve selection/radius in GET and pagination; Reset clears both.
Geolocation runs only on explicit user action. No external geocoding is used.
Leaflet loads from a pinned CDN; OpenStreetMap supplies attributed map tiles.


## Saved Rooms (subsequently authorized)

Active tenants save/remove only their own bookmarks through CSRF-protected POST.
Use `saved_rooms.services.save_room` (idempotent, unique tenant/listing, eligible
published listing required) and `remove_saved_room` (own tenant scope, permitted
for unavailable listings). Browse saved records newest-saved first, six per
page; count includes unavailable bookmarks. Resolve visible content only through
`published_listings`/shared search services; unavailable entries expose no title,
photos, owner or draft fields. Preserve local listing-page query parameters on
return; reject external/arbitrary redirects. No public save state or demo data.


## Tenant rental requests: confirmed rules and pending backend

This later decision authorizes Tenant page layouts, not creation of the rentals
app/migration. Shru (Admin/shared developer B) owns the rentals migration chain.
Earlier unresolved move-in/message, occupancy and cancellation questions above
are resolved as follows; owner decision/agreement rules remain deferred.

- Preferred move-in date is required. Compare against today's date in
  Asia/Kathmandu (Nepal time), and against the captured published revision's
  available_from when present. It must be on/after both dates.
- Message is optional. Occupancy is an explicit total including the tenant:
  minimum 1, maximum the published revision's maximum_occupants. No roommate
  identities or roommate records are collected in this step.
- Submission rechecks active tenant and eligible listing through
  published_listings(), locks the stable listing, and captures its current
  approved revision. Pending or accepted requests for the same tenant/listing
  prevent another submission, including concurrent submissions.
- Tenant cancellation is pending -> cancelled only. Lock and scope by the
  authenticated tenant. Preserve the original record. Cancelled/rejected
  requests permit a new application, rechecking all submission conditions;
  accepted requests do not. No reopening, deletion, expiry or auto-reservation.
- Request-submitted notifications target the listing owner via the existing
  create_notification helper in the submission transaction. Cancellation
  notifications are not specified; do not invent them. Owner decisions and
  agreements are not implemented in this Tenant step.
- Until those models/services exist, My Requests has disabled status filters,
  an explicit unavailable state, and no fabricated counts/records/pagination.
  Request Details has a reusable layout only, with no record URL exposed.
  Send Request remains disabled and there is no fake submission success.

### Required handoff to Shru (no migration created)

Create RentalRequest in rentals, using AUTH_USER_MODEL:

| Field | Required schema |
|---|---|
| tenant | User FK, required, PROTECT |
| listing | stable RoomListing FK, required, PROTECT |
| listing_revision | captured approved ListingRevision FK, required, PROTECT |
| preferred_move_in | DateField, required |
| occupancy | PositiveSmallIntegerField, required, total including tenant |
| message | TextField, blank=True |
| status | pending / accepted / rejected / cancelled, default pending |
| requested_at | server-written DateTimeField |
| responded_at | nullable server-written owner decision timestamp |
| cancelled_at | nullable server-written tenant cancellation timestamp |
| rejection_reason | optional TextField; owner rejection requiredness remains deferred |

Add a conditional unique constraint on (tenant, listing) where status is pending
or accepted; status and occupancy >=1 checks; indexes (tenant,status,requested_at)
and (listing,status,requested_at). Capacity/date/revision ownership checks are
cross-record transactional service checks, not duplicated static schema values.
Provide submit_rental_request(actor, listing_id, preferred_move_in, occupancy,
message="") and cancel_rental_request(actor, request_id) enforcing the rules
above. Tenant list/detail reads must scope ownership before resolving data.
Resolve listing/photo/owner display through the existing eligibility contract;
if unavailable, show a neutral summary rather than unpublished fields. Return
request information/status from the owned retained record. Display no private
owner contact or identity documents; an approved identity status alone may
justify an identity badge. Agreement creation remains outside this handoff.


## Tenant agreement layout handoff (backend deferred)

My Agreements is a tenant-only unavailable page with All/Pending/Active/Completed
structure from the wireframe. No agreement models/services exist. No fabricated
count, pagination, record, confirmation timestamp or download is shown. The
agreement_details template provides extension points for an owned agreement's
metadata, authorized listing summary, immutable agreed rent/deposit/due date/
occupancy/duration, permitted party identity, rules, terms and confirmations.
Confirmation/download remain disabled. There is no record-specific details URL
until Shru supplies the rentals backend and ownership-scoped read contract.
Resolve snapshots and historical access deliberately; do not substitute current
listing terms for agreement terms or expose private documents/contact details.
Existing agreement lifecycle questions above remain unresolved. No rentals
models, services or migrations were created in this layout task.


## Home first-search preference onboarding

Home search and popular-area shortcuts are routed through the tenant-only Home
view. Completion requires a saved preference passing model validation, not just
an existing row. Incomplete searches render a CSRF-protected server-side modal;
errors retain the submitted form. Onboarding accepts a text-only location and contains no coordinate controls or
map. Profile keeps optional map/manual coordinates. No geolocation or geocoding
is used.
Location, room type and positive budget are required; furnishing may be Any and
amenities may be empty. Save through save_tenant_preference for the session user.
On success, Find Rooms receives text location, budget, room type, furnishing
(empty search choice for Any), and amenity IDs. Completed Home searches apply
saved factors with the entered location; old coordinates are not applied to a
new text location. Search changes never update the saved profile. Closing saves
nothing. Direct navbar navigation to Find Rooms remains independent. Preferences
migration ownership is Rohan (Tenant developer A); preference-only Any does not
change listing furnishing choices.


Text-only preference clarification: latitude/longitude may both be null, or both
be provided within their existing bounds. Reject one-sided pairs at model/form/
service and database layers. Completion uses full model validation with this
optional-coordinate contract. The service clears stale coordinates when the
area changes with the old point unchanged and no new selection; Profile records
explicit map/manual selection. Onboarding always saves text-only coordinates.
Listing coordinates and Find Rooms nearby radius/Haversine rules are unchanged.
preferences.0003 is applied in the current local database; new checkouts must run migrate. No existing data is rewritten.


## Tenant Profile verification handoff

Registration-only email proof and tenant ID history/review backend are absent.
Profile currently shows honest Unverified / Not Submitted states and 0/2
completed steps, with ID submission controls disabled and tenant access unchanged.
Shru owns the required accounts schema, services, preservation migrations and
admin integration detailed in [TENANT_VERIFICATION_HANDOFF.md](TENANT_VERIFICATION_HANDOFF.md).
No Profile email-verification workflow or tenant upload endpoint is implemented.


## Verification backend implementation (supersedes unavailable-layout notes)

Registration now sends a signed, expiring 24-hour email verification link.
Successful CSRF-protected confirmation persists proof for that email only.
Resend: one-minute cooldown/five per hour; no repeated verification for proven
addresses. Existing users remain unverified. Tenant Profile now submits decoded
JPEG/PNG front/back government IDs privately; pending -> admin approved/rejected;
rejected -> new immutable attempt. Approved/pending replacement is blocked.
Django admin review is enabled; tenant access remains independent of ID approval.
Accounts.0005 is applied in the current local database; Shru owns coordination. New checkouts must run migrate. See
[TENANT_VERIFICATION_HANDOFF.md](TENANT_VERIFICATION_HANDOFF.md) for implemented
schema/service signatures, console/SMTP setup and manual review steps. Old
owner-only overwritten history cannot be reconstructed and remains unchanged.
