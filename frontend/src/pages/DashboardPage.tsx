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
  Skeleton,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
} from "@/components/ui";
import SmsBalanceCard from "@/components/SmsBalanceCard";
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
      <Masthead dateLine={dateLine} greeting={greeting} />

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

      {/* ── This morning + Rent status / Recent payments ────────────────────────────────── */}
      <section className="grid gap-6 lg:grid-cols-5">
        <div className="lg:col-span-2">
          <div className="mb-4 flex items-baseline justify-between">
            <h2 className="text-lg font-semibold text-content">This morning</h2>
            <Badge tone={alerts.length === 0 ? "sage" : "coral"} withDot>
              {alerts.length === 0
                ? "Nothing pressing"
                : `${alerts.length} ${alerts.length === 1 ? "item" : "items"}`}
            </Badge>
          </div>
          {alerts.length === 0 ? (
            <Card padding="lg">
              <p className="text-base font-medium leading-snug text-content">
                Nothing demands your attention.
              </p>
              <p className="mt-1.5 text-sm text-content-muted">
                Tenants are current and leases are running. Enjoy the morning.
              </p>
            </Card>
          ) : (
            <Card padding="none">
              <ul className="px-3 py-2">
                {alerts.slice(0, 6).map((a, i) => {
                  const action = alertAction(a);
                  return (
                    <li key={i}>
                      <Link
                        to={action.to}
                        className="group flex items-start gap-3 rounded-xl px-3 py-3 text-sm transition-colors hover:bg-surface-sunk focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/40"
                      >
                        <AlertSeverityDot type={a.type} />
                        <div className="min-w-0 flex-1">
                          <span
                            className={cn(
                              "inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider",
                              action.tone
                            )}
                          >
                            {action.label}
                          </span>
                          <p className="mt-1.5 leading-snug text-content-secondary group-hover:text-content">
                            {a.message}
                          </p>
                        </div>
                        <ChevronRight
                          aria-hidden
                          className="mt-0.5 h-4 w-4 shrink-0 text-content-muted transition-transform group-hover:translate-x-0.5 group-hover:text-content"
                        />
                      </Link>
                    </li>
                  );
                })}
                {alerts.length > 6 && (
                  <li className="px-3 py-3 text-xs text-content-muted">+{alerts.length - 6} more items</li>
                )}
              </ul>
            </Card>
          )}

          {/* SMS wallet — sits with the morning alerts because a dry balance
              silently stops rent reminders and receipts going out. */}
          <SmsBalanceCard compact className="mt-6" />
        </div>

        <div className="lg:col-span-3">
          {/* Rent status with the quick actions beside it — on a phone the
              actions sit in one row above the card. */}
          <div className="flex flex-col-reverse gap-5 sm:flex-row sm:items-center">
            <Card padding="none" className="min-w-0 flex-1">
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
            <div className="grid shrink-0 grid-cols-4 justify-items-center gap-x-3 gap-y-4 sm:grid-cols-2">
              <QuickAction to="/payments" icon={Wallet} label="Record" ariaLabel="Record payment" />
              <QuickAction to="/tenants?new=1" icon={UserPlus} label="Add tenant" />
              <QuickAction to="/notifications" icon={Send} label="Remind" ariaLabel="Remind tenants" />
              <QuickAction to="/reports" icon={BarChart3} label="Reports" ariaLabel="View reports" />
            </div>
          </div>

          <div className="mb-4 mt-8 flex items-baseline justify-between">
            <h2 className="text-lg font-semibold text-content">Recent payments</h2>
            <Link
              to="/payments"
              className="text-sm font-medium text-teal-700 transition-colors hover:text-teal-800"
            >
              All payments →
            </Link>
          </div>
          {recent_payments.length === 0 ? (
            <Card padding="lg">
              <p className="text-base font-medium leading-snug text-content">
                No payments recorded yet.
              </p>
              <p className="mt-1.5 text-sm text-content-muted">
                When tenants pay, the ledger appears here.
              </p>
            </Card>
          ) : (
            <Table minWidth={520}>
              <THead>
                <TR>
                  <TH>Tenant</TH>
                  <TH className="hidden sm:table-cell">Building / Unit</TH>
                  <TH className="hidden md:table-cell">Method</TH>
                  <TH className="text-right">Amount</TH>
                  <TH className="text-right">Date</TH>
                </TR>
              </THead>
              <TBody>
                {recent_payments.slice(0, 6).map((p) => (
                  <TR key={p.id}>
                    <TD>
                      <div className="flex w-max items-center gap-3">
                        <img
                          src={avatarFor(p.tenant_name)}
                          alt=""
                          aria-hidden
                          className="h-9 w-9 rounded-full ring-1 ring-border"
                        />
                        <span className="font-medium text-content">{p.tenant_name}</span>
                      </div>
                    </TD>
                    <TD className="hidden text-content-muted sm:table-cell">
                      {p.building_name} · {p.unit_label}
                    </TD>
                    <TD className="hidden md:table-cell">
                      <Badge tone="neutral">{p.source || "—"}</Badge>
                    </TD>
                    <TD className="text-right font-semibold tabular-nums text-content">
                      <span className="text-content-muted">KES </span>
                      {Number(p.amount).toLocaleString()}
                    </TD>
                    <TD className="text-right text-xs uppercase tracking-wider text-content-muted">
                      {p.payment_date}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
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
  /** Fuller name for screen readers when the visible label is a single word. */
  ariaLabel?: string;
}

function QuickAction({ to, icon: Icon, label, ariaLabel }: QuickActionProps) {
  return (
    <Link
      to={to}
      aria-label={ariaLabel}
      className="group flex w-16 flex-col items-center gap-1.5 rounded-2xl focus-visible:outline-none"
    >
      <span className="flex h-12 w-12 items-center justify-center rounded-2xl border border-border bg-surface text-content shadow-sm transition-all duration-200 group-hover:-translate-y-0.5 group-hover:bg-surface-sunk group-hover:shadow-md group-focus-visible:ring-2 group-focus-visible:ring-teal-500/40">
        <Icon className="h-5 w-5" strokeWidth={1.75} />
      </span>
      <span className="whitespace-nowrap text-xs font-medium text-content-secondary group-hover:text-content">
        {label}
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
      className={"mt-1.5 inline-block h-2 w-2 shrink-0 rounded-full " + color}
      aria-hidden
    />
  );
}
