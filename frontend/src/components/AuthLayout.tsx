import { Outlet, useLocation } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";
import { avatarFor } from "@/lib/images";

import ErrorBoundary from "./ErrorBoundary";
import GlobalSearch from "./GlobalSearch";
import MobileNav from "./MobileNav";
import NotificationBell from "./NotificationBell";
import Sidebar from "./Sidebar";

export default function AuthLayout() {
  const { user } = useAuth();
  const location = useLocation();

  const fullName =
    [user?.first_name, user?.last_name]
      .map((s) => s?.trim())
      .filter(Boolean)
      .join(" ") || "Wilson Osoro";

  return (
    <div className="relative min-h-screen">
      <div className="relative z-10 flex">
        <Sidebar />

        <div className="flex min-w-0 flex-1 flex-col">
          {/* Topbar — search, notifications, profile */}
          <header className="sticky top-0 z-30 flex items-center justify-end gap-2 border-b border-border/70 bg-app/80 px-2 py-2.5 backdrop-blur-md sm:px-4 sm:py-3 lg:px-6">
            <GlobalSearch />
            <NotificationBell />
            <button
              className="flex items-center gap-2.5 rounded-full py-1 pl-1 pr-2 transition-colors hover:bg-hover"
              aria-label="Account"
            >
              <img
                src={avatarFor(fullName)}
                alt=""
                aria-hidden
                className="h-9 w-9 rounded-full ring-1 ring-border"
              />
              <span className="hidden text-sm font-medium text-content sm:block">
                {fullName}
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
