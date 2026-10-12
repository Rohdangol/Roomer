# Roomer

Roomer uses Django 5.2, PostgreSQL and the custom `accounts.User`. Registration,
email login, logout, owner document verification and protected role entry pages
exist. Shared listing/revision, preference and notification models/services exist;
their module pages and custom Admin UI are still to be built.

## Windows local setup

Use Python 3.13 (the tested version) and a running PostgreSQL server. Run these
PowerShell commands from the repository root on a new checkout:

```powershell
py -3.13 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

On an existing checkout, reuse `venv` and `.env`; do not overwrite them.

For a new local database, open `psql -U postgres` (or the SQL tool in pgAdmin)
using your local PostgreSQL administrator. In psql:

```sql
CREATE ROLE roomer_dev LOGIN CREATEDB;
\password roomer_dev
CREATE DATABASE roomer_dev OWNER roomer_dev;
```

`\password` prompts privately; set your own password. The local development role
needs CREATEDB for Django's isolated test database. Use a separate local database
per developer; do not point this checkout at an old incompatible Roomer schema.

Edit `.env` privately. Required variables: `DJANGO_SECRET_KEY`, `DB_NAME`,
`DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`. Match the database/role/password
you created; local host/port are normally `localhost` and `5432`. Replace the
secret-key placeholder with a securely generated Django secret key.

Optional: `EMAIL_BACKEND` and `DEFAULT_FROM_EMAIL`; defaults/example use console
email delivery and a local sender. No SMTP or email/OTP verification is set up.

```powershell
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py createsuperuser
.\venv\Scripts\python.exe manage.py runserver
```

Create the superuser interactively only if needed; never put passwords in code
or chat. Public login uses email; Django admin also accepts the internal username.
Open http://127.0.0.1:8000/ and http://127.0.0.1:8000/admin/.

Owners submit citizenship/national-ID documents for manual Django-admin review
before entering their account area; tenants can continue without verification.
Identity files stay under ignored `private_identity/` with authorized downloads.
Listing photos stay under ignored `media/listing_photos/`; published-photo delivery
pages are not built yet. New shared-model admin registrations are inspection-only.
Verification attempt-history extension remains a documented follow-up.

## Collaboration

- Project owner: Tenant pages. Other developer: custom Admin pages.
- Coordinate shared models/migrations, settings, root/app URLs and the shared
  Outfit/Manrope teal theme before editing overlapping files.
- One migration owner per app: Admin/shared developer owns `accounts` and
  `listings`; Tenant developer owns `preferences` and `notifications`. Reconcile
  dependencies before generating migrations; never rewrite applied migrations.
- Work on feature branches and open pull requests; review shared contracts before
  merging. Follow [AGENTS.md](AGENTS.md).
- Contracts: [data model](docs/DATA_MODEL.md) and [workflows](docs/WORKFLOWS.md).
  Future views must call the documented services; deferred rental/price algorithms
  must not be guessed.

## Handoff checks

```powershell
.\venv\Scripts\python.exe manage.py test accounts core listings preferences notifications --noinput
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

Tests use an isolated PostgreSQL test database. `.env`, virtual environments,
local databases, uploads and generated static files are excluded from Git;
`.env.example` contains setup placeholders only. Review exclusions before a PR.
Google Fonts is used by the agreed theme; a browser needs internet for those fonts.
