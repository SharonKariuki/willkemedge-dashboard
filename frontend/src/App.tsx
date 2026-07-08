import { Navigate, Route, Routes } from "react-router-dom";

import AuthLayout from "@/components/AuthLayout";
import ProtectedRoute from "@/components/ProtectedRoute";
import AccountingPage from "@/pages/AccountingPage";
import BuildingsPage from "@/pages/BuildingsPage";
import DashboardPage from "@/pages/DashboardPage";
import ExpensesPage from "@/pages/ExpensesPage";
import LoginPage from "@/pages/LoginPage";
import NotFoundPage from "@/pages/NotFoundPage";
import NotificationsPage from "@/pages/NotificationsPage";
import PasswordResetPage from "@/pages/PasswordResetPage";
import PasswordResetConfirmPage from "@/pages/PasswordResetConfirmPage";
import PaymentsPage from "@/pages/PaymentsPage";
import ReconciliationPage from "@/pages/ReconciliationPage";
import ReportsPage from "@/pages/ReportsPage";
import SettingsPage from "@/pages/SettingsPage";
import TenantsPage from "@/pages/TenantsPage";
import UnitsPage from "@/pages/UnitsPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/reset-password" element={<PasswordResetPage />} />
      <Route path="/reset-password/confirm/:token" element={<PasswordResetConfirmPage />} />

      <Route
        element={
          <ProtectedRoute>
            <AuthLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/buildings" element={<BuildingsPage />} />
        <Route path="/units" element={<UnitsPage />} />
        <Route path="/tenants" element={<TenantsPage />} />
        <Route path="/payments" element={<PaymentsPage />} />
        <Route path="/reconciliation" element={<ReconciliationPage />} />
        <Route path="/expenses" element={<ExpensesPage />} />
        <Route path="/accounting" element={<AccountingPage />} />
        <Route path="/notifications" element={<NotificationsPage />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>

      {/* Public catch-all: a logged-out user hitting a bad URL should see
          NotFound, not get bounced to /login by ProtectedRoute. */}
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
