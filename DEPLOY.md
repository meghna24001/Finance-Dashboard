# Putting Finance Dashboard online (PythonAnywhere)

This walks through hosting the app on **PythonAnywhere**, using their free
account. It needs no credit card, gives you a free `https://` address, and
is one of the easiest hosts to use without knowing Linux server
administration.

**The trade-off:** a free PythonAnywhere web app stops running if you don't
log in for a month. Logging in and clicking one button restarts it — your
data is never affected, only the app "sleeping" — so revisit this page
occasionally if you want the app to always be reachable.

## 1. Create your account

Go to [pythonanywhere.com](https://www.pythonanywhere.com) and click
**Pricing & signup → Create a Beginner account**. No card is asked for.

## 2. Upload your code

1. On the PythonAnywhere dashboard, open the **Files** tab.
2. Click **Upload a file** and upload your project as a `.zip` (zip your
   `finance-dashboard` folder first — but leave out `venv/` and `instance/`,
   since those are your local copies and shouldn't be uploaded).
3. Open a **Bash console** (from the **Consoles** tab, "Bash") and unzip it:
   ```
   unzip finance-dashboard.zip
   cd finance-dashboard
   ```

## 3. Create a virtual environment and install packages

Still in the Bash console:
```
mkvirtualenv --python=python3.12 finance-venv
pip install -r requirements.txt
```
(If `python3.12` isn't offered, run `python3 --version` first and use
whichever version PythonAnywhere has installed instead.)

## 4. Create the .env file (your secrets)

Still in the Bash console:
```
nano .env
```
Paste this in, replacing `yourusername` with your actual PythonAnywhere
username (shown in the top-right of the dashboard), then generate a real
secret key:
```
APP_ENV=production
SECRET_KEY=paste-a-real-secret-here
DATABASE_URL=sqlite:////home/yourusername/finance-dashboard/instance/finance.db
CLIENT_IP_HEADER=X-Real-IP
```
To generate the secret key, open a second console (**Consoles → Python**)
and run:
```python
import secrets; print(secrets.token_urlsafe(48))
```
Copy that value into `.env` in place of `paste-a-real-secret-here`. Save
`nano` with `Ctrl+O`, `Enter`, then `Ctrl+X` to exit.

**Never share this file, paste it into a chat, or upload it anywhere
public.** Anyone who has your `SECRET_KEY` could forge sign-in sessions for
your app.

## 5. Create the database

Still in the Bash console:
```
mkdir -p instance
flask db upgrade
```

This creates every table using the migration in your `migrations/` folder —
the same one you've been running locally — so your online database's
structure matches your code exactly.

## 6. Create the web app

1. Go to the **Web** tab and click **Add a new web app**.
2. Choose **Manual configuration** (not "Flask" — that option skips the
   setup this app needs) and pick the same Python version as your
   virtualenv.
3. Under **Virtualenv**, enter:
   `/home/yourusername/.virtualenvs/finance-venv`
4. Under **Code**, set:
   - **Source code:** `/home/yourusername/finance-dashboard`
   - **Working directory:** `/home/yourusername/finance-dashboard`
5. Click the **WSGI configuration file** link. Delete everything in it and
   replace it with:
   ```python
   import sys
   path = "/home/yourusername/finance-dashboard"
   if path not in sys.path:
       sys.path.insert(0, path)

   from wsgi import application
   ```
6. Under **Static files**, add one entry:
   - **URL:** `/static/`
   - **Directory:** `/home/yourusername/finance-dashboard/static/`

## 7. Go live

Click the big green **Reload** button at the top of the Web tab, then open
your app's address (shown at the top of that page, like
`yourusername.pythonanywhere.com`). You should see the sign-in page, already
on `https://`.

Sign up for a real account there and try adding a transaction, to make sure
everything works before sharing the link with anyone.

## Keeping it running

- **Every month:** log in to PythonAnywhere and click **Run until 3 months
  from today** on the Web tab, or the app will pause. (This button's label
  may say a different number of months — click it regardless.)
- **After you change your code:** upload the new files, then click
  **Reload** on the Web tab. If you changed `models.py`, also run
  `flask db migrate -m "what changed"` and `flask db upgrade` in a Bash
  console first (see "Changing the database later" below).
- **Back up your data occasionally:** in a Bash console,
  ```
  cd finance-dashboard
  source /home/yourusername/.virtualenvs/finance-venv/bin/activate
  flask backup
  ```
  This saves a dated copy into a `backups` folder. Download it from the
  Files tab now and then for real safekeeping.

## Changing the database later

If you ever add a new field or table (for example, if we build a feature
that needs one), don't delete and recreate the database — that would lose
everyone's data. Instead, locally:
```
flask db migrate -m "add whatever changed"
flask db upgrade
```
Check the new file created in `migrations/versions/` — Flask-Migrate is good
but not perfect, so it's worth a quick read. Then upload that new file
(everything in `migrations/` needs to be on the host too) and run
`flask db upgrade` there as well, before reloading the web app.

## Checking it's healthy

Visiting `https://yourusername.pythonanywhere.com/healthz` returns
`{"status": "ok"}` when the app and its database are both reachable — handy
for a quick check without signing in.

## If something goes wrong

The **Web tab → Log files** section has an **error log**. Most problems
(a typo in the WSGI file, a missing package, a wrong path) show up there
clearly. `.env` values not taking effect is almost always a path mistake in
step 4 — double-check `yourusername` is your real username everywhere.

## Other hosts

PythonAnywhere was chosen here because it needs no credit card and no
server knowledge. If you outgrow it, this app also works unchanged on any
host that runs Python (Render, Railway, Fly.io, a VPS...) — set the same
environment variables from `.env.example`, run `flask db upgrade` once, and
point the host at `wsgi:application`. Hosts that run your app behind their
own proxy usually also want `TRUST_PROXY=1` set, which PythonAnywhere does
not need.
