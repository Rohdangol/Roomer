# Roomer shared workflows

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
- Preference service requires all four mandatory factors and location coordinates in its complete details dictionary; omitted/empty amenities mean no preference. `create_notification` is an internal workflow helper, not a public creation endpoint.
- Basic admin registrations are view-only; they inspect records without introducing add/edit/delete paths that bypass services. Existing account/verification admin behavior is unchanged.

## Decision status

All five phase-one questions are resolved: automatic first publication, suspension-based visibility, photo limits/actual-content validation and optional amenities, archive-origin protection/restore to inactive, and immutable submission/review history. Technical structures remain labelled as proposals in DATA_MODEL.md, not implemented code.

Nonblocking deferred decisions: rent-estimation method; matching formulas including optional-amenity scoring; detailed request/roommate/agreement/occupancy lifecycle above. Resolve before implementing those calculations/modules; do not guess in phase one.
