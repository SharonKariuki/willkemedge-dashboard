"""Dashboard + Reports URL routes."""
from django.urls import path

from .views import DashboardSummaryView
from .views_reports import (
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

app_name = "dashboard"

urlpatterns = [
    path("dashboard/summary/", DashboardSummaryView.as_view(), name="summary"),
    path("reports/monthly-collection/", MonthlyCollectionReportView.as_view(), name="monthly-collection"),
    path("reports/annual-income/", AnnualIncomeSummaryView.as_view(), name="annual-income"),
    path("reports/arrears/", ArrearsReportView.as_view(), name="arrears-report"),
    path("reports/tenant-history/<int:tenant_id>/", TenantPaymentHistoryView.as_view(), name="tenant-history"),
    path("reports/occupancy/", OccupancyHistoryView.as_view(), name="occupancy"),
    path("reports/move-log/", MoveInOutLogView.as_view(), name="move-log"),
    path("reports/profit-loss/", ProfitLossReportView.as_view(), name="profit-loss"),
    path("reports/trial-balance/", TrialBalanceView.as_view(), name="trial-balance"),
    path("reports/expense-breakdown/", ExpenseBreakdownReportView.as_view(), name="expense-breakdown"),
]
