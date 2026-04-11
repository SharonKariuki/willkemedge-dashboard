/**
 * Authenticated layout shell — sidebar + topbar + outlet.
 * Day 2 fleshes this out with the real responsive sidebar nav.
 */
import { LogOut } from "lucide-react";
import { Outlet } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";

export default function AuthLayout() {
  const { user, logout } = useAuth();

  return (
    <div className="flex min-h-screen flex-col bg-slate-50">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Willkemedge Dashboard</h1>
          <p className="text-xs text-slate-500">Signed in as {user?.email}</p>
        </div>
        <button
          type="button"
          onClick={() => void logout()}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-100"
        >
          <LogOut className="h-4 w-4" />
          Sign out
        </button>
      </header>
      <main className="flex-1 p-6">
        <Outlet />
      </main>
    </div>
  );
}
