import {
  AlertTriangle,
  ArrowUpRight,
  Banknote,
  Building2,
  CreditCard,
  Home,
  TrendingUp,
  Users,
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

import ProgressBar from "@/components/ProgressBar";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  CardTitle,
  EmptyState,
  PageHeader,
  Skeleton,
  Stat,
} from "@/components/ui";
import { useDashboard } from "@/hooks/useDashboard";
import { cn } from "@/lib/cn";
import { avatarFor, propertyImage } from "@/lib/images";

const OCCUPANCY_COLORS = [
  "rgb(216,154,58)",   // Paid — amber gold
  "rgb(200,195,190)",  // Partial — warm grey
  "rgb(70,65,60)",     // Unpaid — charcoal
  "rgb(170,100,75)",   // Arrears — deep rust
  "rgb(225,220,214)",  // Vacant — light warm grey
];

function KES(n: number) {
  return `KES ${Number(n || 0).toLocaleString()}`;
}

function formatK(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k`;
  return String(n);
}

export default function DashboardPage() {
  const { data, isLoading } = useDashboard();

  if (isLoading || !data) {
    return (
      <div className="space-y-6">
        <PageHeader eyebrow="Overview" title="Loading portfolio…" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full" rounded="lg" />
          ))}
        </div>
        <Skeleton className="h-[280px] w-full" rounded="lg" />
      </div>
    );
  }

  const { kpis, income_trend, occupancy, buildings, recent_payments, alerts } = data;
  const occupancyPct = kpis.total_units > 0 ? Math.round((kpis.occupied / kpis.total_units) * 100) : 0;

  const occData = [
    { name: "Paid", value: occupancy.paid },
    { name: "Partial", value: occupancy.partial },
    { name: "Unpaid", value: occupancy.unpaid },
    { name: "Arrears", value: occupancy.arrears },
    { name: "Vacant", value: occupancy.vacant },
  ].filter((d) => d.value > 0);

  const lastMonth = income_trend[income_trend.length - 2]?.amount ?? 0;
  const thisMonth = income_trend[income_trend.length - 1]?.amount ?? 0;
  const trendDelta = lastMonth > 0 ? ((thisMonth - lastMonth) / lastMonth) * 100 : 0;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Portfolio overview"
        title="Dashboard"
        actions={
          <>
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
          </>
        }
      />

      {/* KPIs */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Total units"
          value={kpis.total_units}
          icon={<Home className="h-5 w-5" />}
          tone="peri"
          deltaLabel={`${kpis.occupied} occupied`}
        />
        <Stat
          label="Active tenants"
          value={kpis.active_tenants}
          icon={<Users className="h-5 w-5" />}
          tone="sage"
          deltaLabel={`${kpis.vacant} vacant units`}
        />
        <Stat
          label="This month"
          value={Math.round(kpis.collection_received)}
          prefix="KES "
          icon={<Banknote className="h-5 w-5" />}
          tone="ochre"
          delta={trendDelta}
          deltaLabel="vs last month"
        />
        <Stat
          label="Total arrears"
          value={Math.round(kpis.total_arrears)}
          prefix="KES "
          icon={<AlertTriangle className="h-5 w-5" />}
          tone="coral"
          deltaLabel={kpis.total_arrears > 0 ? "needs attention" : "all clear"}
        />
      </div>

      {/* Collection progress + occupancy gauge */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card variant="glass" padding="md" className="lg:col-span-2">
          <CardHeader>
            <div>
              <CardTitle>Monthly collection</CardTitle>
              <p className="mt-1 text-xs text-ink-500">
                {KES(kpis.collection_received)} of {KES(kpis.collection_expected)} expected
              </p>
            </div>
            <div className="text-right">
              <p className="font-display text-3xl font-semibold text-ink-900">
                {kpis.collection_percentage}%
              </p>
              <Badge tone={kpis.collection_percentage >= 80 ? "sage" : "coral"} withDot className="mt-1">
                {kpis.collection_percentage >= 80 ? "On track" : "Below target"}
              </Badge>
            </div>
          </CardHeader>
          <ProgressBar percentage={kpis.collection_percentage} showLabel={false} tone="sage" />
          <div className="mt-6 h-[180px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={income_trend} margin={{ top: 10, right: 4, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="incomeGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="rgb(216,154,58)" stopOpacity={0.45} />
                    <stop offset="100%" stopColor="rgb(216,154,58)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="month"
                  tickLine={false}
                  axisLine={false}
                  tick={{ fill: "rgb(140,144,158)", fontSize: 11 }}
                />
                <YAxis
                  tickLine={false}
                  axisLine={false}
                  tick={{ fill: "rgb(140,144,158)", fontSize: 11 }}
                  tickFormatter={formatK}
                />
                <RcTooltip
                  cursor={{ stroke: "rgba(107,142,127,0.3)" }}
                  contentStyle={{
                    background: "rgba(255,255,255,0.95)",
                    border: "1px solid rgba(0,0,0,0.06)",
                    borderRadius: 12,
                    backdropFilter: "blur(12px)",
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

        <Card variant="glass" padding="md">
          <CardHeader>
            <CardTitle>Occupancy</CardTitle>
          </CardHeader>
          <div className="relative mx-auto flex h-[220px] w-full items-center justify-center">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={occData}
                  dataKey="value"
                  innerRadius={62}
                  outerRadius={90}
                  paddingAngle={2}
                  stroke="none"
                >
                  {occData.map((_, i) => (
                    <Cell key={i} fill={OCCUPANCY_COLORS[i % OCCUPANCY_COLORS.length]} />
                  ))}
                </Pie>
                <RcTooltip
                  contentStyle={{
                    background: "rgba(255,255,255,0.95)",
                    border: "1px solid rgba(0,0,0,0.06)",
                    borderRadius: 12,
                    fontSize: 12,
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
              <p className="font-display text-4xl font-semibold text-ink-900">{occupancyPct}%</p>
              <p className="text-[11px] uppercase tracking-wider text-ink-500">Occupied</p>
            </div>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
            {occData.map((d, i) => (
              <div key={d.name} className="flex items-center gap-2">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ background: OCCUPANCY_COLORS[i % OCCUPANCY_COLORS.length] }}
                />
                <span className="text-ink-500">{d.name}</span>
                <span className="ml-auto font-medium text-ink-900 tabular-nums">{d.value}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Buildings gallery */}
      {buildings.length > 0 && (
        <Card variant="glass" padding="md">
          <CardHeader>
            <div>
              <CardTitle>Properties</CardTitle>
              <p className="mt-1 text-xs text-ink-500">Occupancy across your portfolio</p>
            </div>
            <Link to="/buildings" className="text-xs font-medium text-sage-600 hover:text-sage-700 dark:text-sage-400">
              Manage →
            </Link>
          </CardHeader>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {buildings.slice(0, 6).map((b) => {
              const rate = b.total > 0 ? Math.round((b.occupied / b.total) * 100) : 0;
              return (
                <Link
                  key={b.id}
                  to="/buildings"
                  className="group relative overflow-hidden rounded-lg bg-surface-raised shadow-glass transition-all hover:-translate-y-0.5 hover:shadow-float"
                >
                  <div className="relative h-32 w-full overflow-hidden">
                    <img
                      src={propertyImage(b.id ?? b.name, "md")}
                      alt={b.name}
                      loading="lazy"
                      className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-105"
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-black/10 to-transparent" />
                    <div className="absolute bottom-2 left-3 right-3 flex items-end justify-between">
                      <p className="truncate font-display text-sm font-semibold text-white">{b.name}</p>
                      <Badge tone={rate >= 80 ? "sage" : rate >= 50 ? "ochre" : "coral"} className="backdrop-blur">
                        {rate}%
                      </Badge>
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-1 p-3 text-center">
                    <div>
                      <p className="font-display text-base font-semibold text-ink-900">{b.total}</p>
                      <p className="text-[10px] uppercase tracking-wider text-ink-500">Total</p>
                    </div>
                    <div>
                      <p className="font-display text-base font-semibold text-sage-600 dark:text-sage-400">
                        {b.occupied}
                      </p>
                      <p className="text-[10px] uppercase tracking-wider text-ink-500">Occupied</p>
                    </div>
                    <div>
                      <p className="font-display text-base font-semibold text-ink-500">{b.vacant}</p>
                      <p className="text-[10px] uppercase tracking-wider text-ink-500">Vacant</p>
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>
          {buildings.length > 1 && (
            <div className="mt-4 h-[200px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={buildings}
                  margin={{ top: 10, right: 4, left: -20, bottom: 0 }}
                  barCategoryGap="22%"
                >
                  <XAxis dataKey="name" tickLine={false} axisLine={false} tick={{ fill: "rgb(140,144,158)", fontSize: 11 }} />
                  <YAxis tickLine={false} axisLine={false} tick={{ fill: "rgb(140,144,158)", fontSize: 11 }} />
                  <RcTooltip
                    cursor={{ fill: "rgba(107,142,127,0.06)" }}
                    contentStyle={{
                      background: "rgba(255,255,255,0.95)",
                      border: "1px solid rgba(0,0,0,0.06)",
                      borderRadius: 12,
                      fontSize: 12,
                    }}
                  />
                  <Bar dataKey="occupied" stackId="u" fill="rgb(216,154,58)" radius={[0, 0, 0, 0]} />
                  <Bar dataKey="vacant" stackId="u" fill="rgb(196,198,208)" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
      )}

      {/* Recent payments + alerts */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card variant="glass" padding="md">
          <CardHeader>
            <div className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-sage-600" />
              <CardTitle>Recent payments</CardTitle>
            </div>
            <Link to="/payments" className="text-xs font-medium text-sage-600 hover:text-sage-700 dark:text-sage-400">
              All →
            </Link>
          </CardHeader>
          {recent_payments.length === 0 ? (
            <EmptyState
              icon={<CreditCard className="h-5 w-5" />}
              title="No payments yet"
              description="Recorded payments will show up here."
            />
          ) : (
            <ul className="space-y-2">
              {recent_payments.slice(0, 6).map((p) => (
                <li
                  key={p.id}
                  className="flex items-center gap-3 rounded-md bg-white/40 p-2.5 transition-colors hover:bg-white/70 dark:bg-white/5 dark:hover:bg-white/10"
                >
                  <img
                    src={avatarFor(p.tenant_name)}
                    alt=""
                    aria-hidden
                    className="h-9 w-9 rounded-full"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink-900">{p.tenant_name}</p>
                    <p className="truncate text-[11px] text-ink-500">
                      {p.building_name} · {p.unit_label}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-semibold text-sage-700 tabular-nums dark:text-sage-400">
                      {KES(p.amount)}
                    </p>
                    <p className="text-[11px] text-ink-400">{p.payment_date}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card variant="glass" padding="md">
          <CardHeader>
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-coral-500" />
              <CardTitle>Attention needed</CardTitle>
            </div>
            <Badge tone={alerts.length === 0 ? "sage" : "coral"} withDot>
              {alerts.length === 0 ? "All clear" : `${alerts.length} items`}
            </Badge>
          </CardHeader>
          {alerts.length === 0 ? (
            <EmptyState
              icon={<Building2 className="h-5 w-5" />}
              title="Everything looks good"
              description="No overdue tenants or outstanding issues right now."
            />
          ) : (
            <ul className="space-y-2">
              {alerts.map((a, i) => (
                <li
                  key={i}
                  className={cn(
                    "flex items-start gap-3 rounded-md p-3",
                    a.type === "overdue"
                      ? "bg-status-unpaid/8 text-status-unpaid"
                      : "bg-status-partial/10 text-status-partial"
                  )}
                >
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <p className="text-sm">{a.message}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
