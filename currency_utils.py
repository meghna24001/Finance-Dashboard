from babel import Locale, UnknownLocaleError
from babel.numbers import format_currency, get_territory_currencies

# Babel also lists a few regions that are not real countries. We skip them.
NOT_COUNTRIES = {"EU", "AC", "DG", "EA", "IC", "TA"}


def get_countries():
    """Return a sorted list of (code, name) pairs, e.g. ("IN", "India"), for a dropdown."""
    names = Locale("en").territories
    pairs = []
    for code, name in names.items():
        is_country_code = len(code) == 2 and code.isalpha()
        if is_country_code and code not in NOT_COUNTRIES and get_territory_currencies(code):
            pairs.append((code, name))
    return sorted(pairs, key=lambda pair: pair[1])


def currency_for_country(country_code):
    """Return the current currency code for a country, e.g. "IN" -> "INR"."""
    currencies = get_territory_currencies(country_code)
    return currencies[0] if currencies else "USD"


def format_money(amount, currency_code, country_code):
    """Format an amount the way that country writes it, e.g. 100000 -> "₹1,00,000.00"."""
    try:
        locale = Locale.parse(f"en_{country_code}")
    except (UnknownLocaleError, ValueError):
        locale = Locale("en")
    return format_currency(amount, currency_code, locale=locale)
