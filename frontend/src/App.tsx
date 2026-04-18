import { Navigate, Route, Routes } from "react-router-dom";

import AuthLayout from "@/components/AuthLayout";
import ProtectedRoute from "@/components/ProtectedRoute";
import BuildingsPage from "@/pages/BuildingsPage";
import DashboardPage from "@/pages/DashboardPage";
import ExpensesPage from "@/pages/ExpensesPage";
import LoginPage from "@/pages/LoginPage";
import PasswordResetPage from "@/pages/PasswordResetPage";
import PasswordResetConfirmPage from "@/pages/PasswordResetConfirmPage";
import PaymentsPage from "@/pages/PaymentsPage";
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
        <Route path="/expenses" element={<ExpensesPage />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>

      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
