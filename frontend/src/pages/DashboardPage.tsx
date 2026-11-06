import { format } from "date-fns";
import {
  AlertTriangle,
  BarChart3,
  Building2,
  ChevronRight,
  Send,
  UserPlus,
  TrendingUp,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as RcTooltip,
} from "recharts";

import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Modal,
  Skeleton,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
} from "@/components/ui";
import { SmsCreditWidget } from "@/components/SmsBalanceCard";
import { cn } from "@/lib/cn";
import { useBuildingPhotoSrc, useBuildings } from "@/hooks/useBuildings";
import { useDashboard, type DashboardAlert } from "@/hooks/useDashboard";
import { avatarFor } from "@/lib/images";
import { formatKES } from "@/lib/money";

// Chart palette — teal (income/occupied) + semantic status, no rainbow.
const OCCUPANCY_COLORS = [
  "rgb(22,163,74)",   // Paid — success
  "rgb(217,119,6)",   // Partial — warning
  "rgb(220,38,38)",   // Unpaid — danger
  "rgb(234,88,12)",   // Arrears — orange (attention)
  "rgb(203,213,225)", // Vacant — neutral-300
];
const TOOLTIP_STYLE = {
  background: "rgb(255,255,255)",
  border: "1px solid rgb(226,232,240)",
  borderRadius: 14,
  boxShadow: "0 14px 34px -10px rgba(15,23,42,0.14)",
  fontSize: 13,
  padding: "10px 14px",
} as const;

function KES(n: number) {
  return formatKES(n);
}

/** A building's own photo when it has one, else its stock picture. The
 *  dashboard's figures come without photo details, so they are looked up from
 *  the buildings list (already cached by the Buildings page). */
function BuildingThumb({ id, name, className }: { id: number | undefined; name: string; className?: string }) {
  const { data: buildings } = useBuildings();
  const building = buildings?.find((b) => b.id === id) ?? (id != null ? { id, name } : undefined);
  const src = useBuildingPhotoSrc(building);
  return <img src={src} alt={name} loading="lazy" className={className} />;
}

export default function DashboardPage() {
  const { data, isLoading, isError, refetch } = useDashboard();
  const [allAlertsOpen, setAllAlertsOpen] = useState(false);

  const today = new Date();
  const dateLine = format(today, "EEEE, d MMMM").toUpperCase();
  const greeting = "Dashboard overview";

  if (isError && !data) {
    return (
      <div className="space-y-10">
        <Masthead dateLine={dateLine} greeting={greeting} />
        <ErrorState
          title="The dashboard could not be loaded."
          description="Your portfolio summary did not come back. This is usually temporary."
          onRetry={() => void refetch()}
        />
      </div>
    );
  }

  if (isLoading || !data) {
    return (
      <div className="space-y-10">
        <Masthead dateLine={dateLine} greeting={greeting} />
        <div className="grid grid-cols-2 gap-5 lg:grid-cols-4 lg:gap-6">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-36 w-full" rounded="lg" />
          ))}
        </div>
        <div className="grid gap-6 lg:grid-cols-3">
          <Skeleton className="h-[320px] w-full lg:col-span-2" rounded="lg" />
          <Skeleton className="h-[320px] w-full" rounded="lg" />
        </div>
        <Skeleton className="h-72 w-full" rounded="lg" />
      </div>
    );
  }

  const { kpis, occupancy, buildings, recent_payments, alerts } = data;

  const occupancyPct = kpis.total_units > 0
    ? Math.round((kpis.occupied / kpis.total_units) * 100)
    : 0;

  const occData = [
    { name: "Paid",    value: occupancy.paid },
    { name: "Partial", value: occupancy.partial },
    { name: "Unpaid",  value: occupancy.unpaid },
    { name: "Arrears", value: occupancy.arrears },
    { name: "Vacant",  value: occupancy.vacant },
  ].filter((d) => d.value > 0);

  const collectionPct = kpis.collection_expected > 0
    ? Math.round((kpis.collection_received / kpis.collection_expected) * 100)
    : kpis.collection_percentage ?? 0;

  const monthLabel = format(today, "MMMM");

  return (
    <div className="space-y-10 lg:space-y-12">
      {/* ── Masthead with actions ─────────────────────────────────────────── */}
      <Masthead dateLine={dateLine} greeting={greeting}>
        {/* The SMS wallet, up where it is seen: a dry balance silently stops
            rent reminders and receipts going out. */}
        <SmsCreditWidget className="w-full sm:w-auto sm:min-w-[19rem]" />
      </Masthead>

      {/* ── KPI tiles — glanceable ────────────────────────────────────────── */}
      <section className="-mt-4 grid gap-5 sm:grid-cols-2 lg:-mt-6 lg:grid-cols-4 lg:items-stretch lg:gap-6">
        {/* Featured collections widget — dark navy hero, on the LEFT */}
        <CollectedHero
          month={monthLabel}
          pct={collectionPct}
          received={kpis.collection_received}
          expected={kpis.collection_expected}
        />
        <Kpi
          icon={AlertTriangle}
          tone={kpis.total_arrears > 0 ? "alert" : "neutral"}
          label="Arrears"
          value={KES(kpis.total_arrears)}
          caption={kpis.total_arrears > 0 ? undefined : "All settled"}
          to="/tenants?payment_status=in_arrears"
        />
        <Kpi
          icon={Building2}
          tone="navy"
          label="Total units"
          value={kpis.total_units.toLocaleString()}
          caption={`${kpis.occupied} occupied · ${kpis.vacant} vacant`}
          to="/units"
        />
        <Kpi
          icon={TrendingUp}
          tone="teal"
          label="Occupancy"
          value={`${occupancyPct}%`}
          progress={occupancyPct}
          to="/buildings"
        />
      </section>

      {/* ── Quick actions + Rent status, then This morning + Recent payments ── */}
      <section className="grid gap-x-6 gap-y-8 lg:grid-cols-5">
        {/* Quick actions — under the Collected card, beside Rent status: a row
            of four on phones and tablets, a 2×2 block that fills the column
            alongside the chart on desktop. */}
        <div className="grid grid-cols-4 gap-2.5 sm:gap-3 lg:col-span-2 lg:grid-cols-2 lg:auto-rows-fr">
          <QuickAction to="/payments" icon={Wallet} label="Record" hint="Log a rent payment" ariaLabel="Record payment" tone="teal" />
          <QuickAction to="/tenants?new=1" icon={UserPlus} label="Add tenant" hint="Move someone in" tone="navy" />
          <QuickAction to="/notifications" icon={Send} label="Remind" hint="Send rent reminders" ariaLabel="Remind tenants" tone="coral" />
          <QuickAction to="/reports" icon={BarChart3} label="Reports" hint="Statements & arrears" ariaLabel="View reports" tone="neutral" />
        </div>

        <Card padding="none" className="lg:col-span-3">
          <div className="px-6 pt-4">
            <h2 className="text-lg font-semibold text-content">Rent status</h2>
          </div>
          <div className="flex flex-col items-center gap-6 p-4 sm:flex-row sm:px-6">
            <div className="relative flex h-[112px] w-[140px] shrink-0 items-center justify-center">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={occData}
                    dataKey="value"
                    innerRadius={38}
                    outerRadius={54}
                    paddingAngle={2}
                    stroke="none"
                  >
                    {occData.map((_, i) => (
                      <Cell key={i} fill={OCCUPANCY_COLORS[i % OCCUPANCY_COLORS.length]} />
                    ))}
                  </Pie>
                  <RcTooltip contentStyle={TOOLTIP_STYLE} />
                </PieChart>
              </ResponsiveContainer>
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                <p className="text-2xl font-bold tabular-nums tracking-tight text-content">
                  {occupancyPct}
                  <span className="text-base font-semibold text-content-muted">%</span>
                </p>
                <p className="mt-0.5 text-[10px] uppercase tracking-wider text-content-muted">
                  occupied
                </p>
              </div>
            </div>
            <ul className="w-full space-y-2 text-sm">
              {occData.map((d, i) => (
                <li key={d.name} className="flex items-center gap-3">
                  <span
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ background: OCCUPANCY_COLORS[i % OCCUPANCY_COLORS.length] }}
                  />
                  <span className="text-content-secondary">{d.name}</span>
                  <span className="ml-auto font-semibold tabular-nums text-content">{d.value}</span>
                </li>
              ))}
            </ul>
          </div>
        </Card>

        {/* min-w-0: a grid item otherwise grows to its widest content (a long
            alert, the payments table) and pushes the page sideways on phones.
            Both columns are flex columns whose card fills them, so on desktop
            the two cards end level whichever is taller. */}
        <div className="flex min-w-0 flex-col lg:col-span-2">
          <div className="mb-4 flex items-baseline justify-between gap-3">
            <div className="flex items-baseline gap-3">
              <h2 className="text-lg font-semibold text-content">This morning</h2>
              <Badge tone={alerts.length === 0 ? "sage" : "coral"} withDot>
                {alerts.length === 0
                  ? "Nothing pressing"
                  : `${alerts.length} ${alerts.length === 1 ? "item" : "items"}`}
              </Badge>
            </div>
            {alerts.length > ALERTS_SHOWN && (
              <button
                type="button"
                onClick={() => setAllAlertsOpen(true)}
                className="whitespace-nowrap text-sm font-medium text-teal-700 transition-colors hover:text-teal-800"
              >
                View all →
              </button>
            )}
          </div>
          {alerts.length === 0 ? (
            <Card padding="lg" className="flex-1">
              <p className="text-base font-medium leading-snug text-content">
                Nothing demands your attention.
              </p>
              <p className="mt-1.5 text-sm text-content-muted">
                Tenants are current and leases are running. Enjoy the morning.
              </p>
            </Card>
          ) : (
            <Card padding="none" className="flex flex-1 flex-col">
              <ul className="divide-y divide-border px-2 py-1.5">
                {alerts.slice(0, ALERTS_SHOWN).map((a, i) => (
                  <AlertRow key={i} alert={a} />
                ))}
              </ul>
              {alerts.length > ALERTS_SHOWN && (
                <button
                  type="button"
                  onClick={() => setAllAlertsOpen(true)}
                  className="mt-auto border-t border-border px-5 py-3 text-left text-sm font-medium text-content-secondary transition-colors hover:bg-surface-sunk hover:text-content"
                >
                  View all {alerts.length} items
                </button>
              )}
            </Card>
          )}

          <Modal
            open={allAlertsOpen}
            onClose={() => setAllAlertsOpen(false)}
            title="This morning"
            eyebrow={`${alerts.length} items`}
            size="md"
          >
            <ul className="-mx-3 divide-y divide-border">
              {alerts.map((a, i) => (
                <AlertRow key={i} alert={a} onNavigate={() => setAllAlertsOpen(false)} />
              ))}
            </ul>
          </Modal>
        </div>

        <div className="flex min-w-0 flex-col lg:col-span-3">
          <div className="mb-4 flex items-baseline justify-between">
            <h2 className="text-lg font-semibold text-content">Recent payments</h2>
            <Link
              to="/payments"
              className="text-sm font-medium text-teal-700 transition-colors hover:text-teal-800"
            >
              All payments →
            </Link>
          </div>
          {recent_payments.length === 0 ? (
            <Card padding="lg" className="flex-1">
              <p className="text-base font-medium leading-snug text-content">
                No payments recorded yet.
              </p>
              <p className="mt-1.5 text-sm text-content-muted">
                When tenants pay, the ledger appears here.
              </p>
            </Card>
          ) : (
            // The wrapper stretches the table's frame to the column's height.
            // Phones show tenant and amount (date beneath it) only, so the 520px
            // floor the extra columns need applies from sm up.
            <div className="flex flex-1 flex-col [&>div]:flex-1">
              <Table className="sm:min-w-[520px]">
                <THead>
                  <TR>
                    <TH className="px-3 sm:px-5">Tenant</TH>
                    <TH className="hidden sm:table-cell">Building / Unit</TH>
                    <TH className="hidden md:table-cell">Method</TH>
                    <TH className="px-3 text-right sm:px-5">Amount</TH>
                    <TH className="hidden text-right sm:table-cell">Date</TH>
                  </TR>
                </THead>
                <TBody>
                  {recent_payments.slice(0, 6).map((p) => (
                    <TR key={p.id}>
                      <TD className="px-3 sm:px-5">
                        <div className="flex items-center gap-3 sm:w-max">
                          <img
                            src={avatarFor(p.tenant_name)}
                            alt=""
                            aria-hidden
                            className="hidden h-9 w-9 rounded-full ring-1 ring-border sm:block"
                          />
                          <span
                            className="block max-w-[10rem] truncate font-medium text-content sm:max-w-none"
                            title={p.tenant_name}
                          >
                            {p.tenant_name}
                          </span>
                        </div>
                      </TD>
                      <TD className="hidden text-content-muted sm:table-cell">
                        {p.building_name} · {p.unit_label}
                      </TD>
                      <TD className="hidden md:table-cell">
                        <Badge tone="neutral">{p.source || "—"}</Badge>
                      </TD>
                      <TD className="px-3 text-right font-semibold tabular-nums text-content sm:px-5">
                        <span className="text-content-muted">KES </span>
                        {Number(p.amount).toLocaleString()}
                        <span className="block text-[11px] font-normal uppercase tracking-wider text-content-muted sm:hidden">
                          {p.payment_date}
                        </span>
                      </TD>
                      <TD className="hidden text-right text-xs uppercase tracking-wider text-content-muted sm:table-cell">
                        {p.payment_date}
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </div>
          )}
        </div>
      </section>

      {/* ── Properties gallery ────────────────────────────────────────────── */}
      {buildings.length > 0 && (
        <section>
          <div className="flex items-baseline justify-between">
            <div>
              <h2 className="text-lg font-semibold text-content">Properties</h2>
              <p className="mt-1 text-sm text-content-muted">
                {buildings.length} {buildings.length === 1 ? "building" : "buildings"} in the portfolio
              </p>
            </div>
            <Link
              to="/buildings"
              className="text-sm font-medium text-teal-700 transition-colors hover:text-teal-800"
            >
              Manage →
            </Link>
          </div>
          <div className="mt-6 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {buildings.slice(0, 6).map((b) => {
              const rate = b.total > 0 ? Math.round((b.occupied / b.total) * 100) : 0;
              return (
                <Link
                  key={b.id}
                  to={b.id ? `/buildings/${b.id}` : "/buildings"}
                  className="group relative block overflow-hidden rounded-2xl bg-surface shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md dark:border dark:border-border"
                >
                  <div className="relative h-44 w-full overflow-hidden">
                    <BuildingThumb
                      id={b.id}
                      name={b.name}
                      className="h-full w-full object-cover transition-transform duration-700 ease-out group-hover:scale-[1.04]"
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-neutral-950/70 via-neutral-950/10 to-transparent" />
                    <div className="absolute bottom-4 left-4 right-4 flex items-end justify-between gap-3">
                      <p className="truncate text-base font-semibold text-white">
                        {b.name}
                      </p>
                      <p className="text-base font-semibold tabular-nums text-white">
                        {rate}<span className="text-sm text-white/70">%</span>
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-4 px-5 py-4 text-sm">
                    <span className="text-content-muted">
                      <span className="font-semibold tabular-nums text-content">{b.occupied}</span> occupied
                    </span>
                    <span className="text-border-strong">·</span>
                    <span className="text-content-muted">
                      <span className="font-semibold tabular-nums text-content">{b.vacant}</span> vacant
                    </span>
                    <span className="ml-auto text-content-muted">{b.total} total</span>
                  </div>
                </Link>
              );
            })}
          </div>
          {buildings.length > 1 && (
            <Card padding="lg" className="mt-8">
              <div className="flex items-baseline justify-between gap-3">
                <h3 className="text-lg font-semibold text-content">Occupancy by building</h3>
                <span className="text-sm text-content-muted">Units occupied</span>
              </div>
              <ul className="mt-5 space-y-5">
                {buildings.map((b) => {
                  const rate = b.total > 0 ? Math.round((b.occupied / b.total) * 100) : 0;
                  return (
                    <li key={b.id ?? b.name}>
                      <div className="flex items-baseline justify-between gap-3">
                        <span className="truncate font-medium text-content">{b.name}</span>
                        <span className="shrink-0 text-sm tabular-nums text-content-muted">
                          {b.occupied} / {b.total}
                        </span>
                      </div>
                      <div
                        className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-sunk"
                        role="progressbar"
                        aria-label={`${b.name} occupancy`}
                        aria-valuenow={rate}
                        aria-valuemin={0}
                        aria-valuemax={100}
                      >
                        <div
                          className="h-1.5 rounded-full bg-teal-600 transition-[width] duration-700 ease-out"
                          style={{ width: `${rate}%` }}
                        />
                      </div>
                    </li>
                  );
                })}
              </ul>
            </Card>
          )}
        </section>
      )}

      {buildings.length === 0 && (
        <EmptyState
          title="No buildings yet"
          description="Add your first property to start tracking units, tenants, and payments."
        />
      )}
    </div>
  );
}

// ─── Local primitives ───────────────────────────────────────────────────────

interface MastheadProps {
  dateLine: string;
  greeting: string;
  headline?: string;
  children?: React.ReactNode;
}

function Masthead({ dateLine, greeting, headline, children }: MastheadProps) {
  return (
    <header className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <p className="text-xs font-semibold uppercase tracking-wider text-content-muted">
          {dateLine}
        </p>
        <h1 className="mt-2.5 text-3xl font-bold leading-tight tracking-tight text-content sm:text-4xl">
          {greeting}
        </h1>
        {headline && (
          <p className="mt-2.5 text-lg leading-snug text-content-secondary">
            {headline}
          </p>
        )}
      </div>
      {/* shrink-0 so the greeting gives way first — otherwise the actions are
          squeezed until each button drops onto its own line. */}
      {children && (
        <div className="flex shrink-0 flex-wrap items-start gap-3 sm:justify-end">{children}</div>
      )}
    </header>
  );
}

interface CollectedHeroProps {
  month: string;
  pct: number;
  received: number;
  expected: number;
}

function CollectedHero({ month, pct, received, expected }: CollectedHeroProps) {
  return (
    <Link
      to="/payments"
      aria-label={`Collected ${KES(received)} of ${KES(expected)} in ${month}`}
      className="relative flex h-full flex-col overflow-hidden rounded-2xl bg-gradient-to-br from-navy-600 via-navy-800 to-navy-900 p-4 text-white shadow-lg transition-all hover:-translate-y-0.5 hover:shadow-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50">
      {/* Soft teal glow — spatial depth */}
      <div
        aria-hidden
        className="pointer-events-none absolute -right-10 -top-12 h-40 w-40 rounded-full bg-teal-500/25 blur-3xl"
      />
      <div className="relative flex items-start justify-between gap-3">
        <p className="text-xs font-medium uppercase tracking-wider text-white/60">
          Collected · {month}
        </p>
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-white/10 text-teal-300">
          <Wallet className="h-3.5 w-3.5" />
        </div>
      </div>
      <div className="relative mt-2 flex flex-wrap items-end gap-x-2 gap-y-1">
        <p className="text-xl font-bold leading-none tabular-nums tracking-tight sm:text-2xl">
          {KES(received)}
        </p>
        <span className="mb-0.5 inline-flex items-center gap-1 rounded-full bg-teal-500/20 px-2 py-0.5 text-[11px] font-semibold text-teal-300">
          {pct}%
        </span>
      </div>
      <p className="relative mt-1.5 text-xs text-white/55">of {KES(expected)} expected</p>
    </Link>
  );
}

type KpiTone = "navy" | "teal" | "success" | "alert" | "neutral";

const KPI_ICON: Record<KpiTone, string> = {
  navy: "bg-navy-800/[0.07] text-navy-700 dark:bg-navy-500/15 dark:text-navy-500",
  teal: "bg-info-soft text-teal-700 dark:text-teal-500",
  success: "bg-success-soft text-success",
  alert: "bg-orange-500/12 text-orange-700 dark:text-orange-500",
  neutral: "bg-surface-sunk text-content-secondary",
};

interface KpiProps {
  icon: LucideIcon;
  label: string;
  value: string;
  caption?: string;
  progress?: number;
  tone?: KpiTone;
  compact?: boolean;
  /** When set, the tile becomes a link that drills down to the relevant list. */
  to?: string;
}

function Kpi({ icon: Icon, label, value, caption, progress, tone = "neutral", compact, to }: KpiProps) {
  const alert = tone === "alert";
  const interactive = to
    ? "transition-all hover:-translate-y-0.5 hover:shadow-float focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/40"
    : "";
  const body = (
    <Card padding="none" className={cn("h-full", compact ? "p-4" : "p-5", interactive)}>
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs font-medium uppercase tracking-wider text-content-muted">
          {label}
        </p>
        <div
          className={cn(
            "flex shrink-0 items-center justify-center rounded-lg",
            compact ? "h-7 w-7" : "h-8 w-8",
            KPI_ICON[tone]
          )}
        >
          <Icon className={compact ? "h-3.5 w-3.5" : "h-4 w-4"} />
        </div>
      </div>
      <p
        className={cn(
          "font-bold leading-tight tabular-nums tracking-tight",
          compact ? "mt-2 text-xl sm:text-2xl" : "mt-2.5 text-2xl sm:text-3xl",
          alert ? "text-orange-700 dark:text-orange-500" : "text-content"
        )}
      >
        {value}
      </p>
      {progress !== undefined && (
        <div className={cn("h-1.5 w-full overflow-hidden rounded-full bg-surface-sunk", compact ? "mt-2.5" : "mt-3")}>
          <div
            className="h-1.5 rounded-full bg-teal-600 transition-[width] duration-700 ease-out"
            style={{ width: `${Math.min(100, progress)}%` }}
          />
        </div>
      )}
      {caption && (
        <p
          className={cn(
            "text-xs",
            compact ? "mt-1.5" : "mt-2",
            alert ? "text-orange-700 dark:text-orange-500" : "text-content-muted"
          )}
        >
          {caption}
        </p>
      )}
    </Card>
  );

  if (to) {
    return (
      <Link to={to} aria-label={`${label}: ${value}`} className="block h-full">
        {body}
      </Link>
    );
  }
  return body;
}

interface QuickActionProps {
  to: string;
  icon: LucideIcon;
  label: string;
  /** One line under the label, shown where the tile has room (desktop). */
  hint: string;
  /** Fuller name for screen readers when the visible label is a single word. */
  ariaLabel?: string;
  tone: keyof typeof QUICK_ACTION_TONES;
}

/** Icon well colours — one hue per action so the four are told apart at a glance. */
const QUICK_ACTION_TONES = {
  teal: "bg-teal-500/10 text-teal-700 dark:bg-teal-500/15 dark:text-teal-500",
  coral: "bg-coral-50 text-coral-600 dark:bg-white/10 dark:text-coral-400",
  navy: "bg-navy-500/10 text-navy-700 dark:bg-white/10 dark:text-content",
  neutral: "bg-surface-sunk text-content-secondary",
};

function QuickAction({ to, icon: Icon, label, hint, ariaLabel, tone }: QuickActionProps) {
  return (
    <Link
      to={to}
      aria-label={ariaLabel}
      className="group flex min-h-[88px] flex-col items-center justify-center gap-2 rounded-2xl border border-border bg-surface px-1.5 py-3 text-center shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:border-border-strong hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/40 active:translate-y-0 active:shadow-sm lg:flex-row lg:justify-start lg:gap-3.5 lg:px-4 lg:text-left"
    >
      <span
        className={cn(
          "flex h-11 w-11 shrink-0 items-center justify-center rounded-xl transition-transform duration-200 group-hover:scale-105 lg:h-12 lg:w-12",
          QUICK_ACTION_TONES[tone]
        )}
      >
        <Icon className="h-5 w-5 lg:h-[22px] lg:w-[22px]" strokeWidth={2} />
      </span>
      <span className="min-w-0">
        <span className="block whitespace-nowrap text-xs font-semibold leading-tight text-content sm:text-sm">{label}</span>
        <span className="mt-0.5 hidden truncate text-xs text-content-muted lg:block">{hint}</span>
      </span>
    </Link>
  );
}

const ALERT_TONE = {
  danger: "bg-danger-soft text-danger",
  warning: "bg-warning-soft text-warning",
  attention: "bg-orange-500/10 text-orange-700 dark:text-orange-500",
  neutral: "bg-surface-sunk text-content-secondary",
} as const;

/** What to do about an alert, and where to go to do it. Alerts that name a
 *  tenant open that tenant's page, where the balance, notice or lease lives. */
/** "This morning" keeps to a short list; the rest open in View all. */
const ALERTS_SHOWN = 5;

function AlertRow({ alert, onNavigate }: { alert: DashboardAlert; onNavigate?: () => void }) {
  const action = alertAction(alert);
  return (
    <li>
      <Link
        to={action.to}
        onClick={onNavigate}
        className="group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors hover:bg-surface-sunk focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/40"
      >
        <AlertSeverityDot type={alert.type} />
        <p className="line-clamp-2 min-w-0 flex-1 break-words leading-snug text-content-secondary group-hover:text-content">
          {alert.message}
        </p>
        <span
          className={cn(
            "hidden shrink-0 whitespace-nowrap rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider sm:inline-flex",
            action.tone
          )}
        >
          {action.label}
        </span>
        <ChevronRight
          aria-hidden
          className="h-4 w-4 shrink-0 text-content-muted transition-transform group-hover:translate-x-0.5 group-hover:text-content"
        />
      </Link>
    </li>
  );
}

function alertAction(a: DashboardAlert): { label: string; to: string; tone: string } {
  const tenant = a.tenant_id ? `/tenants/${a.tenant_id}` : null;
  switch (a.type) {
    case "overdue":
      return { label: "Collect rent", to: tenant ?? "/tenants?payment_status=in_arrears", tone: ALERT_TONE.danger };
    case "partial":
      return { label: "Chase balance", to: tenant ?? "/units", tone: ALERT_TONE.warning };
    case "move_out":
      return { label: "Plan move-out", to: tenant ?? "/tenants", tone: ALERT_TONE.attention };
    case "expiring_lease":
      return { label: "Renew lease", to: tenant ?? "/tenants", tone: ALERT_TONE.warning };
    default:
      return { label: "Review", to: tenant ?? "/units", tone: ALERT_TONE.neutral };
  }
}

function AlertSeverityDot({ type }: { type: string }) {
  const color =
    type === "overdue"
      ? "bg-danger"
      : type === "partial" || type === "expiring_lease"
      ? "bg-warning"
      : type === "move_out"
      ? "bg-orange-600"
      : "bg-neutral-300";
  return (
    <span
      className={"inline-block h-2 w-2 shrink-0 rounded-full " + color}
      aria-hidden
    />
  );
}
