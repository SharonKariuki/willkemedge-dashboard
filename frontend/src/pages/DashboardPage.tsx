import { format } from "date-fns";
import {
  AlertTriangle,
  ArrowUpRight,
  Building2,
  CreditCard,
  UserPlus,
  TrendingDown,
  TrendingUp,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { Link } from "react-router-dom";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as RcTooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  Badge,
  Button,
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
import { cn } from "@/lib/cn";
import { useDashboard } from "@/hooks/useDashboard";
import { avatarFor, propertyImage } from "@/lib/images";

// Chart palette — teal (income/occupied) + semantic status, no rainbow.
const OCCUPANCY_COLORS = [
  "rgb(22,163,74)",   // Paid — success
  "rgb(217,119,6)",   // Partial — warning
  "rgb(220,38,38)",   // Unpaid — danger
  "rgb(234,88,12)",   // Arrears — orange (attention)
  "rgb(203,213,225)", // Vacant — neutral-300
];
const TEAL = "rgb(13,148,136)";
const AXIS_TICK = { fill: "rgb(100,116,139)", fontSize: 12 };
const TOOLTIP_STYLE = {
  background: "rgb(255,255,255)",
  border: "1px solid rgb(226,232,240)",
  borderRadius: 14,
  boxShadow: "0 14px 34px -10px rgba(15,23,42,0.14)",
  fontSize: 13,
  padding: "10px 14px",
} as const;

function KES(n: number) {
  return `KES ${Number(n || 0).toLocaleString()}`;
}

function formatK(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k`;
  return String(n);
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

  const { kpis, income_trend, occupancy, buildings, recent_payments, alerts } = data;

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

  const thisMonth = kpis.collection_received;
  const lastMonth = kpis.last_month_received ?? 0;
  const trendDelta =
    lastMonth > 0 ? ((thisMonth - lastMonth) / lastMonth) * 100 : 0;
  const trendSign = trendDelta >= 0 ? "+" : "";

  const collectionPct = kpis.collection_expected > 0
    ? Math.round((kpis.collection_received / kpis.collection_expected) * 100)
    : kpis.collection_percentage ?? 0;

  const monthLabel = format(today, "MMMM");

  return (
    <div className="space-y-10 lg:space-y-12">
      {/* ── Masthead with actions ─────────────────────────────────────────── */}
      <Masthead dateLine={dateLine} greeting={greeting}>
        <Link to="/tenants?new=1">
          <Button variant="outline" size="md">
            <UserPlus className="h-4 w-4" />
            Add tenant
          </Button>
        </Link>
        <Link to="/payments">
          <Button variant="outline" size="md">
            <CreditCard className="h-4 w-4" />
            Record payment
          </Button>
        </Link>
        <Link to="/reports">
          <Button variant="primary" size="md">
            View reports
            <ArrowUpRight className="h-4 w-4" />
          </Button>
        </Link>
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

      {/* ── Income trend + Rent status ────────────────────────────────────── */}
      <section className="grid gap-6 lg:grid-cols-3">
        <Card padding="none" className="lg:col-span-2">
          <div className="flex items-center justify-between px-6 pt-4">
            <div>
              <h2 className="text-lg font-semibold text-content">Income</h2>
              <p className="mt-0.5 text-sm text-content-muted">Last 6 months</p>
            </div>
            {lastMonth > 0 ? (
              <Badge tone={trendDelta >= 0 ? "sage" : "coral"}>
                {trendDelta >= 0 ? (
                  <TrendingUp className="h-3.5 w-3.5" />
                ) : (
                  <TrendingDown className="h-3.5 w-3.5" />
                )}
                {trendSign}{trendDelta.toFixed(1)}% vs last month
              </Badge>
            ) : (
              <Badge tone="neutral">First month on record</Badge>
            )}
          </div>
          <div className="h-[150px] px-3 pb-3 pt-3">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart
                data={income_trend}
                margin={{ top: 10, right: 12, left: -8, bottom: 0 }}
              >
                <defs>
                  <linearGradient id="incomeGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={TEAL} stopOpacity={0.28} />
                    <stop offset="100%" stopColor={TEAL} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="month" tickLine={false} axisLine={false} tick={AXIS_TICK} dy={6} />
                <YAxis tickLine={false} axisLine={false} tick={AXIS_TICK} tickFormatter={formatK} />
                <RcTooltip
                  cursor={{ stroke: "rgba(13,148,136,0.35)" }}
                  contentStyle={TOOLTIP_STYLE}
                  formatter={(v) => [KES(Number(v)), "Income"]}
                />
                <Area
                  type="monotone"
                  dataKey="amount"
                  stroke={TEAL}
                  strokeWidth={2.5}
                  fill="url(#incomeGrad)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card padding="none">
          <div className="px-6 pt-4">
            <h2 className="text-lg font-semibold text-content">Rent status</h2>
          </div>
          <div className="p-4">
            <div className="relative mx-auto flex h-[112px] w-full items-center justify-center">
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
            <ul className="mt-4 space-y-2 text-sm">
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
      </section>

      {/* ── This morning + Recent payments ────────────────────────────────── */}
      <section className="grid gap-6 lg:grid-cols-5">
        <Card padding="none" className="lg:col-span-2">
          <div className="flex items-center justify-between px-6 pt-6">
            <h2 className="text-lg font-semibold text-content">This morning</h2>
            <Badge tone={alerts.length === 0 ? "sage" : "coral"} withDot>
              {alerts.length === 0
                ? "Nothing pressing"
                : `${alerts.length} ${alerts.length === 1 ? "item" : "items"}`}
            </Badge>
          </div>
          {alerts.length === 0 ? (
            <div className="px-6 pb-6 pt-4">
              <p className="text-base font-medium leading-snug text-content">
                Nothing demands your attention.
              </p>
              <p className="mt-1.5 text-sm text-content-muted">
                Tenants are current and leases are running. Enjoy the morning.
              </p>
            </div>
          ) : (
            <ul className="mt-2 px-6 pb-3">
              {alerts.slice(0, 6).map((a, i) => (
                <li key={i} className="flex items-start gap-3 py-3 text-sm">
                  <AlertSeverityDot type={a.type} />
                  <p className="leading-snug text-content-secondary">{a.message}</p>
                </li>
              ))}
              {alerts.length > 6 && (
                <li className="py-3 text-xs text-content-muted">+{alerts.length - 6} more items</li>
              )}
            </ul>
          )}
        </Card>

        <div className="lg:col-span-3">
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
            <Card padding="lg">
              <p className="text-base font-medium leading-snug text-content">
                No payments recorded yet.
              </p>
              <p className="mt-1.5 text-sm text-content-muted">
                When tenants pay, the ledger appears here.
              </p>
            </Card>
          ) : (
            <Table>
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
                      <div className="flex items-center gap-3">
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
                    <img
                      src={propertyImage(b.id ?? b.name, "md")}
                      alt={b.name}
                      loading="lazy"
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
            <Card padding="none" className="mt-8">
              <div className="px-6 pt-6">
                <h3 className="text-lg font-semibold text-content">Occupancy by building</h3>
              </div>
              <div className="h-[220px] px-3 pb-4 pt-6">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={buildings}
                    margin={{ top: 10, right: 12, left: -8, bottom: 0 }}
                    barCategoryGap="30%"
                  >
                    <XAxis dataKey="name" tickLine={false} axisLine={false} tick={AXIS_TICK} dy={6} />
                    <YAxis tickLine={false} axisLine={false} tick={AXIS_TICK} />
                    <RcTooltip cursor={{ fill: "rgba(13,148,136,0.06)" }} contentStyle={TOOLTIP_STYLE} />
                    <Bar dataKey="occupied" stackId="u" fill={TEAL} radius={[0, 0, 0, 0]} />
                    <Bar dataKey="vacant" stackId="u" fill="rgb(203,213,225)" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
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
      {children && <div className="flex flex-wrap items-center gap-2.5">{children}</div>}
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
