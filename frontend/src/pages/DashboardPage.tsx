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
import { useAuth } from "@/hooks/useAuth";
import { useDashboard, type DashboardData } from "@/hooks/useDashboard";
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

  const firstName = user?.first_name?.trim() || "Wilson";
  const today = new Date();
  const dateLine = format(today, "EEEE, d MMMM").toUpperCase();
  const greeting = `Welcome back, ${firstName}.`;

  if (isError && !data) {
    return (
      <div className="space-y-8">
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
      <div className="space-y-8">
        <Masthead dateLine={dateLine} greeting={greeting} />
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28 w-full" rounded="lg" />
          ))}
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          <Skeleton className="h-[280px] w-full lg:col-span-2" rounded="lg" />
          <Skeleton className="h-[280px] w-full" rounded="lg" />
        </div>
        <Skeleton className="h-64 w-full" rounded="lg" />
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
  const monthLabel = format(today, "MMMM");

  return (
    <div className="space-y-8">
      {/* ── Masthead with actions ─────────────────────────────────────────── */}
      <Masthead dateLine={dateLine} greeting={greeting} headline={headline}>
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
      </Masthead>

      {/* ── KPI tiles ─────────────────────────────────────────────────────── */}
      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Kpi
          label="Total units"
          value={kpis.total_units.toLocaleString()}
          caption={`${kpis.occupied} occupied · ${kpis.vacant} vacant`}
        />
        <Kpi
          label="Occupancy"
          value={`${occupancyPct}%`}
          progress={occupancyPct}
        />
        <Kpi
          label={`Collected · ${monthLabel}`}
          value={`${collectionPct}%`}
          caption={`${KES(kpis.collection_received)} of ${KES(kpis.collection_expected).replace("KES ", "")}`}
        />
        <Kpi
          label="Arrears"
          value={KES(kpis.total_arrears)}
          caption={kpis.total_arrears > 0 ? `${alerts.filter((a) => a.type === "overdue").length} tenants overdue` : "All settled"}
          tone={kpis.total_arrears > 0 ? "alert" : "neutral"}
        />
      </section>

      {/* ── Income trend + Rent status ────────────────────────────────────── */}
      <section className="grid gap-4 lg:grid-cols-3">
        <Card variant="flat" padding="none" className="ring-1 ring-ink-200/70 lg:col-span-2">
          <div className="flex items-center justify-between border-b border-ink-200 px-5 py-4">
            <h2 className="font-display text-lg font-semibold text-ink-900">
              Income — last 6 months
            </h2>
            {lastMonth > 0 ? (
              <Badge tone={trendDelta >= 0 ? "sage" : "coral"}>
                {trendSign}{trendDelta.toFixed(1)}% vs last month
              </Badge>
            ) : (
              <Badge tone="neutral">First month on record</Badge>
            )}
          </div>
          <div className="h-[220px] px-2 py-4">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart
                data={income_trend}
                margin={{ top: 10, right: 12, left: -8, bottom: 0 }}
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
        </Card>

        <Card variant="flat" padding="none" className="ring-1 ring-ink-200/70">
          <div className="border-b border-ink-200 px-5 py-4">
            <h2 className="font-display text-lg font-semibold text-ink-900">Rent status</h2>
          </div>
          <div className="p-5">
            <div className="relative mx-auto flex h-[160px] w-full items-center justify-center">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={occData}
                    dataKey="value"
                    innerRadius={52}
                    outerRadius={74}
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
                <p className="font-display text-3xl font-semibold tabular-nums text-ink-900">
                  {occupancyPct}
                  <span className="text-lg text-ink-400">%</span>
                </p>
                <p className="mt-0.5 text-[10px] uppercase tracking-[0.16em] text-ink-500">
                  occupied
                </p>
              </div>
            </div>
            <ul className="mt-5 space-y-2 text-xs">
              {occData.map((d, i) => (
                <li key={d.name} className="flex items-center gap-3">
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{ background: OCCUPANCY_COLORS[i % OCCUPANCY_COLORS.length] }}
                  />
                  <span className="text-ink-500">{d.name}</span>
                  <span className="ml-auto font-medium tabular-nums text-ink-900">{d.value}</span>
                </li>
              ))}
            </ul>
          </div>
        </Card>
      </section>

      {/* ── This morning + Recent payments ────────────────────────────────── */}
      <section className="grid gap-4 lg:grid-cols-5">
        <Card variant="flat" padding="none" className="ring-1 ring-ink-200/70 lg:col-span-2">
          <div className="flex items-center justify-between border-b border-ink-200 px-5 py-4">
            <h2 className="font-display text-lg font-semibold text-ink-900">This morning</h2>
            <Badge tone={alerts.length === 0 ? "sage" : "coral"} withDot>
              {alerts.length === 0
                ? "Nothing pressing"
                : `${alerts.length} ${alerts.length === 1 ? "item" : "items"}`}
            </Badge>
          </div>
          {alerts.length === 0 ? (
            <div className="px-5 py-6">
              <p className="font-display text-base leading-snug text-ink-700">
                Nothing demands your attention.
              </p>
              <p className="mt-1 text-sm text-ink-500">
                Tenants are current and leases are running. Enjoy the morning.
              </p>
            </div>
          ) : (
            <ul className="divide-y divide-ink-100 px-5">
              {alerts.slice(0, 6).map((a, i) => (
                <li key={i} className="flex items-start gap-3 py-3 text-sm">
                  <AlertSeverityDot type={a.type} />
                  <p className="leading-snug text-ink-700">{a.message}</p>
                </li>
              ))}
              {alerts.length > 6 && (
                <li className="py-3 text-xs text-ink-500">+{alerts.length - 6} more items</li>
              )}
            </ul>
          )}
        </Card>

        <div className="lg:col-span-3">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="font-display text-lg font-semibold text-ink-900">Recent payments</h2>
            <Link
              to="/payments"
              className="text-xs font-medium uppercase tracking-[0.16em] text-sage-600 hover:text-sage-700"
            >
              All payments →
            </Link>
          </div>
          {recent_payments.length === 0 ? (
            <Card variant="flat" padding="lg" className="ring-1 ring-ink-200/70">
              <p className="font-display text-base leading-snug text-ink-700">
                No payments recorded yet.
              </p>
              <p className="mt-1 text-sm text-ink-500">
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
                          className="h-8 w-8 rounded-full ring-1 ring-ink-200/60"
                        />
                        <span className="font-medium text-ink-900">{p.tenant_name}</span>
                      </div>
                    </TD>
                    <TD className="hidden text-ink-500 sm:table-cell">
                      {p.building_name} · {p.unit_label}
                    </TD>
                    <TD className="hidden md:table-cell">
                      <Badge tone="neutral">{p.source || "—"}</Badge>
                    </TD>
                    <TD className="text-right font-display font-semibold tabular-nums text-ink-900">
                      <span className="text-ink-400">KES </span>
                      {Number(p.amount).toLocaleString()}
                    </TD>
                    <TD className="text-right text-xs uppercase tracking-[0.12em] text-ink-400">
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
          <div className="flex items-baseline justify-between border-b border-ink-200 pb-3">
            <div>
              <h2 className="font-display text-lg font-semibold text-ink-900">Properties</h2>
              <p className="mt-1 text-sm text-ink-500">
                {buildings.length} {buildings.length === 1 ? "building" : "buildings"} in the portfolio
              </p>
            </div>
            <Link
              to="/buildings"
              className="text-xs font-medium uppercase tracking-[0.16em] text-sage-600 hover:text-sage-700"
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
                  className="group relative block overflow-hidden rounded-lg ring-1 ring-ink-200/70 transition-all hover:-translate-y-0.5 hover:shadow-float"
                >
                  <div className="relative h-40 w-full overflow-hidden">
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
                  <div className="flex items-center gap-4 bg-white px-3 py-3 text-xs">
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
            <Card variant="flat" padding="none" className="mt-6 ring-1 ring-ink-200/70">
              <div className="border-b border-ink-200 px-5 py-4">
                <h3 className="font-display text-base font-semibold text-ink-900">Occupancy by building</h3>
              </div>
              <div className="h-[200px] px-2 py-4">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={buildings}
                    margin={{ top: 10, right: 12, left: -8, bottom: 0 }}
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
    <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-ink-500">
          {dateLine}
        </p>
        <h1 className="mt-2 font-display text-3xl font-semibold leading-tight text-ink-900 sm:text-4xl">
          {greeting}
        </h1>
        {headline && (
          <p className="mt-2 font-display text-lg font-normal leading-snug text-ink-500">
            {headline}
          </p>
        )}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </header>
  );
}

interface KpiProps {
  label: string;
  value: string;
  caption?: string;
  progress?: number;
  tone?: "neutral" | "alert";
}

function Kpi({ label, value, caption, progress, tone = "neutral" }: KpiProps) {
  return (
    <Card variant="flat" padding="md" className="ring-1 ring-ink-200/70">
      <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-ink-500">
        {label}
      </p>
      <p
        className={cn(
          "mt-2 font-display text-2xl font-semibold leading-none tabular-nums sm:text-3xl",
          tone === "alert" ? "text-coral-600" : "text-ink-900"
        )}
      >
        {value}
      </p>
      {progress !== undefined && (
        <div className="mt-3 h-1.5 w-full rounded-full bg-ink-100">
          <div
            className="h-1.5 rounded-full bg-sage-500 transition-[width] duration-700 ease-out"
            style={{ width: `${Math.min(100, progress)}%` }}
          />
        </div>
      )}
      {caption && (
        <p className={cn("mt-2 text-xs", tone === "alert" ? "text-coral-600" : "text-ink-500")}>
          {caption}
        </p>
      )}
    </Card>
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
