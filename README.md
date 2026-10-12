# Roomer

A minimal Django starter with a basic home page, Django admin, PostgreSQL, and
python-dotenv. The user model is Django's default auth.User.

Run from the project directory using the existing virtual environment:

```powershell
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py runserver
```

Open http://127.0.0.1:8000/. Admin is at /admin/.

.env contains private database settings and DJANGO_SECRET_KEY; do not share or
commit it. .env.example documents the environment variable names. On a new
machine, configure .env and install requirements.txt into a virtual environment.

The fresh PostgreSQL database is empty. No migrations or superuser were created
during the reset. When ready to initialize this fresh database, run:

```powershell
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py createsuperuser
```

Admin needs those tables before it can be used. Existing databases are preserved;
do not select the previous custom-account database for this starter.
