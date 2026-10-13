# Working verification backend ? coordination with Shru

## Migration and ownership

Shru owns accounts migrations and custom Admin integration. The authorized
accounts.0005 migration adds User.email_verified_at/verified_email,
EmailVerificationDelivery, TenantIdentityAttempt and TenantIdentityReview.
It is applied in the current local database; new checkouts must run migrate. Existing users default unverified; existing owner
verification rows/file references are untouched. No applied migration is rewritten.
Run `python manage.py migrate` with the existing venv (also applies any pending
text-only preference migration). No development users/documents were created.

## Registration email proof

`accounts.verification_services.send_verification_email(user, request)` sends a
Django-signed 24-hour link using the configured email backend. Account-locked
issuance persists a SHA-256 nonce digest, one-minute cooldown and five-per-hour
limit before the on-commit mail send. Resend invalidates older unconsumed links.
Delivery failure leaves the account available and rate limits intact.
`confirm_email(token)` checks signature/age, current email and digest under lock,
then records the current verified_email snapshot/email_verified_at and consumes
the delivery state. Reopening a verified link cannot grant new proof or force
reverification. Proof is valid only while the recorded email matches User.email;
registration/login alone never proves ownership. Email remains read-only on
Profile; Django admin proof fields are read-only. No login restriction was added.
GET displays confirmation; the actual verification is a CSRF-protected POST.
Unverified signed-in users can resend; Profile displays the canonical
`email_is_verified(user)` result. Console delivery is acceptable locally.

## Tenant government ID

TenantIdentityAttempt is an immutable submission: user PROTECT; citizenship/NID;
required trimmed document_number; issued_date explicitly AD (not future in Nepal
time); required front/back private files; pending/approved/rejected status;
submission/review timestamps, reviewer PROTECT and rejection reason. A conditional
unique constraint permits one pending/approved attempt per tenant. Rejected
resubmission creates a new attempt; approved/pending documents cannot be replaced.
History retains all previous documents and applied/stale/invalid review attempts.
TenantIdentityReview links attempt/reviewer with PROTECT and records decision,
reason, outcome and time; admin audit rows are read-only.

`submit_tenant_identity(actor, details)` accepts only the five document fields,
checks active tenant permissions, locks the account and validates the attempt.
`review_tenant_identity(actor, attempt_id, decision, reason="")` requires active
staff with accounts.change_tenantidentityattempt, locks the attempt, records the
review audit, and applies only a pending approve/reject (reason required on reject).
Shru's custom Admin must call these services instead of saving statuses directly.
Existing Django admin exposes private downloads and these review controls now.

Uploads are decoded JPEG/PNG only, up to 5 MB per side, with matching format,
nonanimation and decompression protection. Owner PDF support is unchanged; tenant
PDF uploads are deliberately not accepted without an actual-content PDF validator.
Reuse PrivateDocumentStorage/random paths, with own-submitter or staff view/change
permission download checks; attachment responses use no-store/nosniff. No public
media/static identity URL exists. Government ID remains optional for tenant access.
Profile derives Not Submitted/Pending/Verified/Rejected from its latest own attempt,
shows rejection reasons/history and counts only persisted email and approved ID.

## Email configuration

Existing defaults: console EMAIL_BACKEND and local DEFAULT_FROM_EMAIL.
For inbox delivery configure EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend,
EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, DEFAULT_FROM_EMAIL,
EMAIL_USE_TLS and EMAIL_USE_SSL in the private environment. Use the provider's
settings; do not enable TLS and SSL together. No SMTP credentials are installed.
Keep production host/HTTPS configuration appropriate for verification-link URLs.

## Checks and limits

Django configuration check passed. Four focused security checks ran in an
isolated PostgreSQL test database: signing/expiry/throttling/proof, private
ownership/history, invalid uploads/administrative-field rejection, and Profile
upload/email-confirmation CSRF. Temporary file storage was used; no development
uploads/accounts created. Owner immutable-history extension remains deferred
as described in DATA_MODEL.md, separate from these new tenant attempts.
