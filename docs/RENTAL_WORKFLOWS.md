# Rental request and agreement workflows

This contract supersedes the older Owner-finalization flow for new workflow-v2
agreements. Shared migration/service owner: Shru; this change is explicitly
user-authorized. No applied migration is rewritten.

## Requests and reservation

Active tenants submit required move-in date, total occupancy (including the
tenant), message and confirmation. Existing availability, capacity, duplicate,
identity-approved owner and Nepal-date checks remain in submit_request.
Pending requests alone may be cancelled by their tenant or rejected/accepted by
the verified owner. Reapplication after rejection/cancellation creates a record.

`decide_request(owner, request_id, "accept")` locks listing then request. In the
same transaction it accepts, reserves and calls `create_draft_locked` to create
one agreement/draft version. Retry returns the same agreement. Another accepted
request or binding agreement blocks a competing reservation; existing legacy
accepted-request conflicts require explicit resolution, never automatic rejection.
The acceptance endpoint redirects to Owner Agreement Details.

Draft snapshots preserve requested room/revision, parties, occupancy, move-in,
rent/deposit and supported house rules. Payment due day, end date and additional
terms are left missing; no legal clauses or assumed end dates are generated.

## Versioned party consent and Admin approval

States for v2:
`draft -> awaiting_tenant -> pending_admin -> scheduled -> active -> completed`.
Approval on the start date goes directly from pending_admin to active.
Tenant change request: `awaiting_tenant -> changes_requested`.
Admin return: `pending_admin -> changes_requested`.
Owner revision: `changes_requested -> draft` with a NEW terms version.
Saving an editable draft also creates a new immutable version.

- Only the verified owner may prepare permitted terms in a current draft or
  returned agreement. Parties, room and occupancy are not posted/editable fields.
- `prepare_agreement` requires current terms ID, positive rent, nonnegative
  deposit, due day 1?28, future/today start, end after start and entered terms.
- `send_agreement` requires the current draft and complete terms. The HTTP view
  MUST validate AgreementActionForm's explicit consent checkbox first. It records
  sent_at and owner_accepted_at against exactly this version.
- `confirm_agreement` allows only the owned current sent version, with Owner
  consent already recorded. Its view MUST validate the Tenant consent checkbox.
  It records Tenant consent and moves to Pending Admin Approval; no subsequent
  Owner finalization exists. The old finalize URL fails safely without mutation.
- `request_agreement_changes` requires the tenant's current sent version and a
  nonempty explanation. Owner editing creates a new version; old consent/reasons
  remain historical and do not authorize the replacement.
- `review_agreement` requires active staff with rentals.view_rentalagreement,
  rentals.change_rentalagreement AND rentals.approve_rentalagreement. Approve
  requires both parties' recorded consent to the same current sent version.
  Return requires a reason; staff cannot edit terms through this workflow.
- AgreementReview preserves reviewer, exact version, decision, reason and time.
  Both parties can see review history for versions visible to them. Tenants see
  only sent versions, including their last sent version while the Owner revises.
- Every mutation is POST+CSRF. Services lock listing before agreement/request;
  expected version IDs and state checks reject stale forms and double clicks.
  Basic Django admin is inspection-only for requests, terms and review history.

## Nepal dates, scheduler and availability

All new date comparisons use Asia/Kathmandu. End dates are INCLUSIVE.
Approval with start_date before today is rejected: return for revised dates and
fresh party consent. Admin approval never backdates.

A current approved version with both consents is Scheduled until start_date.
It is Active only while start_date <= today <= end_date; the listing is Occupied.
After end_date the scheduler completes it and releases the reservation/occupancy.
The listing stays Reserved during draft, revision, consent, Admin review and
future approved start. Existing listing availability/archive services block
Reserved/Occupied actions.

Completion restores the availability captured before reservation only if the
listing is still eligible (approved publication, active verified Owner, no
archive). An inactive or admin-restricted listing is never republished as a
completion side effect. Completed records/versions remain readable.

If the scheduler misses the entire rental period, it completes directly without
inventing a historical activation timestamp. Per-record locks/state checks make
repeat or concurrent runs safe; notifications are created only on a transition.
Notifications cover sending, changes, Tenant consent, Admin decisions, activation
and completion. No chat, early termination or accepted-request cancellation is
introduced; those transitions remain undefined and require a separate decision.

## Legacy and migration safety

Migration rentals.0002 adds workflow_version=1 to ALL existing agreements, then
sets the default to 2 for future agreements. Statuses, terms, snapshots, party
consent/finalization times and audit data are retained. No Admin approval is
backfilled. Existing legacy Pending/Scheduled/Active/Completed records remain
readable and labelled legacy; their exclusive end-date interpretation remains.
Legacy active agreements retain explicit Owner/permitted-staff completion under
the prior rule. Legacy scheduling, revision, sending and finalization are NOT
automatically converted to the new consent process; the scheduler skips legacy
records. A separate approved migration policy is needed for those records.

Local pre-change audit: 0 agreements, 0 versions, 1 accepted request. That accepted
request is not silently reserved or converted. Its Owner can explicitly submit
preparation to create a v2 draft if no competing reservation exists.

Apply (after reviewing the handoff):

```powershell
.\venv\Scripts\python.exe manage.py migrate
```

## Unattended setup

Keep the existing management-command name, now handling BOTH activation and
completion. Run every minute, including unattended/missed-run recovery:

```powershell
.\venv\Scripts\python.exe manage.py activate_scheduled_agreements
```

Windows Task Scheduler:
- Program: `D:\Rohan\Study material\6th Sem\Project II\Roomer\venv\Scripts\python.exe`
- Arguments: `manage.py activate_scheduled_agreements`
- Start in: `D:\Rohan\Study material\6th Sem\Project II\Roomer`
- Repeat every minute indefinitely, run whether logged in or not, recover missed
  starts and retain failure logs. No OS task is installed by this code change.

Grant review staff the new approval permission and agreement view/change
permissions using Django admin. Existing staff receive no automatic grants.
Superusers have the permissions already. Console email settings are unchanged.

## Manual verification

1. Submit two pending requests for one room. Accept one as Owner: confirm Reserved,
   automatic draft and redirect. Retrying cannot create another agreement.
2. Supply missing terms/end date. Without consent, sending fails. With consent,
   send; confirm sent version is read-only and Tenant sees full terms.
3. Tenant requests changes with explanation; Owner revises/resends. Verify old
   consent remains in history and cannot confirm/approve the new version.
4. Confirm as Tenant, review in custom Admin. Test return with reason, fresh
   consents, then approval. Approval after start requires updated dates.
5. Future approval is Scheduled/Reserved; run scheduler at start and after end.
   Verify Active/Occupied, Completed, no duplicate notifications and no inactive
   republication. Verify unrelated accounts cannot read or mutate the agreement.
