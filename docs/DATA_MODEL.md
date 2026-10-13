# Roomer shared data model

## Authority and scope

Sources: the supplied Database Architecture and ER Implementation Specification, Roomer Database ER Diagram.png, Roomer Wireframe.pdf (29 pages), existing accounts models/migrations, and the user's subsequent decisions. Explicit user decisions override conflicting diagram/wireframe examples.

**Confirmed** means an agreed requirement or existing implementation. **Technical proposal** means a concrete schema choice for developer review, not an additional business rule. **Unresolved/deferred** means it must not be implemented by guessing.

Phase one: listings with revisions, amenities/photos, tenant preferences, and notifications. Preserve the existing User and OwnerVerification interfaces. Document, but do not implement, rental requests, agreements, rental records, or known-roommate requests. No roommate discovery, reviews, complaints, saved rooms, email verification, password reset, or new profile models in this phase.

The specification was prepared before implementation. The latest user instruction authorizes the phase-one model/service contract below; remaining rental/history/calculation proposals stay deferred.

## Phase-one implementation boundary

Implemented apps: `listings` (five models), `preferences` (two models), `notifications` (one model), with their initial migrations and a five-amenity seed migration. Existing User and OwnerVerification models/migrations are preserved exactly in this step. Verification-history extension is a separate follow-up: current verification resubmission still overwrites its current record until that authorized extension is implemented. Do not present history protection/backfill as completed.

Technical details adopted: inactive initial draft listing; 1-based unique photo positions 1–10; all substantive revision fields reviewed; immutable submitted snapshots; inspection-only Django admin, with future workflow mutations routed through services. `Pillow==12.3.0` was already installed and is recorded in requirements for actual content decoding; no package was installed.

Photo files have no direct storage URL. Future photo delivery must authorize the referenced published revision and public eligibility; do not expose the entire storage directory as public media. Draft photo associations can be removed/reordered without deleting files shared by retained history. External transaction rollback after a successful upload may leave an unreferenced file; controlled orphan cleanup remains a separate maintenance concern and must never delete referenced history.

User/verification deletion and submission-history changes are deliberately not part of these new app migrations. Rental models, matching calculations and rent estimation remain unimplemented.

## Shared conventions

- User relationships reference `settings.AUTH_USER_MODEL`, not a concrete User import or new profile table. Use descriptive `related_name` values.
- IDs: Django BigAutoField. Currency: DecimalField(12, 2), NPR monthly amounts, never floating point. These sizes are technical proposals.
- All timestamps: timezone-aware DateTimeField; workflow timestamps are server-written and read-only in management forms/admin.
- Required text: trim and reject whitespace-only input. Optional text: blank string; optional dates/numbers/FKs: null. Statuses use TextChoices plus database check constraints.
- Validate prices, capacities, coordinate bounds, uniqueness, and status values at the database where possible. Cross-row ownership/workflow checks belong in transactional services and model validation. Django `save()` does not automatically call `full_clean()`.
- Normal account management uses `is_active=False`; normal listing management uses availability changes/archive. Do not hard-delete historical records. File retention/cleanup is separate from FK deletion and must not run silently.

## Existing accounts — `accounts`

### User (confirmed, preserve)

Purpose: account identity and authentication. Inherits AbstractUser, retaining username, hashed password, names, last_login, date_joined, groups, permissions, is_active, is_staff and is_superuser.

| Field | Type / requiredness | Rules |
|---|---|---|
| username | unique CharField(150), required internally | Public signup generates UUID; no public username input. Admin username login remains supported. |
| email | unique EmailField(254), required | Strip/lowercase entire address; unique database `Lower(email)` constraint. |
| full_name | CharField(150), model optional | Required by registration. |
| phone_number | CharField(20), model optional | Required by registration; optional leading +, 7–15 ASCII digits; not unique. |
| role | CharField(10), required, default tenant | tenant / owner only. Admin authority is Django staff/model permissions, not a signup role. |
| profile_picture | ImageField, optional | Added in accounts.0004; nonanimated JPEG/PNG/WebP, actual-content validation, maximum 5 MB. Randomized files under ignored media/profile_pictures; own-tenant authenticated delivery only, no public storage URL. |

Suspension, identity verification, listing approval and listing availability are independent. Suspension does not erase records. Preserve current inactive-user authentication rejection.

### OwnerVerification (confirmed existing interface; history conflict noted)

Purpose: private citizenship/national-ID submission and admin review.

| Field | Type / requiredness | Relationship / validation |
|---|---|---|
| user | OneToOneField(User), required | One current record per owner. Currently CASCADE: conflicts with the new historical-deletion rule below. |
| document_type | CharField(20), required | citizenship / national_id. |
| document | private FileField, required | JPG/JPEG, PNG or PDF, matching signature, <=5 MB; random storage name; never a public media/static URL. |
| status | CharField(20), required | pending / approved / rejected; default pending. |
| submitted_at | DateTimeField, required | Server-written on submission/resubmission. |
| reviewed_at | DateTimeField, optional | Server-written on decision. |
| reviewed_by | ForeignKey(User), optional | Currently SET_NULL; reviewer identity retention conflicts with deletion protection. |
| rejection_reason | TextField, optional generally | Required on rejection; cleared on resubmission. |

Current transitions/actions: owner absent -> pending; admin pending -> approved/rejected; owner rejected -> pending by replacing the current submission. Pending/approved uploads cannot be replaced. Ordinary owners cannot access home/owner routes until approval; tenants need not verify now. Staff navigation remains separate. Authorized reviewers need staff status and view/change permission; downloads are private attachments, also available to the submitter.

**Confirmed required extension, not implemented:** retain every submission and review attempt, and protect submitter/reviewer from deletion. Replace overwriting on resubmission with the history structure below. The existing table and file references must survive migration.

### Verification history extension — `accounts`

Technical structure for the confirmed retention requirement:

- Keep OwnerVerification as the stable one-per-owner identity with its existing primary key. Change user FK to PROTECT. Add nullable `current_attempt` FK(OwnerVerificationAttempt, PROTECT), restricted to this verification's attempts. Current status is derived from that attempt; it must not be independently editable. Preserve the status-reading interface by adapting callers together.
- OwnerVerificationAttempt: id; verification FK(OwnerVerification, required, PROTECT); attempt_number PositiveIntegerField required; document_type/document with existing private-storage validation; status pending/approved/rejected; submitted_at required; reviewed_at optional; reviewed_by FK(User, optional, PROTECT); rejection_reason optional except rejection. Unique `(verification, attempt_number)`; one pending attempt per verification; indexes `(verification, submitted_at)` and `(status, submitted_at)`.
- Submitted document/type/time never changes. One normal pending -> approved/rejected decision finalizes the attempt. After rejection, create a new pending attempt and atomically update current_attempt; never overwrite older documents, decisions or reasons. Pending/approved attempts cannot be replaced.
- VerificationReviewAttempt: id; attempt FK(OwnerVerificationAttempt, required, PROTECT); reviewer FK(User, required, PROTECT); requested_decision CharField approved/rejected (optional if invalid input supplied no recognized decision); rejection_reason TextField optional, required for an applied rejection; attempted_at DateTimeField required; outcome applied/stale/invalid. This append-only audit retains every authorized review submission, including stale/invalid attempts; only applied reviews change status. Validation errors remain visible without fabricating a decision. Do not store raw request bodies or document contents in audit fields. Technical audit choices may be refined before implementation.
- Historical downloads use attempt IDs, with submitter/authorized-reviewer checks. Never resolve a historical document through a moving pointer or expose public media URLs. Do not delete files on resubmission.

Future preservation migration, without rewriting applied migrations:
1. Add history tables and nullable current_attempt while retaining existing columns/rows. Backfill each existing verification into attempt 1, copying exact document path/type/status/timestamps/reviewer/reason. Backfill its existing finalized review as an applied audit entry where metadata exists; set current_attempt. Do not rename/reupload/delete documents or invent missing metadata.
2. Validate counts, values, file references and pointer ownership. Stop on contradictory/incomplete historical metadata. Previously overwritten attempts cannot be reconstructed; only surviving records can be preserved.
3. Switch submission/review/download/access callers to immutable attempts. Preserve existing verification IDs; old document routes may resolve the current attempt, while new history links use immutable IDs. Apply PROTECT to historical references.
4. Only after verified backfill and caller migration, remove redundant current-document/review columns in a separate explicit migration. Preserve the stable record and current-status interface. No reset, history deletion or rewrite of existing migrations.

ER TenantProfile/OwnerProfile/AdminProfile, `email_verified`, duplicated owner verification status and profile address are deferred. Phase-one FKs use User directly; do not copy verification status onto User/Profile.

## Listings — proposed app `listings`

### RoomListing

Purpose: stable listing identity, ownership and live availability. **Confirmed:** content revisions need separate review while old approved content stays public. **Technical proposal:** split ER content fields into ListingRevision so they exist once per version, not on both tables.

| Field | Type / requiredness | Rules / deletion |
|---|---|---|
| owner | ForeignKey(User), required | PROTECT; active owner for mutations; verified before publication submission. |
| published_revision | ForeignKey(ListingRevision), optional | PROTECT; only an approved revision of this same listing. Null until first approval. |
| listing_status | CharField(16), required | available / inactive / occupied. Availability independent of revision approval. Initial status proposal: inactive. |
| archived_at | DateTimeField, optional | Separate archive marker; owner (own listing) or admin may archive. |
| archived_by | ForeignKey(User), optional, PROTECT | Retained archiving actor, required when archived. |
| archive_source | CharField(16), optional when not archived | owner / admin, required when archived; preserves restriction even if actor roles change. |
| published_at | DateTimeField, optional | First publication timestamp, server-written, read-only. |
| created_at, updated_at | DateTimeField, required | Server-written; management timestamps read-only. |

Public eligibility: a published approved revision + available + not archived + active owner. Suspension hides listings and blocks new applications without changing their states; unsuspension restores only otherwise eligible visibility. First approval automatically publishes as available. Later revision approval never overrides intentional deactivation/archive. Restore clears archive metadata and returns availability to inactive, preserving approval; owner cannot restore an admin-origin archive. Until agreements exist, deactivation/archive must reject every occupied listing; afterward enforce the active-agreement restriction.

Constraints: published revision must belong to the listing (transactional service/model validation; plain FK cannot express this); allowed status values; archived_at/archived_by/archive_source must be supplied together or all empty. Proposed indexes: `(listing_status, archived_at)`, `(owner, listing_status)`, `published_at`. FK indexes are supplied by Django.

### ListingRevision

Purpose: complete versioned substantive content, including amenities/photos. A public listing renders only `published_revision`; it must not mix fields from newer drafts/pending revisions.

| Field | Proposed type / requiredness | Rules |
|---|---|---|
| listing | ForeignKey(RoomListing), required, PROTECT | Preserve version history and stable listing references. |
| version | PositiveIntegerField, required | Unique `(listing, version)`; allocated under listing lock. |
| title | CharField(200), required | Nonblank. |
| description | TextField, required | ER description is the wireframe's About this Room; no duplicate about field. |
| city, locality | CharField(100) each, required | Wireframe district/city and area/locality labels. |
| address | CharField(255), required | Detailed address, not a second copy of city/locality. |
| latitude, longitude | DecimalField(9, 6), required | Latitude -90..90, longitude -180..180; used for location matching. |
| room_type | CharField(16), required | single_room / double_room / 1bhk / 2bhk. Display Single Room / Double Room / 1BHK / 2BHK. |
| furnishing | CharField(16), required | furnished / unfurnished. |
| monthly_rent | DecimalField(12, 2), required | >0. Owner's actual asking rent. |
| security_deposit | DecimalField(12, 2), required | >=0; zero explicitly means no deposit. |
| available_from | DateField, required | Substantive availability date, distinct from operational listing_status. No invented future-date-only restriction. |
| maximum_occupants | PositiveSmallIntegerField, required | >=1; future capacity includes lead tenant and roommates. |
| floor | CharField(50), optional | Text accommodates ground/basement/numbered floors without assuming local numbering. |
| bathroom_details | CharField(255), optional | Additional description. Attached Bathroom remains an Amenity; do not persist a duplicate attached-bathroom flag. |
| cooking_allowed, visitors_allowed, smoking_allowed, pets_allowed | BooleanField each, required | Explicit yes/no values; no invented restrictions. |
| quiet_hours_start, quiet_hours_end | TimeField each, optional as a pair | Both supplied or both empty. Overnight intervals are allowed. |
| additional_rules | TextField, optional | Rules beyond explicit flags. |
| approval_status | CharField(16), required | draft / pending / approved / rejected; draft is a technical preparation state. |
| submitted_at, reviewed_at | DateTimeField, optional | Server-written at their respective transitions. |
| reviewed_by | ForeignKey(User), optional, PROTECT | Required reviewer on approval/rejection; retained audit identity. |
| rejection_reason | TextField, optional generally | Required for rejected revision (technical proposal for actionable review). |
| created_at, updated_at | DateTimeField, required | Server-written, read-only. |

Constraints/proposed indexes: unique `(listing, version)`; conditional unique `(listing)` for each of draft and pending; positive rent, nonnegative deposit, capacity and coordinate checks, paired quiet hours; `(listing, approval_status)`, `(approval_status, submitted_at)`. Review metadata/status consistency validated by services/model validation.

Approved/rejected snapshots are immutable; editing creates a draft copied from the currently published version. Pending snapshots are locked. Approval changes the published pointer atomically; prior approved versions remain retained. Owner activation/deactivation never creates a content revision.

Whether editing rent should affect existing pending applications/agreement drafts is deferred with those modules; agreements must keep their own agreed terms. Never overwrite historical agreed rent from a listing edit.

### Amenity and ListingAmenity

- Amenity: id; `name` CharField(80), required, case-insensitively unique. Seed the confirmed catalog: Wi-Fi, Water Supply, Attached Bathroom, Parking, Laundry. Do not invent more choices. Admin catalog maintenance is a proposed permission, not an owner-side taxonomy feature.
- ListingAmenity: id; `revision` FK(ListingRevision), required, CASCADE; `amenity` FK(Amenity), required, PROTECT; unique `(revision, amenity)`. Related names: revision.amenity_links, amenity.listing_links. The ER listing link moves to the revision to preserve approved amenities.
- Owner edits amenities through draft listing edits. Public search reads only the published revision's amenity links. A parent draft can be cleaned up by a controlled service; approved/rejected snapshots and their child links must not be hard-deleted through normal management.

### RoomImage

Fields: id; `revision` FK(ListingRevision), required, CASCADE; `image` FileField, required; `position` PositiveSmallIntegerField, required; `created_at` DateTimeField, server-written. Unique `(revision, position)`; order by position; first image is the cover (wireframe p16). No duplicate cover flag.

Images belong to revisions, not mutable live listings. Copying a revision must preserve prior image references/content; uploads/reorders/deletions affect only the draft. Never overwrite/delete files used by published or retained historical snapshots.

Confirmed photo policy: JPEG, PNG and WebP only; no SVG or animation (including animated PNG/WebP). Decode/verify actual content and format, reject corrupt files and extension/format mismatches; filename/MIME/signature checks alone are insufficient. Each photo <=5 MB; at most 10 per content revision, not across retained history. Drafts may have zero; submission/publication require at least one. Enforce limits in upload/submission/review services and admin paths. Image-decoder dependency is an implementation detail to review before package installation; identity-document rules remain unchanged.

## Tenant preferences — proposed app `preferences`

### TenantPreference and PreferredAmenity

Purpose: store room-matching preferences; location, maximum budget, room type and furnishing are required, while amenities are optional. No stored Recommendation entity.

| Field | Proposed type / requiredness | Relationship / validation |
|---|---|---|
| tenant | OneToOneField(User), required | CASCADE; private configuration, not rental history; tenant role only. |
| preferred_location | CharField(255), required | Human-readable location. |
| latitude, longitude | DecimalField(9, 6), optional, null/blank allowed | Both supplied within listing coordinate bounds or both null; text-only preferences are valid. |
| maximum_budget | DecimalField(12, 2), required | >0; maximum monthly budget only, no minimum budget field. |
| preferred_room_type | CharField(16), required | Same four room-type choices as listings. |
| preferred_furnishing | CharField(16), required | Same two furnishing choices. |
| updated_at | DateTimeField, required | Server-written. |

PreferredAmenity: id; `preference` FK(TenantPreference), required, CASCADE; `amenity` FK(Amenity), required, PROTECT; unique `(preference, amenity)`. Proposed related names: preference.amenity_links, amenity.preference_links. Zero rows means no amenity preference; no fake None amenity. Save required factors and optional amenity selection together transactionally.

The preference record can be absent before setup; saving requires the four non-amenity factors. Tenants manage only their own preferences. No profile join is needed. Optional amenities overrides the source's earlier compulsory-selection statement. Scoring with no amenity preference remains unresolved; do not invent a zero penalty or weight redistribution.

## Notifications — proposed app `notifications`

Purpose: real in-app event messages; existing header verification notices are computed status hints, not persisted unread notifications.

Fields: id; `user` FK(User), required, CASCADE; `title` CharField(200), required; `message` TextField, required; `is_read` BooleanField default False; `created_at` DateTimeField, required, server-written. Proposed related name: user.notifications. Proposed index `(user, is_read, created_at)`.

Transitions: unread -> read; owner/tenant/admin recipient may read only their own records or mark their own notifications read. Servers create notifications for supported workflow events, not arbitrary public users. Recipient notification rows may be removed with an otherwise deletable account: they are not the authoritative agreement/verification history. No unique message-text rule, fake unread counts, external delivery, or notification-link FK is implied by the ER.

## Deferred rental models — proposed app `rentals`

The following contracts record known requirements; unresolved transitions/requiredness must be agreed before their migrations.

### RentalRequest (application)

Fields: id; `tenant` FK(User), `listing` FK(RoomListing), both required PROTECT; proposed `listing_revision` FK(ListingRevision), required PROTECT to identify the approved content requested; `message` TextField (requiredness unresolved); `preferred_move_in` DateField (wireframe p9, requiredness unresolved); `status` CharField choices pending/accepted/rejected plus proposed cancelled (wireframe Cancel Request); `requested_at` DateTimeField required; `responded_at` DateTimeField optional; `rejection_reason` TextField optional except rejection requirement still to confirm.

One pending request per `(tenant, listing)` via conditional uniqueness. Index `(listing, status, requested_at)` and `(tenant, status, requested_at)`. Applicant must be active tenant; listing eligible for requests; owner cannot decide other owners' requests. Do not duplicate occupancy count: derive `1 + included roommates`, unless future requirements explicitly include unidentified occupants.

Known transitions: tenant submits pending; listing owner accepts/rejects pending; accepted may proceed to agreement. Cancellation eligibility/reopening/expiry and whether acceptance reserves a listing are unresolved. Deletion PROTECT preserves applications and their listing/user links.

### Roommate (known roommate request, not discovery)

Fields: id; `rental_request` FK(RentalRequest), required PROTECT; `full_name` CharField(150), `email` EmailField(254), `phone` CharField(20), requiredness to confirm; `approval_status` CharField pending/approved/rejected; `created_at` DateTimeField server-written. No user account/FK required. Index `(rental_request, approval_status)`. Normalize email/validate phone consistently; do not invent global roommate email/phone uniqueness.

Tenant proposes known roommates only within own request; listing owner approves/rejects each roommate request. Whether request acceptance requires every proposed roommate to be approved, and whether new roommates may be proposed after activation, remain unresolved. Never exceed maximum occupants. No stranger matching.

### RentalAgreement

Fields: id; `rental_request` OneToOneField(RentalRequest), required PROTECT (ER 0..1 agreement per request); `listing`, `tenant`, `owner` required ForeignKeys, all PROTECT; `start_date`, `end_date` DateField (end-date optionality unresolved); `monthly_rent`, `security_deposit` DecimalField(12, 2), required; `terms` TextField required; proposed `payment_due_day` PositiveSmallIntegerField required (wireframes p11/p20); `status` pending/active/completed, with cancellation/termination unresolved; `tenant_accepted_at`, `owner_accepted_at` DateTimeField optional; `created_at` DateTimeField server-written.

Agreement party/listing FKs are denormalized historical references from the ER and must agree with accepted rental_request at creation. Currency checks >0 rent/>=0 deposit, valid date interval, due-day range proposal 1..28 needs agreement rather than assuming calendar handling. Index `(listing, status, start_date, end_date)` and party/status indexes.

Both parties must accept the same terms before activation. Only roommates from this request can be attached. Prevent overlapping active agreements for the same listing using locked transition services plus an agreed database constraint/date-boundary contract. Do not assume open-ended tenancy or silently adopt an interval-boundary convention. Rental terms are snapshots and do not change with later listing revisions.

### AgreementRoommate and RentalRecord

- AgreementRoommate: id; `agreement` FK(RentalAgreement), required PROTECT; `roommate` FK(Roommate), required PROTECT; unique `(agreement, roommate)`. Validate same request and approved roommate status; archived agreement composition is retained.
- RentalRecord: id; `agreement` FK(RentalAgreement), required PROTECT; `move_in_date` DateField; `move_out_date` DateField optional; `status` choices/requiredness to confirm. Preserve occupancy history; move-out cannot precede move-in. Exact creation/closure triggers and number of records per agreement remain unresolved. Do not duplicate contract status without defining its different meaning.

## Deferred rent estimation

Confirmed: owner can request a suggested rent; persist amount, method/model version and generation timestamp; never change actual rent automatically. Listings work with no suggested rent. No estimation formula, trained model, dataset, or executable estimation method exists in the supplied text/ER/wireframes. Calculation is unresolved and deferred; never generate dummy estimates.

Future RentEstimate fields: listing FK(PROTECT), owner FK(User, PROTECT), proposed input_revision FK(ListingRevision, PROTECT), estimated_rent DecimalField(12, 2), estimation_method CharField, model_version CharField (optional when no model), created_at DateTimeField. Lengths/method identifiers are deferred. A revision reference prevents displaying an estimate calculated for different listing details. Do not duplicate an estimate as a manually editable recommended_rent; a nullable read-only derived suggestion satisfies the ER's display intent.

Room matching is separate: `S = 0.30L + 0.30B + 0.15A + 0.15R + 0.10F`. Scores are dynamic, not rent amounts. Factor normalization/distance/budget/amenity scoring formulas are not supplied and remain unresolved; do not present the weighted expression alone as an implemented algorithm.

## Deletion contract

| Reference | Policy |
|---|---|
| Stable verification -> owner/current attempt; submission -> verification/reviewer; review audit -> submission/reviewer | PROTECT through future preservation migration; replace existing CASCADE/SET_NULL without losing surviving records. |
| Listing -> owner/published revision/archiving actor; revision -> listing/reviewer | PROTECT; manage through deactivation/archive and retain review snapshots. |
| Revision amenity/photo -> revision | CASCADE for controlled draft cleanup only; no normal hard deletion of approved/rejected history. |
| Amenity referenced by listing/preference joins | PROTECT. |
| Preference -> tenant; preferred amenity -> preference | CASCADE for nonhistorical private preferences. |
| Notification -> recipient | CASCADE; notifications do not substitute for historical records. |
| Request, agreement, roommate, agreement-roommate, rental record -> their parent/party references | PROTECT; suspension/deactivation instead of removing historical parties/listings. |
| Future estimate -> listing/owner/revision | PROTECT. |

## Two-developer ownership and sequence (recommended)

Developer A = Tenant work; Developer B = Admin/shared-schema work. Replace labels with names in team planning; **one migration owner per app**:

| App | Migration owner | First dependencies/work |
|---|---|---|
| accounts | B | Preserve User; extend verification with immutable submission/review history and backfill surviving records before retiring mutable columns. |
| listings | B | Amenity, RoomListing, ListingRevision, ListingAmenity, RoomImage; reviewed publication service. A consumes published-query contract. |
| preferences | A | TenantPreference/PreferredAmenity after the shared Amenity migration. |
| notifications | A | Notification using AUTH_USER_MODEL; B calls agreed event-creation interface. |
| rentals | B, later | Deferred shared lifecycle/models; A implements tenant consumers after agreement. |

Approve revision contract first, then create listings initial migration, then preferences/notifications in parallel. Tenant browsing/preferences and Admin listing review can share the listing schema without competing migrations. Coordinate app dependencies before generating migrations; neither developer edits the other's migration chain. No simultaneous schema variants or rewrites of applied migrations.


## Saved Rooms (subsequently authorized)

App: `saved_rooms`; migration owner: Tenant developer (A). SavedRoom has a
required tenant FK to AUTH_USER_MODEL (CASCADE), required stable RoomListing FK
(CASCADE), and server-written saved_at. Unique (tenant, listing); index
(tenant, saved_at). Bookmarks do not replace protected rental/verification
history. No account/listing model fields change. Normal listing deactivation
or archive retains bookmarks; unavailable bookmarks render no listing content.


## Rental request clarification (later Tenant decision)

See WORKFLOWS.md, "Tenant rental requests: confirmed rules and pending backend",
for Shru's required schema/service handoff. Move-in is required; message optional;
occupancy is an explicit positive total including the tenant (superseding the
proposed derived roommate count for this step). Pending/accepted uniqueness,
pending-only cancellation and new-record reapplication after rejection/cancellation
are confirmed. No roommate identities are collected. No rentals model or
migration was created in the Tenant layout task; migration ownership remains B.


Preference onboarding clarification: preferred_furnishing now supports any /
furnished / unfurnished (preferences.0002). Any is a preference-only choice,
not a listing value. Preference coordinates are optional as a pair after preferences.0003; listing coordinates remain required. See the
Home first-search section in WORKFLOWS.md.


Text-only preference migration ownership: Rohan (Tenant developer A). Migration
preferences.0003 alters only nullable preference coordinates and their paired
constraint; it preserves existing values and is applied in the current local database.


## Authorized verification implementation update

Accounts.0005 (applied in the current local database) implements email_verified_at/verified_email
proof, rate-limited signed email delivery state and immutable TenantIdentityAttempt/
TenantIdentityReview models. This supersedes previous tenant/email unavailable
notes. Exact fields, constraints and shared services are documented in
TENANT_VERIFICATION_HANDOFF.md. Shru owns accounts migrations. Existing
OwnerVerification is preserved; its separate history-backfill proposal remains
deferred. Tenant government ID is optional for access; email proof follows
successful link confirmation only, never registration/login.
