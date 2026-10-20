# Implemented rental workflows

This supersedes the deferred request/agreement contracts in WORKFLOWS.md and
DATA_MODEL.md. The subsequent user decisions authorize the `rentals` app and
its migration chain. There were no existing rental models to reuse.

## Requests

Active Tenants submit from an eligible listing's **Send Request** link. Move-in,
message and explicit total occupancy (including the Tenant) are required.
Move-in must be today or later in Asia/Kathmandu and on/after current listing
availability. Capacity, approved publication, active verified Owner, archive,
availability and binding agreements are rechecked under the listing lock.
Submission captures the approved revision, retaining its content and photos.

Only the Tenant can cancel Pending requests. Only the active, identity-approved
listing Owner can accept/reject Pending requests. Pending/Accepted requests
prevent another application by the same Tenant/listing, including concurrent
submissions; Rejected/Cancelled requests permit a new record. Acceptance does
not reserve the listing, create an agreement or change occupancy. Multiple
accepted requests can be reviewed before one agreement becomes binding.

Tenant and Owner lists show real scoped counts and six records per page.
All includes Cancelled; the other wireframe tabs are Pending/Accepted/Rejected.
State changes require POST, CSRF and explicit confirmation. The service locks
listing before request and rejects stale transitions. Submission/cancellation
notify the Owner; acceptance/rejection notify the Tenant, in the same transaction.

## Agreements

An accepted request has at most one RentalAgreement. Owner preparation creates
an immutable AgreementTerms version with agreed rent/deposit, due day 1–28,
required start/end dates, occupancy, entered additional terms, approved listing
revision/house-rule snapshot and participant name/contact snapshots. No legal
clauses are generated. Roommate identities and payment processing are excluded.

The Owner saves, reviews and explicitly sends a version. The Tenant confirms
that exact version; the Owner then agrees to it through explicit finalization.
The status remains Pending throughout preparation/sending/confirmation.
Editing Pending terms creates another version and requires a new send and
fresh confirmation. Previous versions and their timestamps are retained.
Unsent terms are private to the Owner and authorized Admin; the Tenant can
read only sent versions. Finalized terms cannot be edited.

Finalization with a past start date is rejected. Today activates immediately;
a future start becomes Scheduled and reserves the listing immediately.
Scheduled/Active agreements prevent new requests, acceptance of existing
Pending requests, another finalization, and listing availability/archive actions.
Services serialize these decisions under the listing lock; a database partial
unique constraint also permits only one Scheduled/Active agreement per listing.
This intentionally forbids all advance bookings, even with nonoverlapping dates.

Dates use `[start_date, end_date)` and end must be strictly after start.
The scheduler changes due Scheduled agreements to Active and marks the listing
Occupied. A binding reservation survives account suspension; activation records
the binding occupancy without lifting suspension, archive or publication rules.
Missed scheduler runs catch up on the next run, including overdue agreements.

Only the verified Owner, or active staff with both
`rentals.view_rentalagreement` and `rentals.change_rentalagreement`, may mark
an Active agreement Completed, on/after its end date, confirming vacation of
the room. Tenants cannot complete; early termination is unavailable. End-date
passage alone never releases the room. Completion releases to Available only
with approved publication, active verified Owner and no archive/admin archive;
otherwise it becomes Inactive and preserves the restriction. After completion,
another agreement can start on that same exclusive end date.

Finalization, activation and completion notify both parties atomically.
Sending notifies the Tenant; Tenant confirmation notifies the Owner.
Participant-scoped list/detail/history/download routes retain wireframe layouts,
real status filters/counts and three agreements per page. Admin requires
`rentals.view_rentalagreement`; Admin search filters stored party names or ID.
Finalized downloads are HTML documents containing the binding stored terms,
with private/no-store responses. Photos use record-scoped private endpoints;
staff additionally need `listings.view_roomimage`. Identity documents are never
copied to rental records or exposed through rental endpoints.

## Installation and unattended activation

Apply the new `listings.0005` and `rentals.0001` migrations without resetting
existing data:

```powershell
.\venv\Scripts\python.exe manage.py migrate
```

Run this command through an unattended scheduler **every minute**:

```powershell
.\venv\Scripts\python.exe manage.py activate_scheduled_agreements
```

For Windows Task Scheduler, use:

- Program: `D:\BCA 6th sem\Roomer\venv\Scripts\python.exe`
- Arguments: `manage.py activate_scheduled_agreements`
- Start in: `D:\BCA 6th sem\Roomer`
- Trigger: repeat every minute indefinitely, including when nobody is logged in;
  run as soon as possible after a missed start and retain failure logs.

Use the deployed checkout/virtualenv paths on another machine. A process
supervisor, cron or the hosting scheduler can run the same command. Date
comparisons always use Asia/Kathmandu, independent of the scheduler machine's
timezone. Activation occurs on the first successful run on/after the start date.
The command is idempotent and requires no page visit. It never completes an
agreement or releases a listing. No OS scheduled task is installed by this change.

Grant staff the agreement model permissions through the existing Django Admin
user/group controls. Grant request/terms view permissions only to staff who need
the respective read-only basic Admin pages. No permission is automatically
granted to existing accounts.

## Focused manual sequence

1. Use an eligible listing and two Tenant accounts. Submit with a required message,
   valid date and occupancy. Try a duplicate, past date and excess occupancy.
2. Confirm Tenant/Owner lists, filters, counts, pagination and cross-account denial.
   Cancel a Pending request and reapply; reject another and reapply.
3. Accept as the listing Owner. Prepare and send agreement terms. Confirm as its
   Tenant, then finalize as Owner. Try editing before finalization and verify
   that old confirmation cannot finalize a replacement version.
4. Finalize with today's start to see Active/Occupied. For another free listing,
   finalize with a future start to see Scheduled/Reserved; verify submission,
   pending-request acceptance, competing finalization and deactivation are blocked.
   Verify unattended activation on its start date through the scheduler.
5. On/after the end date, confirm completion as Owner or permitted Admin. Check
   release, retained history, finalized download and both parties' notifications.
   Confirm that Tenant completion and completion before the end date are blocked.
