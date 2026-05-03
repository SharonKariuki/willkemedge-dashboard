import { LogOut } from "lucide-react";
import { Outlet } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";
import { displayName } from "@/lib/displayName";

import GlobalSearch from "./GlobalSearch";
import MobileNav from "./MobileNav";
import NotificationBell from "./NotificationBell";
import Sidebar from "./Sidebar";
import { Button } from "./ui";

export default function AuthLayout() {
  const { user, logout } = useAuth();

  const initials = (user?.email ?? "??")
    .split("@")[0]
    .split(/[._-]/)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase() ?? "")
    .join("");

  return (
    <div className="relative min-h-screen">
      {/* Paper-grain texture overlay */}
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 z-0 opacity-[0.015] mix-blend-multiply"
        style={{
          backgroundImage:
            "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='140' height='140'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0.35 0 0 0 0 0.25 0 0 0 0 0.15 0 0 0 0.9 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>\")",
        }}
      />
      <div className="relative z-10 flex">
        <Sidebar />

        <div className="flex min-w-0 flex-1 flex-col">
          {/* Topbar */}
          <header className="sticky top-0 z-30 px-2 pt-2 sm:px-4 lg:px-6 lg:pt-4">
            <div className="glass-strong flex items-center gap-2 rounded-xl px-2.5 py-2 ring-1 ring-ochre-500/10 sm:gap-3 sm:px-4 sm:py-2.5">
              <div className="min-w-0 flex-1">
                <p className="font-display text-[13px] font-semibold leading-none text-ink-900 sm:text-base">
                  Welcome back{user?.email ? `, ${displayName(user.email.split("@")[0])}` : ""}
                </p>
              </div>

              <GlobalSearch />

              {/* Real-time notification bell */}
              <NotificationBell />

              <div className="flex items-center gap-2 pl-1">
                <div className="hidden text-right sm:block">
                  <p className="text-xs font-medium text-ink-900">
                    {user?.email?.split("@")[0] ?? "User"}
                  </p>
                  <p className="text-[10px] uppercase tracking-wider text-ink-500">Admin</p>
                </div>
                <button
                  className="flex h-9 w-9 items-center justify-center rounded-full bg-ink-900 text-xs font-semibold text-white shadow-glass"
                  aria-label="Account"
                >
                  {initials || "U"}
                </button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Sign out"
                  onClick={() => void logout()}
                  className="hidden sm:inline-flex"
                >
                  <LogOut className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </header>

          {/* Main */}
          <main className="flex-1 px-2.5 pb-28 pt-3 sm:px-4 sm:pt-4 lg:px-6 lg:pb-8">
            <div className="mx-auto max-w-[1400px] animate-fade-up">
              <Outlet />
            </div>
          </main>

          <MobileNav />
        </div>
      </div>
    </div>
  );
}
