from decimal import Decimal
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from bank_import import StatementParseError, parse_statement, parse_amount


def test_parse_amount_handles_indian_bank_formats():
    assert parse_amount("1,25,000.50") == 125000.50
    assert parse_amount("(250.00)") == -250
    assert parse_amount("1,000 DR") == -1000
    assert parse_amount("1.234,56") == Decimal("1234.56")
    assert parse_amount("1.234,56-") == Decimal("-1234.56")


def test_parse_sbi_style_xlsx(tmp_path):
    path = tmp_path / "statement.xlsx"
    pd.DataFrame(
        [
            ["Value Date", "Post Date", "Details", "Ref No/Cheque No", "Debit", "Credit", "Balance"],
            ["31/12/2025", "31/12/2025", "UPI TEST", "ABC123", "1,250.00", "", "8,750.00"],
            ["01/01/2026", "01/01/2026", "SALARY", "", "", "5,000.00", "13,750.00"],
        ]
    ).to_excel(path, index=False, header=False)

    rows = parse_statement(path)
    assert [(row["type"], row["amount"], row["description"]) for row in rows] == [
        ("expense", "1250.00", "UPI TEST"),
        ("income", "5000.00", "SALARY"),
    ]
    assert rows[0]["fingerprint"] != rows[1]["fingerprint"]


def test_parse_international_xlsx_with_metadata_and_transaction_direction(tmp_path):
    path = tmp_path / "international.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame([
            ["Account No: 001234567890"],
            ["Booking Date", "Payee", "Amount", "Dr/Cr", "Closing Balance"],
            ["12/01/2026", "Grocery shop", "1.234,56", "D", "8.765,44"],
            ["13/01/2026", "Employer", "2,500.75", "C", "11.266,19"],
            ["14/01/2026", "Card merchant", "45.50", "Card payment", "11.220,69"],
        ]).to_excel(writer, sheet_name="Transactions", index=False, header=False)
        pd.DataFrame([
            ["Fecha operación", "Descripción", "Debe", "Haber", "IBAN"],
            ["2026-01-14", "Rent", "900.00", "", "GB82 WEST 1234 5698 7654 32"],
        ]).to_excel(writer, sheet_name="Más transacciones", index=False, header=False)

    rows = parse_statement(path)

    assert [(row["type"], row["amount"], row["description"]) for row in rows] == [
        ("expense", "1234.56", "Grocery shop"),
        ("income", "2500.75", "Employer"),
        ("expense", "45.50", "Card merchant"),
        ("expense", "900.00", "Rent"),
    ]
    assert rows[0]["account_number"] == "001234567890"
    assert rows[1]["account_number"] == "001234567890"
    assert rows[2]["account_number"] == "001234567890"
    assert rows[3]["account_number"] == "GB82WEST12345698765432"


def test_rejects_positive_amount_with_unrecognized_transaction_direction(tmp_path):
    path = tmp_path / "ambiguous.xlsx"
    pd.DataFrame([
        ["Date", "Details", "Amount", "Type"],
        ["2026-01-12", "Transfer", "100.00", "Internal Transfer"],
    ]).to_excel(path, index=False, header=False)

    with pytest.raises(StatementParseError, match="Could not determine whether"):
        parse_statement(path)


def test_parse_sbi_positional_pdf():
    page = Mock()
    page.extract_text.return_value = "Account Number: 39855599976"
    page.extract_tables.return_value = [[
        ["Balance", None, None, None, None, None, None],
        ["02/09/2026", "02/09/2026", "UPI transfer", "UTR123", "", "1,000.00", "11,000.00"],
        ["03/09/2026", "03/09/2026", "POS purchase", "CARD456", "250.00", "", "10,750.00"],
    ]]
    pdf = Mock(pages=[page])

    with patch("pdfplumber.open", return_value=pdf):
        rows = parse_statement(b"%PDF-test fixture", filename="statement.pdf")

    assert [(row["date"], row["type"], row["amount"], row["payment_mode"]) for row in rows] == [
        ("2026-09-02", "income", "1000.00", "upi"),
        ("2026-09-03", "expense", "250.00", "card"),
    ]
    assert all(row["account_number"] == "39855599976" for row in rows)
    assert rows[0]["fingerprint"] != rows[1]["fingerprint"]


def test_parse_pdf_table_using_generic_headers():
    page = Mock()
    page.extract_text.return_value = "IBAN: GB82 WEST 1234 5698 7654 32"
    page.extract_tables.return_value = [[
        ["Transaction Date", "Payee", "Amount", "Dr/Cr"],
        ["2026-09-02", "Utilities", "85.50", "D"],
        ["2026-09-03", "Refund", "20.00", "C"],
    ]]
    pdf = Mock(pages=[page])

    with patch("pdfplumber.open", return_value=pdf):
        rows = parse_statement(b"%PDF-test fixture", filename="statement.pdf")

    assert [(row["type"], row["amount"], row["description"]) for row in rows] == [
        ("expense", "85.50", "Utilities"),
        ("income", "20.00", "Refund"),
    ]
    assert all(row["account_number"] == "GB82WEST12345698765432" for row in rows)
