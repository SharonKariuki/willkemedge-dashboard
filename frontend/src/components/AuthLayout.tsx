import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";
import { CAP, type Capability, can, roleLabel, userName } from "@/lib/access";
import { avatarFor } from "@/lib/images";
import { homePath, pageRequirement } from "@/lib/nav";

import ErrorBoundary from "./ErrorBoundary";
import GlobalSearch from "./GlobalSearch";
import MobileNav from "./MobileNav";
import NotificationBell from "./NotificationBell";
import Sidebar from "./Sidebar";

export default function AuthLayout() {
  const { user } = useAuth();
  const location = useLocation();

  // Whoever is signed in - never a stand-in name, now that each person has
  // their own account.
  const fullName = userName(user) || "Account";
  const role = roleLabel(user);

  // A page outside this person's role sends them to the first one they can
  // use (a caretaker lands on Properties). The API refuses regardless; this
  // just saves them a screen of errors.
  const allowed = (cap: Capability) => can(user, cap);
  const need = pageRequirement(location.pathname);
  if (user && need && !allowed(need)) {
    return <Navigate to={homePath(allowed)} replace />;
  }

  return (
    <div className="relative min-h-screen">
      <div className="relative z-10 flex">
        <Sidebar />

        <div className="flex min-w-0 flex-1 flex-col">
          {/* Topbar — search, notifications, profile */}
          <header className="sticky top-0 z-30 flex items-center justify-end gap-2 border-b border-border/70 bg-app/80 px-2 py-1.5 backdrop-blur-md sm:px-4 lg:px-6">
            <GlobalSearch />
            {/* The bell reads the collections summary - money. */}
            {allowed(CAP.VIEW_FINANCE) && <NotificationBell />}
            <button
              className="flex items-center gap-2.5 rounded-full py-0.5 pl-0.5 pr-2 transition-colors hover:bg-hover"
              aria-label={role ? `Account: ${fullName}, ${role}` : "Account"}
            >
              <img
                src={avatarFor(fullName)}
                alt=""
                aria-hidden
                className="h-8 w-8 rounded-full ring-1 ring-border"
              />
              <span className="hidden flex-col items-start text-left leading-tight sm:flex">
                <span className="text-sm font-medium text-content">{fullName}</span>
                {role && role !== fullName && (
                  <span className="text-[10px] uppercase tracking-[0.14em] text-content-muted">{role}</span>
                )}
              </span>
            </button>
          </header>

          {/* Main */}
          <main className="flex-1 px-2.5 pb-28 pt-3 sm:px-4 sm:pt-4 md:pb-8 lg:px-6">
            <div className="mx-auto max-w-[1400px] animate-fade-up">
              {/* Keyed by path so a render error in one page is cleared on
                  navigation and never blanks the whole shell. */}
              <ErrorBoundary inline key={location.pathname}>
                <Outlet />
              </ErrorBoundary>
            </div>
          </main>

          <MobileNav />
        </div>
      </div>
    </div>
  );
}
