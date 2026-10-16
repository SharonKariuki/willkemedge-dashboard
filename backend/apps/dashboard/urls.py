"""Dashboard + Reports URL routes."""
from django.urls import path

from .views import DashboardSummaryView
from .views_accounting import AccountingDashboardView, ReportExportView
from .views_reports import (
    AgingArrearsReportView,
    AnnualIncomeSummaryView,
    ArrearsReportView,
    ExpenseBreakdownReportView,
    MonthlyCollectionReportView,
    MoveInOutLogView,
    OccupancyHistoryView,
    ProfitLossReportView,
    TenantPaymentHistoryView,
    TrialBalanceView,
)
from .views_statements import (
    ExpiringLeasesReportView,
    LandlordStatementReportView,
    RentBalancesReportView,
    RentOverpaymentsReportView,
    TenantStatementReportView,
    UnitStatementReportView,
    VacantUnitsReportView,
)

app_name = "dashboard"

urlpatterns = [
    path("dashboard/summary/", DashboardSummaryView.as_view(), name="summary"),
    path("reports/monthly-collection/", MonthlyCollectionReportView.as_view(), name="monthly-collection"),
    path("reports/annual-income/", AnnualIncomeSummaryView.as_view(), name="annual-income"),
    path("reports/arrears/", ArrearsReportView.as_view(), name="arrears-report"),
    path("reports/aging-arrears/", AgingArrearsReportView.as_view(), name="aging-arrears-report"),
    path("reports/tenant-history/<int:tenant_id>/", TenantPaymentHistoryView.as_view(), name="tenant-history"),
    path("reports/occupancy/", OccupancyHistoryView.as_view(), name="occupancy"),
    path("reports/move-log/", MoveInOutLogView.as_view(), name="move-log"),
    path("reports/profit-loss/", ProfitLossReportView.as_view(), name="profit-loss"),
    path("reports/trial-balance/", TrialBalanceView.as_view(), name="trial-balance"),
    path("reports/expense-breakdown/", ExpenseBreakdownReportView.as_view(), name="expense-breakdown"),
    path("reports/accounting/", AccountingDashboardView.as_view(), name="accounting"),
    path("reports/export/", ReportExportView.as_view(), name="report-export"),
    path("reports/rent-balances/", RentBalancesReportView.as_view(), name="rent-balances"),
    path("reports/rent-overpayments/", RentOverpaymentsReportView.as_view(), name="rent-overpayments"),
    path("reports/expiring-leases/", ExpiringLeasesReportView.as_view(), name="expiring-leases"),
    path("reports/vacant-units/", VacantUnitsReportView.as_view(), name="vacant-units"),
    path("reports/tenant-statement/<int:tenant_id>/", TenantStatementReportView.as_view(), name="tenant-statement"),
    path("reports/unit-statement/<int:unit_id>/", UnitStatementReportView.as_view(), name="unit-statement"),
    path("reports/landlord-statement/", LandlordStatementReportView.as_view(), name="landlord-statement"),
]
