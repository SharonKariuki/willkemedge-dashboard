import type { ReactNode } from "react";
import { Building2 } from "lucide-react";

import { propertyImage } from "@/lib/images";

interface Props {
  children: ReactNode;
  title: string;
  subtitle?: string;
}

export default function AuthShell({ children, title, subtitle }: Props) {
  return (
    <div className="flex min-h-screen">
      {/* Left: form panel */}
      <div className="relative flex w-full flex-col justify-center px-6 py-10 sm:px-10 lg:w-[46%] lg:px-16">
        <div className="absolute left-6 top-6 flex items-center gap-2 sm:left-10 lg:left-16">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-ink-900 text-white shadow-glass">
            <span className="font-display text-base font-semibold">W</span>
          </div>
          <div>
            <p className="font-display text-sm font-semibold text-ink-900">Willkemedge</p>
            <p className="text-[10px] uppercase tracking-[0.14em] text-ink-500">Property Suite</p>
          </div>
        </div>

        <div className="mx-auto w-full max-w-sm">
          <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-sage-600 dark:text-sage-400">
            Welcome
          </p>
          <h1 className="mt-2 font-display text-3xl font-semibold leading-tight text-ink-900 sm:text-4xl">
            {title}
          </h1>
          {subtitle && <p className="mt-2 text-sm text-ink-500">{subtitle}</p>}
          <div className="mt-8">{children}</div>
        </div>

        <p className="absolute bottom-6 left-6 text-[11px] text-ink-400 sm:left-10 lg:left-16">
          © {new Date().getFullYear()} Willkemedge · Dr. William Osoro
        </p>
      </div>

      {/* Right: image panel (hidden on small) */}
      <div className="relative hidden overflow-hidden lg:block lg:w-[54%]">
        <img
          src={propertyImage("login-hero", "lg")}
          alt=""
          aria-hidden
          className="absolute inset-0 h-full w-full object-cover"
        />
        <div className="absolute inset-0 bg-gradient-to-br from-sage-700/60 via-ink-900/30 to-coral-500/40" />
        <div className="absolute inset-0 flex flex-col justify-end p-12">
          <div className="glass-strong max-w-md rounded-xl p-6">
            <Building2 className="h-6 w-6 text-white" />
            <p className="mt-3 font-display text-2xl font-semibold leading-tight text-white">
              Every building, every tenant, every payment — in one clean view.
            </p>
            <p className="mt-3 text-sm text-white/80">
              A property management suite designed for Dr. Osoro's portfolio.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
