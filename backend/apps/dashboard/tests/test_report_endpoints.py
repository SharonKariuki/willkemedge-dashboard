"""The Reports page's tabs, one test per promise each report makes.

Seven of the tabs called endpoints that did not exist; the rest disagreed with
each other about what "income" was. These tests pin the identities the
reports now keep — a balance reconciles, a net matches the P&L's net — as well
as the filters every tab offers.
"""
import datetime as _dt
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from apps.buildings.models import (
    Building,
    PropertyType,
    Unit,
    UnitClassification,
    UnitStatus,
)
from apps.expenses.models import Account, Expense, ExpenseCategory, ManualIncome
from apps.payments.models import Arrears, UtilityCharge
from apps.payments.monthly_ledger import current_balances
from apps.payments.services import process_payment
from apps.tenants.models import Tenant, TenantStatus

User = get_user_model()

JUN, JUL, AUG, YEAR = 6, 7, 8, 2026


def _bill(tenant, month, vat=Decimal("0")):
    rent = tenant.monthly_rent
    return Arrears.objects.create(
        tenant=tenant, period_month=month, period_year=YEAR,
        expected_rent=rent, expected_vat=vat, balance=rent + vat,
    )


class ReportEndpointsTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="owner", email="owner@test.com", password="testpass123!", role="owner"
        )
        cls.north = Building.objects.create(name="North Block", total_floors=1)
        cls.south = Building.objects.create(name="South Block", total_floors=1)
        cls.farm = Building.objects.create(
            name="Soy Farm", total_floors=1, property_type=PropertyType.FARM
        )

        cls.n1 = Unit.objects.create(
            building=cls.north, label="N1", monthly_rent=Decimal("10000"),
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        cls.n2 = Unit.objects.create(
            building=cls.north, label="N2", monthly_rent=Decimal("20000"),
            status=UnitStatus.OCCUPIED_UNPAID, classification=UnitClassification.BUSINESS,
        )
        cls.s1 = Unit.objects.create(
            building=cls.south, label="S1", monthly_rent=Decimal("8000"),
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        cls.vacant = Unit.objects.create(
            building=cls.south, label="S2", monthly_rent=Decimal("9000"),
            status=UnitStatus.VACANT,
        )
        cls.farm_unit = Unit.objects.create(
            building=cls.farm, label="F1", monthly_rent=Decimal("0"), status=UnitStatus.VACANT,
        )

        def tenant(first, unit, rent, **extra):
            return Tenant.objects.create(
                first_name=first, last_name="Test", id_number=first, phone="+254700000000",
                unit=unit, monthly_rent=Decimal(rent), move_in_date=extra.pop("move_in", "2026-06-01"),
                **extra,
            )

        cls.res = tenant("Res", cls.n1, "10000")
        cls.com = tenant("Com", cls.n2, "20000")
        cls.sou = tenant("Sou", cls.s1, "8000")

        for month in (JUN, JUL, AUG):
            _bill(cls.res, month)
            _bill(cls.com, month, vat=Decimal("3200"))
            _bill(cls.sou, month)
        UtilityCharge.objects.create(
            tenant=cls.res, posting_date=_dt.date(2026, 7, 31),
            period_month=JUL, period_year=YEAR, label="Water", amount=Decimal("500"),
        )

        # Res pays June in June, July partly in July. Com pays in full each month.
        # Sou overpays in July.
        process_payment(tenant=cls.res, amount=Decimal("10000"),
                        payment_date="2026-06-03", period_month=JUN, period_year=YEAR)
        process_payment(tenant=cls.res, amount=Decimal("4000"),
                        payment_date="2026-07-04", period_month=JUL, period_year=YEAR)
        for month in (JUN, JUL, AUG):
            process_payment(tenant=cls.com, amount=Decimal("23200"),
                            payment_date=f"2026-{month:02d}-05", period_month=month, period_year=YEAR)
        process_payment(tenant=cls.sou, amount=Decimal("8000"),
                        payment_date="2026-06-02", period_month=JUN, period_year=YEAR)
        process_payment(tenant=cls.sou, amount=Decimal("20000"),
                        payment_date="2026-07-02", period_month=JUL, period_year=YEAR)

        repairs = ExpenseCategory.objects.create(
            name="Repairs", account=Account.objects.get(code="5200")
        )
        Expense.objects.create(
            date="2026-07-10", category=repairs, amount=Decimal("3000"), description="Roof",
            period_month=JUL, period_year=YEAR, building=cls.north,
        )
        ManualIncome.objects.create(
            date="2026-07-20", building=cls.farm, account=Account.objects.get(code="4300"),
            amount=Decimal("5000"), description="Soy harvest", period_month=JUL, period_year=YEAR,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def get(self, url, **params):
        resp = self.client.get(url, params)
        assert resp.status_code == 200, resp.content
        return resp.json()

    # --- every tab has an endpoint -------------------------------------

    def test_every_reports_tab_endpoint_answers(self):
        for url in (
            "/api/reports/rent-balances/",
            "/api/reports/rent-overpayments/",
            "/api/reports/expiring-leases/",
            "/api/reports/vacant-units/",
            f"/api/reports/tenant-statement/{self.res.id}/",
            f"/api/reports/unit-statement/{self.n1.id}/",
            "/api/reports/landlord-statement/",
        ):
            assert self.client.get(url).status_code == 200, url

    def test_bad_parameters_answer_400_not_500(self):
        for url, params in (
            ("/api/reports/profit-loss/", {"month": "13"}),
            ("/api/reports/profit-loss/", {"building": "abc"}),
            ("/api/reports/rent-balances/", {"year": "x"}),
            ("/api/reports/arrears/", {"status": "nobody"}),
            ("/api/reports/move-log/", {"from": "yesterday"}),
            (f"/api/reports/tenant-statement/{self.res.id}/", {"from": "2026-14"}),
        ):
            assert self.client.get(url, params).status_code == 400, (url, params)

    # --- rent balances -------------------------------------------------

    def test_rent_balances_reconcile_row_by_row(self):
        body = self.get("/api/reports/rent-balances/", month=JUL, year=YEAR)
        rows = {r["tenant_id"]: r for r in body["balances"]}
        assert set(rows) == {self.res.id, self.com.id, self.sou.id}
        for r in rows.values():
            assert round(r["brought_forward"] + r["charged"] - r["paid"] - r["credits"], 2) == r["balance"]

        # Res: June square, July 10,000 rent + 500 water − 4,000 paid.
        assert rows[self.res.id]["brought_forward"] == 0.0
        assert rows[self.res.id]["charged"] == 10500.0
        assert rows[self.res.id]["balance"] == 6500.0
        assert rows[self.res.id]["status"] == "Partial"
        # Commercial charge includes the VAT it is billed.
        assert rows[self.com.id]["charged"] == 23200.0
        assert rows[self.com.id]["status"] == "Paid"
        # Sou paid 20,000 against 8,000: 12,000 in credit.
        assert rows[self.sou.id]["balance"] == -12000.0
        assert rows[self.sou.id]["status"] == "In credit"

        assert body["total_outstanding"] == 6500.0
        assert body["total_in_credit"] == 12000.0

    def test_rent_balance_is_the_roll_balance_at_month_end(self):
        body = self.get("/api/reports/rent-balances/", month=JUL, year=YEAR)
        expected = current_balances(
            [self.res, self.com, self.sou], today=_dt.date(2026, 7, 31)
        )
        for r in body["balances"]:
            assert Decimal(str(r["balance"])) == expected[r["tenant_id"]]

    def test_rent_balances_filters(self):
        south = self.get("/api/reports/rent-balances/", month=JUL, year=YEAR, building=self.south.id)
        assert [r["tenant_id"] for r in south["balances"]] == [self.sou.id]
        assert south["building"]["name"] == "South Block"

        owing = self.get("/api/reports/rent-balances/", month=JUL, year=YEAR, status="owing")
        assert [r["tenant_id"] for r in owing["balances"]] == [self.res.id]

    # --- overpayments --------------------------------------------------

    def test_overpayments_lists_tenants_in_credit(self):
        body = self.get("/api/reports/rent-overpayments/", month=JUL, year=YEAR)
        assert [r["tenant_id"] for r in body["overpayments"]] == [self.sou.id]
        assert body["overpayments"][0]["overpaid"] == 12000.0
        assert body["total_overpaid"] == 12000.0
        # August's rent eats 8,000 of the credit.
        aug = self.get("/api/reports/rent-overpayments/", month=AUG, year=YEAR)
        assert aug["overpayments"][0]["overpaid"] == 4000.0

    # --- income agrees across reports ----------------------------------

    def test_farm_income_counts_in_every_income_figure(self):
        pnl = self.get("/api/reports/profit-loss/", month=JUL, year=YEAR)
        # July as billed: Res 10,000 + Com 20,000 (net of VAT) + Sou 8,000
        # + the 500 water charge + farm 5,000 — whatever cash came in.
        assert pnl["income"] == 43500.0
        assert {"label": "Farm / Agricultural Income", "amount": 5000.0} in pnl["income_breakdown"]

        annual = self.get("/api/reports/annual-income/", year=YEAR)
        july = next(m for m in annual["monthly"] if m["month"] == JUL)
        assert july["total"] == 43500.0
        assert july["manual"] == 5000.0

        breakdown = self.get("/api/reports/expense-breakdown/", month=JUL, year=YEAR)
        # Net of VAT, the same as the P&L.
        assert breakdown["total_income"] == 43500.0

        # The Accounting page reads the same ledger, so it agrees to the shilling.
        ledger_pnl = self.get("/api/reports/accounting/", tab="pnl", month=JUL, year=YEAR)
        ledger_income = {a["code"]: a["amount"] for g in ledger_pnl["income"] for a in g["accounts"]}
        assert ledger_income["4300"] == 5000.0
        assert ledger_income["4150"] == 500.0
        assert ledger_pnl["total_income"] == pnl["income"] == 43500.0

    def test_landlord_statement_matches_the_pnl(self):
        for building in (None, self.north.id, self.farm.id):
            params = {"month": JUL, "year": YEAR}
            if building:
                params["building"] = building
            pnl = self.get("/api/reports/profit-loss/", **params)
            landlord = self.get("/api/reports/landlord-statement/", **params)
            assert landlord["total_income"] == pnl["income"]
            assert landlord["total_expenses"] == pnl["total_expenses"]
            assert landlord["net"] == pnl["net_profit"]

        landlord = self.get("/api/reports/landlord-statement/", month=JUL, year=YEAR)
        memo = [r for r in landlord["rows"] if r["section"] == "memo"]
        assert memo == [{
            "section": "memo",
            "description": "VAT collected on commercial rent (owed to KRA)",
            "amount": 3200.0,
        }]
        income = sum(r["amount"] for r in landlord["rows"] if r["section"] == "income")
        assert income == landlord["total_income"]

    def test_pnl_building_filter(self):
        north = self.get("/api/reports/profit-loss/", month=JUL, year=YEAR, building=self.north.id)
        assert north["income"] == 30500.0  # 10,000 + 20,000 net + 500 water, as billed
        assert north["total_expenses"] == 3000.0
        farm = self.get("/api/reports/profit-loss/", month=JUL, year=YEAR, building=self.farm.id)
        assert farm["income"] == 5000.0

    # --- collection ----------------------------------------------------

    def test_monthly_collection_is_cash_received_in_the_month(self):
        # A payment dated in July but allocated to August is July's cash.
        process_payment(tenant=self.res, amount=Decimal("1000"),
                        payment_date="2026-07-30", period_month=AUG, period_year=YEAR)
        body = self.get("/api/reports/monthly-collection/", month=JUL, year=YEAR)
        assert body["total"] == 4000 + 23200 + 20000 + 1000
        assert any(p["period"] == "8/2026" for p in body["payments"])

        north = self.get("/api/reports/monthly-collection/", month=JUL, year=YEAR, building=self.north.id)
        assert north["total"] == 4000 + 23200 + 1000

    # --- statements ----------------------------------------------------

    def test_tenant_statement_reconciles_and_closes_on_the_balance(self):
        body = self.get(f"/api/reports/tenant-statement/{self.res.id}/")
        total = (
            body["opening_balance"] + body["total_expected"]
            - body["total_paid"] - body["total_credits"]
        )
        assert round(total, 2) == body["closing_balance"]
        assert Decimal(str(body["closing_balance"])) == current_balances([self.res])[self.res.id]

        july = self.get(f"/api/reports/tenant-statement/{self.res.id}/", **{"from": "2026-07", "to": "2026-07"})
        assert [r["period"] for r in july["rows"]] == ["July 2026"]
        assert july["opening_balance"] == 0.0
        assert july["closing_balance"] == 6500.0

    def test_unit_statement_lists_each_tenancy(self):
        moved_out = Tenant.objects.create(
            first_name="Old", last_name="Test", id_number="OLD", phone="+254700000009",
            unit=self.n1, monthly_rent=Decimal("9000"), move_in_date="2026-01-01",
            move_out_date="2026-05-31", status=TenantStatus.MOVED_OUT,
        )
        Arrears.objects.create(
            tenant=moved_out, period_month=5, period_year=YEAR,
            expected_rent=Decimal("9000"), expected_vat=Decimal("0"), balance=Decimal("9000"),
        )
        body = self.get(f"/api/reports/unit-statement/{self.n1.id}/")
        assert [t["tenant"] for t in body["tenancies"]] == ["Res Test", "Old Test"]
        assert body["tenancies"][1]["closing_balance"] == 9000.0

    # --- units and leases ----------------------------------------------

    def test_vacant_units_are_lettable_units_only(self):
        body = self.get("/api/reports/vacant-units/")
        assert [u["label"] for u in body["units"]] == ["S2"]  # farm unit left out
        assert body["potential_rent"] == 9000.0
        assert self.get("/api/reports/vacant-units/", building=self.north.id)["count"] == 0

    def test_expiring_leases_by_anniversary(self):
        today = _dt.date.today()
        soon = Tenant.objects.create(
            first_name="Soon", last_name="Test", id_number="SOON", phone="+254700000010",
            unit=self.vacant, monthly_rent=Decimal("9000"),
            move_in_date=(today + _dt.timedelta(days=20)).replace(year=today.year - 1),
        )
        body = self.get("/api/reports/expiring-leases/", days=30)
        ids = [r["tenant_id"] for r in body["leases"]]
        assert soon.id in ids
        # Moved in June 2026: the first anniversary is months away.
        assert self.res.id not in ids

        self.res.status = TenantStatus.NOTICE_GIVEN
        self.res.save(update_fields=["status"])
        body = self.get("/api/reports/expiring-leases/", days=30)
        notice = next(r for r in body["leases"] if r["tenant_id"] == self.res.id)
        assert notice["status"] == "Notice given"

    # --- other filters -------------------------------------------------

    def test_arrears_and_aging_filter_by_building(self):
        north = self.get("/api/reports/arrears/", building=self.north.id)
        assert {r["tenant_id"] for r in north["arrears"]} <= {self.res.id, self.com.id}
        south = self.get("/api/reports/aging-arrears/", building=self.south.id)
        assert all(r["unit"].startswith("South Block") for r in south["aging"])

    def test_move_log_date_window(self):
        body = self.get("/api/reports/move-log/", **{"from": "2026-06-01", "to": "2026-06-30"})
        assert body["count"] == 3
        assert body["moved_in"] == 3
        assert self.get("/api/reports/move-log/", **{"from": "2025-01-01", "to": "2025-12-31"})["count"] == 0

    def test_occupancy_filter_and_totals(self):
        body = self.get("/api/reports/occupancy/", building=self.south.id)
        assert [b["name"] for b in body["buildings"]] == ["South Block"]
        assert body["totals"] == {
            "total": 2, "occupied": 1, "vacant": 1, "under_maintenance": 0, "rate": 50.0,
        }
