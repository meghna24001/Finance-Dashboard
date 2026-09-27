"""Checks that picking a country sets the right currency.
Uses a throwaway in-memory database."""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from app import create_app
from config import TestConfig
from models import db, User
from currency_utils import get_countries, format_money

app = create_app(TestConfig)
print("Countries available:", len(get_countries()))

with app.app_context():
    user = User(email="x@example.com", name="X")
    user.set_password("pw12345")
    db.session.add(user)
    db.session.commit()

    for code in ["IN", "US", "GB", "JP", "DE"]:
        user.set_country(code)
        db.session.commit()
        print(f"{code} -> {user.currency} | 100000 shows as {format_money(100000, user.currency, user.country)}")
