"""The entry point a web host uses to run this app.

On PythonAnywhere, the "WSGI configuration file" they give you should contain just:

    from wsgi import application

This file also loads a .env file (see .env.example) if one exists, so secrets
like SECRET_KEY don't have to be typed into the host's configuration screen.
"""
from dotenv import load_dotenv

load_dotenv()  # does nothing if there is no .env file (e.g. on your own computer)

from app import create_app  # noqa: E402 (must come after load_dotenv)

application = create_app()
