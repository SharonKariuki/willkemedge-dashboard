/**
 * Authenticated layout shell — sidebar + topbar + outlet.
 */
import { LogOut } from "lucide-react";
import { Outlet } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";

import MobileNav from "./MobileNav";
import Sidebar from "./Sidebar";

export default function AuthLayout() {
  const { user, logout } = useAuth();

  return (
    <div className="flex min-h-screen bg-slate-50">
      <Sidebar />

      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 lg:px-6">
          <div className="flex items-center gap-3">
            <MobileNav />
            <div>
              <h1 className="text-base font-semibold text-slate-900 lg:text-lg">
                Willkemedge Dashboard
              </h1>
              <p className="text-xs text-slate-500">Signed in as {user?.email}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => void logout()}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-100"
          >
            <LogOut className="h-4 w-4" />
            <span className="hidden sm:inline">Sign out</span>
          </button>
        </header>
        <main className="flex-1 overflow-auto p-4 lg:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
