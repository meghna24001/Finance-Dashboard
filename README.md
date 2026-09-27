# Finance Dashboard

A Flask application for tracking personal finances. The codebase is organized
by responsibility so application entry points, route handlers, shared logic,
and tests are easy to find.

## Project structure

```text
.
├── app.py                 # Flask application factory and CLI commands
├── wsgi.py                # WSGI entry point for web hosts
├── routes/                # Web and API blueprints
├── templates/             # Jinja templates, grouped by feature
├── static/                # CSS, JavaScript, icons, and vendor assets
├── migrations/            # Alembic database migrations
├── tests/                 # Automated test suite and shared test helpers
├── config.py              # Environment-specific settings
├── extensions.py          # Shared Flask extensions
├── models.py              # SQLAlchemy models and model helpers
├── forms.py               # WTForms definitions
├── finance.py             # Shared finance calculations and date helpers
├── bank_import.py         # Bank statement parsing
├── currency_utils.py      # Currency and locale helpers
└── requirements.txt       # Python dependencies
```

The local `instance/` directory is reserved for database files and is
intentionally kept outside the source folders. Do not upload it with
application code.

## Run locally

Create and activate a virtual environment, install dependencies, then start
the development server:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
flask --app app run --debug
```

## Run tests

```powershell
python -m pytest
```

Some scenario checks can also be run directly as modules, for example
`python -m tests.test_auth`. The PDF parser test uses an in-memory statement
fixture and does not require a real account statement in the project.

For deployment instructions, see [DEPLOY.md](DEPLOY.md).
