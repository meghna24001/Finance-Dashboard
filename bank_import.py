"""Local parsers for bank statements.

The public entry point is :func:`parse_statement`.  Parsers return dictionaries
with a small, format-independent schema so callers do not need to know whether
the source was an SBI PDF or an Excel export.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class BankImportError(Exception):
    """Base class for statement import failures."""


class UnsupportedFormatError(BankImportError):
    """The supplied file extension is not supported."""


class MissingDependencyError(BankImportError):
    """An optional parser dependency is not installed."""


class StatementParseError(BankImportError):
    """The file could be read but no statement rows could be parsed."""


class StatementPasswordError(BankImportError):
    """A password was required or did not unlock the statement."""


_ALIASES = {
    "date": (
        "date", "txn date", "transaction date", "tran date", "posting date", "posted date",
        "booking date", "booked date", "post date", "value date", "effective date",
        "operation date", "activity date", "transaction date", "fecha", "fecha operacion",
        "data operazione", "buchungstag", "buchungsdatum", "transactiedatum",
        "boekdatum", "datum",
    ),
    "value_date": ("value date", "value dt"),
    "description": (
        "description", "transaction description", "narration", "particulars",
        "transaction particulars", "remarks", "details", "transaction details",
        "memo", "payee", "merchant", "counterparty", "beneficiary", "libelle",
        "buchungstext", "verwendungszweck", "concepto", "descripcion", "motif",
        "descrizione", "descricao",
    ),
    "reference": (
        "ref no", "reference number", "reference", "transaction reference",
        "cheque no", "chq no", "instrument", "confirmation number", "referenz",
        "numero de referencia",
    ),
    "debit": (
        "debit", "debits", "withdrawal", "withdrawals", "debit amount",
        "withdrawal amount", "money out", "paid out", "outgoing", "payment amount",
        "expense", "expenses", "dr", "soll", "belastung", "cargo", "cargos",
        "adeudo", "addebito", "retiro", "retrait", "levantamento", "saida", "debe",
    ),
    "credit": (
        "credit", "credits", "deposit", "deposits", "credit amount",
        "deposit amount", "money in", "paid in", "incoming", "received",
        "income", "cr", "haben", "gutschrift", "abono", "ingreso",
        "accredit", "accredito", "deposito", "entrada", "haber",
    ),
    "amount": (
        "amount", "transaction amount", "txn amount", "value", "montant",
        "betrag", "importe", "valor", "importo",
    ),
    "balance": (
        "balance", "closing balance", "available balance", "running balance",
        "solde", "saldo", "kontostand",
    ),
    "transaction_type": (
        "type", "transaction type", "transaction code", "debit credit",
        "credit debit", "dr cr", "cr dr", "direction", "transaction direction",
        "soll haben",
    ),
    "account_number": (
        "account number", "account no", "account #", "account id", "acct no",
        "acct number", "a c no", "iban", "iban number", "numero de cuenta",
        "numero de compte", "kontonummer", "numero conto",
    ),
}


def _clean_header(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", ascii_text).strip()


def _column_map(columns: Iterable[Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    cleaned = {column: _clean_header(column) for column in columns}
    for field, aliases in _ALIASES.items():
        for column, name in cleaned.items():
            if name in aliases or any(name.startswith(alias + " ") for alias in aliases):
                result[field] = column
                break
    return result


def parse_date(value: Any) -> date | None:
    """Parse common bank dates, returning ``None`` for blank/non-date values."""
    if value is None or (isinstance(value, float) and value != value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    # Excel serial dates are handled without making pandas mandatory here.
    if re.fullmatch(r"\d+(?:\.\d+)?", text) and float(text) > 20000:
        from datetime import timedelta
        return date(1899, 12, 30) + timedelta(days=float(text))
    if re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[T\s].*)?$", text):
        try:
            return datetime.fromisoformat(text[:10].replace("/", "-")).date()
        except ValueError:
            pass
    try:
        from dateutil.parser import parse
        return parse(text, dayfirst=True, fuzzy=True).date()
    except (ValueError, OverflowError, TypeError):
        return None


def parse_amount(value: Any) -> Decimal | None:
    """Parse Indian/European separators, parentheses, and DR/CR suffixes."""
    if value is None:
        return None
    if isinstance(value, float) and value != value:
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace("\u00a0", " ")
    if not text or text in {"-", "—", "nan", "None"}:
        return None
    negative = (text.startswith("(") and text.endswith(")") or text.endswith("-"))
    suffix = re.search(r"\b(DR|CR)\b", text, re.I)
    if suffix:
        negative = negative or suffix.group(1).upper() == "DR"
        text = text[:suffix.start()] + text[suffix.end():]
    text = text.strip("()").replace("\u2212", "-")
    if text.endswith("-"):
        text = text[:-1]
    text = re.sub(r"[^\d,.'+-]", "", text).replace("'", "")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        if re.search(r",\d{1,2}$", text):
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    if not text or text in {"+", "-", "."}:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    return -abs(amount) if negative else amount


def _normalise_rows(rows: Iterable[Mapping[Any, Any]]) -> list[dict[str, Any]]:
    output = []
    for raw in rows:
        mapping = dict(raw)
        columns = _column_map(mapping)
        parsed_date = parse_date(mapping.get(columns.get("date"))) if "date" in columns else None
        if parsed_date is None:
            continue
        debit = parse_amount(mapping.get(columns["debit"])) if "debit" in columns else None
        credit = parse_amount(mapping.get(columns["credit"])) if "credit" in columns else None
        raw_amount = parse_amount(mapping.get(columns["amount"])) if "amount" in columns else None
        if debit is not None or credit is not None:
            signed_amount = abs(credit or Decimal("0")) - abs(debit or Decimal("0"))
        elif raw_amount is not None:
            signed_amount = raw_amount
            if "transaction_type" in columns:
                raw_direction = mapping.get(columns["transaction_type"])
                direction = _transaction_direction(raw_direction)
                if direction:
                    signed_amount = abs(raw_amount) * direction
                elif raw_amount > 0 and _cell_text(raw_direction):
                    raise StatementParseError(
                        "Could not determine whether a transaction is income or expense from its type. "
                        "Use a statement with debit/credit columns or recognizable transaction labels."
                    )
        else:
            continue
        if signed_amount == 0:
            continue

        description = _cell_text(mapping.get(columns["description"])) if "description" in columns else ""
        reference = _cell_text(mapping.get(columns["reference"])) if "reference" in columns else ""
        row: dict[str, Any] = {
            "date": parsed_date.isoformat(),
            "value_date": (parse_date(mapping.get(columns["value_date"])).isoformat()
                           if "value_date" in columns and parse_date(mapping.get(columns["value_date"])) else None),
            "description": description or reference,
            "reference": reference,
            "debit": abs(debit) if debit is not None else None,
            "credit": abs(credit) if credit is not None else None,
            "balance": parse_amount(mapping.get(columns["balance"])) if "balance" in columns else None,
            "amount": signed_amount,
            "account_number": (
                _normalise_account_value(mapping.get(columns["account_number"]))
                if "account_number" in columns else ""
            ),
        }
        # JSON-friendly, deterministic decimal representation.
        for key in ("amount", "debit", "credit", "balance"):
            if row[key] is not None:
                row[key] = format(row[key], "f")
        row["type"] = "income" if signed_amount > 0 else "expense"
        row["amount"] = format(abs(signed_amount), "f")
        row["category_hint"] = ""
        row["payment_mode"] = _payment_mode(row["description"], row["reference"])
        row["fingerprint"] = fingerprint_row(row)
        output.append(row)
    return output


def _transaction_direction(value: Any) -> Decimal | None:
    direction = _clean_header(value)
    if direction in {
        "d", "dr", "debit", "withdrawal", "withdrawn", "expense", "out",
        "outgoing", "outflow", "soll", "belastung", "cargo", "adeudo",
        "addebito", "retiro", "retrait", "ausgabe",
    }:
        return Decimal("-1")
    if direction in {
        "c", "cr", "credit", "deposit", "income", "in", "incoming", "inflow",
        "received", "haben", "gutschrift", "abono", "ingreso", "accredito",
        "deposito", "einnahme",
    }:
        return Decimal("1")
    if re.search(
        r"\b(debit|withdraw|payment|paid|purchase|compra|pago|paiement|expense|atm|pos|charge|sent|"
        r"kartenzahlung)\b",
        direction,
    ) or "credit card" in direction:
        return Decimal("-1")
    if re.search(r"\b(credit|deposit|income|received|refund|salary|interest|recibido)\b", direction):
        return Decimal("1")
    return None


def _normalise_account_value(value: Any) -> str:
    account = _cell_text(value)
    if re.fullmatch(r"\d+\.0+", account):
        account = account.split(".", 1)[0]
    return re.sub(r"[\s-]", "", account).upper()


def _account_number(text: str) -> str:
    iban = re.search(r"\b[A-Z]{2}\d{2}(?:[\s-]?[A-Z0-9]){11,30}\b", text, re.I)
    if iban:
        return re.sub(r"[\s-]", "", iban.group(0)).upper()

    labelled = re.search(
        r"(?:account(?:\s+(?:number|no|id))?|acct(?:\s+(?:number|no))?|a\s*/?\s*c\s*(?:no|number)"
        r"|numero\s+de\s+cuenta|numero\s+de\s+compte|kontonummer|numero\s+conto)"
        r"\s*(?:[:#.-]\s*)?([0-9X*][0-9X* -]{2,38}[0-9])",
        text,
        re.I,
    )
    if labelled:
        return re.sub(r"[\s-]", "", labelled.group(1)).upper()
    return ""


def _cell_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return ""
    text = str(value).strip()
    return "" if text.casefold() in {"nan", "none"} else text


def _payment_mode(description: str, reference: str) -> str:
    text = f"{description} {reference}".casefold()
    if "upi" in text:
        return "upi"
    if "atm" in text or "cash withdrawal" in text:
        return "cash"
    if "pos" in text or "card" in text or "debit card" in text:
        return "card"
    if "cheque" in text or "chq" in text:
        return "cheque"
    if "neft" in text or "imps" in text or "rtgs" in text:
        return "bank_transfer"
    if "net banking" in text or "internet banking" in text:
        return "net_banking"
    return "bank_transfer"


def fingerprint_row(row: Mapping[str, Any]) -> str:
    """Return a stable SHA-256 fingerprint for a parsed row."""
    keys = ("date", "value_date", "description", "reference", "amount", "debit", "credit", "balance")
    payload = "\x1f".join(str(row.get(key) or "").strip() for key in keys)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_excel(source: str | os.PathLike[str] | bytes, password: str | None = None, suffix: str | None = None) -> list[dict[str, Any]]:
    try:
        import pandas as pd
    except ImportError as exc:
        raise MissingDependencyError("Excel parsing requires pandas and an Excel engine") from exc
    suffix = suffix or (Path(source).suffix.lower() if not isinstance(source, bytes) else ".xlsx")
    if password:
        try:
            import msoffcrypto
        except ImportError as exc:
            raise MissingDependencyError("Encrypted Excel files require msoffcrypto-tool") from exc
        raw = io.BytesIO(source if isinstance(source, bytes) else Path(source).read_bytes())
        decrypted = io.BytesIO()
        try:
            office = msoffcrypto.OfficeFile(raw)
            office.load_key(password=password)
            office.decrypt(decrypted)
        except Exception as exc:
            raise StatementPasswordError("Unable to decrypt Excel statement with supplied password") from exc
        source = decrypted
        suffix = ".xlsx"
    try:
        excel_source = io.BytesIO(source) if isinstance(source, bytes) else source
        sheets = pd.read_excel(
            excel_source,
            header=None,
            sheet_name=None,
            engine="xlrd" if suffix == ".xls" else "openpyxl",
        )
    except (ImportError, ValueError, OSError) as exc:
        raise StatementParseError(
            "Unable to read Excel statement. If it is password-protected, enter its password and try again."
        ) from exc
    rows = []
    found_header = False
    for frame in sheets.values():
        # Bank exports often put title/account information above the header.
        header_index = next(
            (
                i for i, row in frame.iterrows()
                if {"date", "amount"} <= _column_map(row.tolist()).keys()
                or (
                    "date" in _column_map(row.tolist())
                    and {"debit", "credit"} & _column_map(row.tolist()).keys()
                )
            ),
            None,
        )
        if header_index is None:
            continue
        found_header = True
        header = [str(value).strip() for value in frame.iloc[header_index].tolist()]
        account_number = _account_number(
            " ".join(str(value) for value in frame.iloc[:header_index].to_numpy().ravel())
        )
        data = frame.iloc[header_index + 1:].copy()
        data.columns = header
        sheet_rows = _normalise_rows(data.to_dict("records"))
        for row in sheet_rows:
            row["account_number"] = row["account_number"] or account_number
        rows.extend(sheet_rows)
    if not found_header:
        raise StatementParseError("No recognizable date and amount columns found in Excel file")
    if not rows:
        raise StatementParseError("No transaction rows found in Excel statement")
    return rows


def parse_pdf(source: str | os.PathLike[str] | bytes, password: str | None = None) -> list[dict[str, Any]]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise MissingDependencyError("PDF parsing requires pdfplumber") from exc
    try:
        pdf = pdfplumber.open(io.BytesIO(source) if isinstance(source, bytes) else source, password=password)
    except Exception as exc:
        if password:
            raise StatementPasswordError("Unable to open PDF with supplied password") from exc
        raise StatementParseError(
            "Unable to open PDF statement. If it is password-protected, enter its password and try again."
        ) from exc
    rows: list[Mapping[Any, Any]] = []
    page_text = []
    try:
        for page in pdf.pages:
            page_text.append(page.extract_text() or "")
            for table in page.extract_tables() or []:
                if not table:
                    continue
                header = table[0]
                if len(_column_map(header)) >= 2:
                    rows.extend(dict(zip(header, values)) for values in table[1:])
                else:
                    rows.extend(_sbi_positional_rows(table))
    finally:
        pdf.close()
    parsed = _normalise_rows(rows)
    account_number = _account_number(" ".join(page_text))
    for row in parsed:
        row["account_number"] = account_number
    if not parsed:
        raise StatementParseError("No recognizable transaction table found in PDF statement")
    return parsed


def _sbi_positional_rows(table: Sequence[Sequence[Any]]) -> list[Mapping[str, Any]]:
    """Read SBI account-summary tables whose PDF has lost the header row.

    SBI's rendered table is: value date, post date, details, ref/cheque,
    debit, credit, balance. The first row often contains only ``Balance``.
    """
    result = []
    for values in table:
        if len(values) < 7 or parse_date(values[0]) is None:
            continue
        result.append({
            "Value Date": values[0],
            "Post Date": values[1],
            "Details": values[2],
            "Ref No/Cheque No": values[3],
            "Debit": values[4],
            "Credit": values[5],
            "Balance": values[6],
        })
    return result


def parse_statement(source: str | os.PathLike[str] | bytes, password: str | None = None, filename: str | None = None) -> list[dict[str, Any]]:
    """Parse a PDF, XLS, or XLSX statement based on its extension."""
    if isinstance(source, bytes):
        suffix = Path(filename).suffix.lower() if filename else (".pdf" if source[:5] == b"%PDF-" else ".xlsx")
        if suffix == ".pdf":
            return parse_pdf(source, password)
        if suffix in {".xls", ".xlsx"}:
            return parse_excel(source, password, suffix=suffix)
        raise UnsupportedFormatError(f"Unsupported statement format: {suffix or '(none)'}")
    suffix = Path(source).suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(source, password)
    if suffix in {".xls", ".xlsx"}:
        return parse_excel(source, password)
    raise UnsupportedFormatError(f"Unsupported statement format: {suffix or '(none)'}")


row_fingerprint = fingerprint_row
parse_bank_statement = parse_statement

__all__ = [
    "BankImportError", "UnsupportedFormatError", "MissingDependencyError",
    "StatementParseError", "StatementPasswordError", "parse_statement",
    "parse_pdf", "parse_excel", "parse_date", "parse_amount",
    "fingerprint_row", "row_fingerprint", "parse_bank_statement",
]
