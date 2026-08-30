"""
Tests for the JSON-driven official rent-statement generator.

The canonical case reproduces the real "Unit 3A" statement (Zachary Bwonda,
May-2026) exactly — every running balance and summary figure must match.
"""
import json

import pytest

from apps.payments.statement_generator import (
    build_context,
    generate_statement_file,
    generate_statement_pdf,
    generate_statements,
)

# The exact ledger from the official Unit 3A statement.
UNIT_3A = {
    "tenant_name": "Zachary Bwonda", "unit": "3A", "pin": "A007523148T",
    "id_number": "700421629", "phone": "0718 080157", "month": "May-2026",
    "statement_date": "4 May 2026", "unit_descriptor": "House 3A - Donholm Estate",
    "opening_balance": -18200,
    "transactions": [
        {"date": "1 Jan 2026", "description": "Month Rent - Jan 2025", "invoice_amount": 20000},
        {"date": "1 Jan 2026", "description": "Water usage - Dec. '25", "invoice_amount": 1500},
        {"date": "24 Jan 2026", "description": "Payment Received", "payments": 20000},
        {"date": "1 Feb 2026", "description": "Water usage - Feb. '26 (9units)", "invoice_amount": 1350},
        {"date": "1 Feb 2026", "description": "Month Rent - Feb 2026", "invoice_amount": 20000},
        {"date": "26 Feb 2026", "description": "Payment Received", "payments": 22000},
        {"date": "1 Mar 2026", "description": "Month Rent - March-2026", "invoice_amount": 20000},
        {"date": "1 Mar 2026", "type": "water", "label": "Water usage - Feb. '26",
         "opening_reading": 1445, "closing_reading": 1449, "rate": 150},
        {"date": "26 Mar 2026", "description": "Payment Received", "payments": 22000},
        {"date": "1 Apr 2026", "description": "Month Rent - April-2026", "invoice_amount": 20000},
        {"date": "1 Apr 2026", "type": "water", "label": "Water usage - Mar. '26",
         "opening_reading": 1449, "closing_reading": 1456, "rate": 150},
        {"date": "1 May 2026", "description": "Month Rent - May-2026", "invoice_amount": 20000},
        {"date": "1 May 2026", "type": "water", "label": "Water usage - Apr '26",
         "opening_reading": 1456, "closing_reading": 1463, "rate": 150},
    ],
}

EXPECTED_BALANCES = [
    "1,800", "3,300", "-16,700", "-15,350", "4,650", "-17,350",
    "2,650", "3,250", "-18,750", "1,250", "2,300", "22,300", "23,350",
]


class TestBuildContext:
    def test_running_balances_match_the_official_statement(self):
        ctx = build_context(UNIT_3A)
        assert [r["balance"] for r in ctx["rows"]] == EXPECTED_BALANCES

    def test_summary_totals(self):
        ctx = build_context(UNIT_3A)
        assert ctx["current_month"] == "20,000.00"
        assert ctx["arrears_others"] == "3,350.00"
        assert ctx["total_due"] == "23,350.00"
        assert ctx["total_due_whole"] == "23,350"

    def test_water_charge_computed_from_readings(self):
        ctx = build_context(UNIT_3A)
        # 1449 - 1445 = 4 units @ 150 = 600
        water = ctx["rows"][7]
        assert water["description_lines"][0] == "Water usage - Feb. '26 (4 units @ KES 150)"
        assert water["description_lines"][1] == "Opening Reading: 1445"
        assert water["description_lines"][2] == "Closing Reading: 1449"
        assert water["invoice_amount"] == "600"

    def test_negative_balance_flagged(self):
        ctx = build_context(UNIT_3A)
        assert ctx["rows"][2]["balance_negative"] is True   # -16,700
        assert ctx["rows"][0]["balance_negative"] is False  # 1,800

    def test_payment_row_has_blank_invoice_cell(self):
        ctx = build_context(UNIT_3A)
        payment = ctx["rows"][2]
        assert payment["invoice_amount"] == ""
        assert payment["payments"] == "20,000"

    def test_paybill_account_uses_the_unit(self):
        ctx = build_context(UNIT_3A)
        assert ctx["paybill_account"] == "90290#3A"

    def test_minimal_input_from_the_spec_example(self):
        data = {
            "tenant_name": "John Doe", "unit": "4B", "month": "June-2026",
            "statement_date": "4 June 2026",
            "transactions": [
                {"date": "1 June 2026", "description": "Month Rent - June 2026",
                 "invoice_amount": 20000, "payments": 0},
                {"date": "24 June 2026", "description": "Payment Received",
                 "invoice_amount": 0, "payments": 20000},
            ],
        }
        ctx = build_context(data)
        assert [r["balance"] for r in ctx["rows"]] == ["20,000", "0"]
        assert ctx["total_due"] == "0.00"
        assert ctx["current_month"] == "20,000.00"


class TestPdfOutput:
    def test_generates_valid_pdf_bytes(self):
        pdf = generate_statement_pdf(UNIT_3A)
        assert pdf[:4] == b"%PDF"
        assert len(pdf) > 2000

    def test_writes_unit_named_file(self, tmp_path):
        path = generate_statement_file(UNIT_3A, tmp_path)
        assert path.name == "Unit 3A.pdf"
        assert path.read_bytes()[:4] == b"%PDF"

    def test_batch_loop_one_pdf_per_unit(self, tmp_path):
        tenants = [
            {**UNIT_3A, "unit": "1A"},
            {**UNIT_3A, "unit": "1B"},
            {**UNIT_3A, "unit": "2A"},
        ]
        paths = generate_statements(tenants, tmp_path)
        names = sorted(p.name for p in paths)
        assert names == ["Unit 1A.pdf", "Unit 1B.pdf", "Unit 2A.pdf"]
        for p in paths:
            assert p.read_bytes()[:4] == b"%PDF"


@pytest.mark.django_db
class TestManagementCommand:
    def test_generate_statements_command(self, tmp_path):
        from io import StringIO

        from django.core.management import call_command

        json_path = tmp_path / "tenants.json"
        json_path.write_text(json.dumps([
            {**UNIT_3A, "unit": "1A"},
            {**UNIT_3A, "unit": "1B"},
        ]))
        out_dir = tmp_path / "statements"
        out = StringIO()
        call_command("generate_statements", str(json_path), "--out", str(out_dir), stdout=out)
        assert "2 statement(s) written" in out.getvalue()
        assert (out_dir / "Unit 1A.pdf").exists()
        assert (out_dir / "Unit 1B.pdf").exists()
