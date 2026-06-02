import { format } from "date-fns";
import {
  ArrowUpRight,
  CreditCard,
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
  EmptyState,
  ErrorState,
  Skeleton,
} from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import { useDashboard, type DashboardData } from "@/hooks/useDashboard";
import { displayName } from "@/lib/displayName";
import { avatarFor, propertyImage } from "@/lib/images";

const OCCUPANCY_COLORS = [
  "rgb(216,154,58)",   // amber gold — paid
  "rgb(214,182,118)",  // ochre — partial
  "rgb(170,100,75)",   // muted rust — unpaid
  "rgb(180,124,40)",   // deeper gold — arrears
  "rgb(225,220,214)",  // taupe — vacant
];

function KES(n: number) {
  return `KES ${Number(n || 0).toLocaleString()}`;
}

function formatK(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k`;
  return String(n);
}

function greetingFor(hour: number) {
  if (hour < 5) return "Good evening";
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

function headlineFor(data: DashboardData): string {
  const { kpis, alerts, recent_payments } = data;
  const overdue = alerts.filter((a) => a.type === "overdue").length;
  const expiring = alerts.filter((a) => a.type === "expiring_lease" || a.type === "move_out").length;

  if (overdue > 0) {
    return overdue === 1
      ? "One tenant is overdue."
      : `${overdue} tenants are overdue.`;
  }
  if (expiring > 0) {
    return expiring === 1
      ? "A lease changes this week."
      : `${expiring} leases change this week.`;
  }
  if (recent_payments.length > 0) {
    const today = recent_payments.filter(
      (p) => p.payment_date === new Date().toISOString().slice(0, 10)
    ).length;
    if (today > 0) {
      return today === 1
        ? "One payment landed today."
        : `${today} payments landed today.`;
    }
  }
  if (kpis.total_arrears === 0 && kpis.vacant === 0) {
    return "The portfolio is in good order.";
  }
  return "Quiet so far.";
}

export default function DashboardPage() {
  const { data, isLoading, isError, refetch } = useDashboard();
  const { user } = useAuth();

  const firstName = user?.first_name?.trim() || displayName(user?.email?.split("@")[0]) || "there";
  const today = new Date();
  const dateLine = format(today, "EEEE, d MMMM").toUpperCase();
  const greeting = `${greetingFor(today.getHours())}, ${firstName}.`;

  if (isError && !data) {
    return (
      <div className="space-y-10">
        <header className="space-y-2">
          <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-ink-500">
            {dateLine}
          </p>
          <h1 className="font-display text-4xl font-semibold leading-tight text-ink-900 sm:text-5xl">
            {greeting}
          </h1>
        </header>
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
        <header className="space-y-2">
          <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-ink-500">
            {dateLine}
          </p>
          <h1 className="font-display text-4xl font-semibold leading-tight text-ink-900 sm:text-5xl">
            {greeting}
          </h1>
          <Skeleton className="h-4 w-64" />
        </header>
        <Skeleton className="h-48 w-full" rounded="lg" />
        <Skeleton className="h-[280px] w-full" rounded="lg" />
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

  const headline = headlineFor(data);
  const monthLabel = format(today, "MMMM").toUpperCase();

  return (
    <div className="space-y-12">
      {/* ── Editorial masthead ────────────────────────────────────────────── */}
      <header className="flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-ink-500">
            {dateLine}
          </p>
          <h1 className="mt-3 font-display text-4xl font-semibold leading-[1.05] text-ink-900 sm:text-5xl">
            {greeting}
          </h1>
          <p className="mt-3 max-w-2xl font-display text-xl font-normal leading-snug text-ink-500">
            {headline}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link to="/payments">
            <Button variant="glass" size="md">
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
        </div>
      </header>

      {/* ── Lead figure: collection + occupancy ───────────────────────────── */}
      <section className="grid gap-10 lg:grid-cols-3 lg:gap-12">
        {/* Collection — the lead figure */}
        <div className="lg:col-span-2">
          <div className="flex items-baseline justify-between gap-4 border-b border-ink-200 pb-3">
            <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-ink-500">
              {monthLabel} · Collected
            </p>
            <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-ink-500">
              of {KES(kpis.collection_expected)} expected
            </p>
          </div>
          <div className="mt-6 flex flex-wrap items-end justify-between gap-6">
            <p className="font-display text-4xl font-semibold leading-none tracking-tight text-ink-900 sm:text-5xl lg:text-[4rem]">
              <span className="text-ink-400">KES </span>
              <span className="tabular-nums">{Math.round(thisMonth).toLocaleString()}</span>
            </p>
            <div className="text-right">
              <p className="font-display text-3xl font-semibold tabular-nums text-ink-900 sm:text-4xl">
                {collectionPct}
                <span className="ml-0.5 text-xl text-ink-400">%</span>
              </p>
              {lastMonth > 0 ? (
                <p className="mt-1 text-xs uppercase tracking-[0.16em] text-ink-500">
                  {trendSign}{trendDelta.toFixed(1)}% vs last month
                </p>
              ) : (
                <p className="mt-1 text-xs uppercase tracking-[0.16em] text-ink-500">
                  First month on record
                </p>
              )}
            </div>
          </div>
          {/* Hairline progress */}
          <div className="mt-6 h-px w-full bg-ink-100">
            <div
              className="h-px bg-sage-500 transition-[width] duration-700 ease-out"
              style={{ width: `${Math.min(100, collectionPct)}%` }}
            />
          </div>
          {/* Income trend — no card walls */}
          <div className="mt-6 h-[200px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart
                data={income_trend}
                margin={{ top: 10, right: 4, left: -20, bottom: 0 }}
              >
                <defs>
                  <linearGradient id="incomeGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="rgb(216,154,58)" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="rgb(216,154,58)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="month"
                  tickLine={false}
                  axisLine={false}
                  tick={{ fill: "rgb(120,100,90)", fontSize: 11 }}
                />
                <YAxis
                  tickLine={false}
                  axisLine={false}
                  tick={{ fill: "rgb(120,100,90)", fontSize: 11 }}
                  tickFormatter={formatK}
                />
                <RcTooltip
                  cursor={{ stroke: "rgba(216,154,58,0.3)" }}
                  contentStyle={{
                    background: "rgba(255,255,255,0.96)",
                    border: "1px solid rgba(44,31,26,0.08)",
                    borderRadius: 10,
                    boxShadow: "0 10px 28px -8px rgba(44,31,26,0.12)",
                    fontSize: 12,
                  }}
                  formatter={(v) => [KES(Number(v)), "Income"]}
                />
                <Area
                  type="monotone"
                  dataKey="amount"
                  stroke="rgb(216,154,58)"
                  strokeWidth={2.5}
                  fill="url(#incomeGrad)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Occupancy — quiet sidebar */}
        <div className="lg:border-l lg:border-ink-200 lg:pl-12">
          <div className="border-b border-ink-200 pb-3">
            <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-ink-500">
              Occupancy
            </p>
          </div>
          <div className="relative mx-auto mt-4 flex h-[180px] w-full items-center justify-center">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={occData}
                  dataKey="value"
                  innerRadius={56}
                  outerRadius={80}
                  paddingAngle={2}
                  stroke="none"
                >
                  {occData.map((_, i) => (
                    <Cell key={i} fill={OCCUPANCY_COLORS[i % OCCUPANCY_COLORS.length]} />
                  ))}
                </Pie>
                <RcTooltip
                  contentStyle={{
                    background: "rgba(255,255,255,0.96)",
                    border: "1px solid rgba(44,31,26,0.08)",
                    borderRadius: 10,
                    fontSize: 12,
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
              <p className="font-display text-4xl font-semibold tabular-nums text-ink-900">
                {occupancyPct}
                <span className="text-xl text-ink-400">%</span>
              </p>
              <p className="mt-1 text-[10px] uppercase tracking-[0.18em] text-ink-500">
                {kpis.occupied} of {kpis.total_units} occupied
              </p>
            </div>
          </div>
          <ul className="mt-6 space-y-2 text-xs">
            {occData.map((d, i) => (
              <li key={d.name} className="flex items-center gap-3">
                <span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{ background: OCCUPANCY_COLORS[i % OCCUPANCY_COLORS.length] }}
                />
                <span className="text-ink-500">{d.name}</span>
                <span className="ml-auto font-medium tabular-nums text-ink-900">{d.value}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ── Supporting figure row ─────────────────────────────────────────── */}
      <section className="grid grid-cols-2 divide-x divide-ink-200 border-y border-ink-200 sm:grid-cols-4">
        <Figure
          label="Total units"
          value={kpis.total_units.toString()}
          caption={`${kpis.occupied} occupied · ${kpis.vacant} vacant`}
        />
        <Figure
          label="Active tenants"
          value={kpis.active_tenants.toString()}
          caption={kpis.active_tenants === 1 ? "Single tenancy" : "Across the portfolio"}
        />
        <Figure
          label="Outstanding"
          value={KES(kpis.total_arrears).replace("KES ", "")}
          prefix="KES "
          caption={kpis.total_arrears > 0 ? "Awaiting payment" : "All settled"}
          tone={kpis.total_arrears > 0 ? "alert" : "neutral"}
        />
        <Figure
          label="Last month"
          value={KES(lastMonth).replace("KES ", "")}
          prefix="KES "
          caption={lastMonth > 0 ? "Collected in full" : "No record yet"}
        />
      </section>

      {/* ── This morning + Recent payments ────────────────────────────────── */}
      <section className="grid gap-10 lg:grid-cols-2 lg:gap-12">
        <div>
          <div className="flex items-baseline justify-between border-b border-ink-200 pb-3">
            <h2 className="font-display text-xl font-semibold text-ink-900">
              This morning
            </h2>
            <Badge tone={alerts.length === 0 ? "sage" : "coral"} withDot>
              {alerts.length === 0
                ? "Nothing pressing"
                : `${alerts.length} ${alerts.length === 1 ? "item" : "items"}`}
            </Badge>
          </div>
          {alerts.length === 0 ? (
            <div className="mt-6 max-w-md">
              <p className="font-display text-lg leading-snug text-ink-700">
                Nothing demands your attention.
              </p>
              <p className="mt-1 text-sm text-ink-500">
                Tenants are current, leases are running, and the portfolio is quiet. Enjoy the morning.
              </p>
            </div>
          ) : (
            <ul className="mt-4 divide-y divide-ink-100">
              {alerts.slice(0, 6).map((a, i) => (
                <li key={i} className="flex items-start gap-3 py-3 text-sm">
                  <AlertSeverityDot type={a.type} />
                  <p className="leading-snug text-ink-700">{a.message}</p>
                </li>
              ))}
              {alerts.length > 6 && (
                <li className="pt-3 text-xs text-ink-500">
                  +{alerts.length - 6} more items
                </li>
              )}
            </ul>
          )}
        </div>

        <div>
          <div className="flex items-baseline justify-between border-b border-ink-200 pb-3">
            <h2 className="font-display text-xl font-semibold text-ink-900">
              Recent payments
            </h2>
            <Link
              to="/payments"
              className="text-xs font-medium uppercase tracking-[0.18em] text-sage-600 hover:text-sage-700"
            >
              All payments
            </Link>
          </div>
          {recent_payments.length === 0 ? (
            <div className="mt-6 max-w-md">
              <p className="font-display text-lg leading-snug text-ink-700">
                No payments recorded yet.
              </p>
              <p className="mt-1 text-sm text-ink-500">
                When tenants pay, the ledger appears here.
              </p>
            </div>
          ) : (
            <ul className="mt-2 divide-y divide-ink-100">
              {recent_payments.slice(0, 6).map((p) => (
                <li key={p.id} className="flex items-center gap-3 py-3">
                  <img
                    src={avatarFor(p.tenant_name)}
                    alt=""
                    aria-hidden
                    className="h-9 w-9 rounded-full ring-1 ring-ink-200/60"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink-900">{p.tenant_name}</p>
                    <p className="truncate text-[11px] text-ink-500">
                      {p.building_name} · {p.unit_label}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="font-display text-base font-semibold tabular-nums text-ink-900">
                      <span className="text-ink-400">KES </span>
                      {Number(p.amount).toLocaleString()}
                    </p>
                    <p className="text-[10px] uppercase tracking-[0.14em] text-ink-400">
                      {p.payment_date}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      {/* ── Properties — the editorial gallery ────────────────────────────── */}
      {buildings.length > 0 && (
        <section>
          <div className="flex items-baseline justify-between border-b border-ink-200 pb-3">
            <div>
              <h2 className="font-display text-xl font-semibold text-ink-900">Properties</h2>
              <p className="mt-1 text-sm text-ink-500">
                {buildings.length} {buildings.length === 1 ? "building" : "buildings"} in the portfolio
              </p>
            </div>
            <Link
              to="/buildings"
              className="text-xs font-medium uppercase tracking-[0.18em] text-sage-600 hover:text-sage-700"
            >
              Manage
            </Link>
          </div>
          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {buildings.slice(0, 6).map((b) => {
              const rate = b.total > 0 ? Math.round((b.occupied / b.total) * 100) : 0;
              return (
                <Link
                  key={b.id}
                  to="/buildings"
                  className="group relative block overflow-hidden rounded-md transition-all hover:-translate-y-0.5"
                >
                  <div className="relative h-44 w-full overflow-hidden rounded-md">
                    <img
                      src={propertyImage(b.id ?? b.name, "md")}
                      alt={b.name}
                      loading="lazy"
                      className="h-full w-full object-cover transition-transform duration-700 ease-out group-hover:scale-[1.04]"
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-ink-900/70 via-ink-900/10 to-transparent" />
                    <div className="absolute bottom-3 left-3 right-3 flex items-end justify-between gap-3">
                      <p className="truncate font-display text-base font-semibold text-white">
                        {b.name}
                      </p>
                      <p className="font-display text-base font-semibold tabular-nums text-white">
                        {rate}<span className="text-sm text-white/70">%</span>
                      </p>
                    </div>
                  </div>
                  <div className="mt-3 flex items-center gap-4 text-xs">
                    <span className="text-ink-500">
                      <span className="font-medium tabular-nums text-ink-900">{b.occupied}</span> occupied
                    </span>
                    <span className="text-ink-300">·</span>
                    <span className="text-ink-500">
                      <span className="font-medium tabular-nums text-ink-900">{b.vacant}</span> vacant
                    </span>
                    <span className="ml-auto text-ink-400">{b.total} total</span>
                  </div>
                </Link>
              );
            })}
          </div>
          {buildings.length > 1 && (
            <div className="mt-10">
              <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-ink-500">
                By building
              </p>
              <div className="mt-3 h-[180px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={buildings}
                    margin={{ top: 10, right: 4, left: -20, bottom: 0 }}
                    barCategoryGap="28%"
                  >
                    <XAxis
                      dataKey="name"
                      tickLine={false}
                      axisLine={false}
                      tick={{ fill: "rgb(120,100,90)", fontSize: 11 }}
                    />
                    <YAxis
                      tickLine={false}
                      axisLine={false}
                      tick={{ fill: "rgb(120,100,90)", fontSize: 11 }}
                    />
                    <RcTooltip
                      cursor={{ fill: "rgba(216,154,58,0.06)" }}
                      contentStyle={{
                        background: "rgba(255,255,255,0.96)",
                        border: "1px solid rgba(44,31,26,0.08)",
                        borderRadius: 10,
                        fontSize: 12,
                      }}
                    />
                    <Bar dataKey="occupied" stackId="u" fill="rgb(216,154,58)" />
                    <Bar dataKey="vacant" stackId="u" fill="rgb(225,220,214)" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </section>
      )}

      {/* If no buildings at all */}
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

interface FigureProps {
  label: string;
  value: string;
  prefix?: string;
  caption: string;
  tone?: "neutral" | "alert";
}

function Figure({ label, value, prefix, caption, tone = "neutral" }: FigureProps) {
  return (
    <div className="px-5 py-5 first:pl-0 last:pr-0 sm:py-6">
      <p className="text-[10px] font-medium uppercase tracking-[0.22em] text-ink-500">
        {label}
      </p>
      <p className="mt-3 font-display text-2xl font-semibold leading-none tabular-nums text-ink-900 sm:text-3xl">
        {prefix && <span className="text-ink-400">{prefix}</span>}
        {value}
      </p>
      <p
        className={
          "mt-2 text-xs " +
          (tone === "alert" ? "text-coral-600" : "text-ink-500")
        }
      >
        {caption}
      </p>
    </div>
  );
}

function AlertSeverityDot({ type }: { type: string }) {
  const color =
    type === "overdue"
      ? "bg-status-unpaid"
      : type === "partial" || type === "expiring_lease"
      ? "bg-status-partial"
      : type === "move_out"
      ? "bg-peri-500"
      : "bg-ink-300";
  return (
    <span
      className={"mt-1.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full " + color}
      aria-hidden
    />
  );
}
