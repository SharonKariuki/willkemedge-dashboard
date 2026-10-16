import { useQuery } from "@tanstack/react-query";
import {
  BookOpen, Calculator, ChevronRight, DollarSign, FileBarChart2, Scale, Target,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";

import {
  Badge, Card, EmptyState, ErrorState, PageHeader, Skeleton,
  Table, TBody, TD, TH, THead, TR,
} from "@/components/ui";
import { fmtDate, kes, selectCls } from "@/features/reports/reportFormat";
import {
  BuildingFilter, DownloadButtons, FilterBar, LiveStatus, SearchBox, SelectFilter,
} from "@/features/reports/reportKit";
import { useReport } from "@/hooks/useReports";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { downloadFile } from "@/lib/downloadPdf";

// ─── tabs and periods ────────────────────────────────────────────────────────
const TABS = [
  { key: "balance_sheet", label: "Balance Sheet", icon: BookOpen },
  { key: "pnl",           label: "Profit & Loss", icon: FileBarChart2 },
  { key: "trial_balance", label: "Trial Balance", icon: Scale },
  { key: "ledger",        label: "General Ledger", icon: ChevronRight },
  { key: "coa",           label: "Chart of Accounts", icon: Calculator },
  { key: "petty_cash",    label: "Petty Cash", icon: DollarSign },
  { key: "budgeting",     label: "Budget vs Actual", icon: Target },
] as const;
type TabKey = (typeof TABS)[number]["key"];

const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

type Preset = "this_month" | "last_month" | "this_quarter" | "last_quarter" | "ytd" | "last_year" | "custom";
const PRESETS: [Preset, string][] = [
  ["this_month", "This month"], ["last_month", "Last month"],
  ["this_quarter", "This quarter"], ["last_quarter", "Last quarter"],
  ["ytd", "Year to date"], ["last_year", "Last year"], ["custom", "Custom dates"],
];

function presetRange(preset: Preset, today = new Date()): [string, string] {
  const y = today.getFullYear();
  const m = today.getMonth();
  const q = Math.floor(m / 3) * 3;
  switch (preset) {
    case "last_month": return [iso(new Date(y, m - 1, 1)), iso(new Date(y, m, 0))];
    case "this_quarter": return [iso(new Date(y, q, 1)), iso(new Date(y, q + 3, 0))];
    case "last_quarter": return [iso(new Date(y, q - 3, 1)), iso(new Date(y, q, 0))];
    case "ytd": return [iso(new Date(y, 0, 1)), iso(today)];
    case "last_year": return [iso(new Date(y - 1, 0, 1)), iso(new Date(y - 1, 11, 31))];
    default: return [iso(new Date(y, m, 1)), iso(new Date(y, m + 1, 0))];
  }
}

const SOURCES: [string, string][] = [
  ["", "All sources"], ["payment", "Payments"], ["expense", "Expenses"],
  ["utility_charge", "Water / utility charges"], ["manual_income", "Manual income"],
  ["tenant_credit", "Tenant credits"], ["credit_application", "Credits applied"],
  ["tenant_refund", "Refunds"], ["opening_ar,opening_deposit", "Opening balances"],
];

/** A statement as the API returns it; each view reads the fields its tab sends. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AccountingData = Record<string, any>;

interface AccountOption { code: string; name: string; is_header: boolean }

function useAccounts() {
  return useQuery<AccountOption[]>({
    queryKey: ["accounts", "all"],
    queryFn: async () => (await api.get("/accounting/accounts/")).data,
    staleTime: 10 * 60_000,
  });
}

/** Debounce a search box so typing doesn't fire a request per keystroke. */
function useDebounced<T>(value: T, ms = 350) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

// ─── shared bits ─────────────────────────────────────────────────────────────
const TONE_TEXT = {
  sage: "text-sage-700 dark:text-sage-400",
  coral: "text-status-unpaid",
  peri: "text-peri-600 dark:text-peri-400",
  ochre: "text-ochre-600",
  ink: "text-ink-900",
} as const;

function StatTile({ label, value, tone = "ink" }: { label: string; value: string; tone?: keyof typeof TONE_TEXT }) {
  return (
    <div className="neu-sm min-w-0 p-4">
      <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">{label}</p>
      <p className={cn("mt-1 truncate font-display text-xl font-semibold tabular-nums", TONE_TEXT[tone])}>{value}</p>
    </div>
  );
}

const money = (n: number | null | undefined, blankZero = false) =>
  n === null || n === undefined || (blankZero && Number(n) === 0) ? "—" : kes(n);

function Num({ children, strong, className }: { children: ReactNode; strong?: boolean; className?: string }) {
  return <TD className={cn("text-right tabular-nums", strong && "font-semibold text-ink-900", className)}>{children}</TD>;
}

function BalancedBadge({ ok, okText = "Balanced", badText = "Out of balance" }: { ok: boolean; okText?: string; badText?: string }) {
  return <Badge tone={ok ? "sage" : "coral"} withDot>{ok ? okText : badText}</Badge>;
}

// ─── Balance sheet ───────────────────────────────────────────────────────────
interface LineItem { code: string; name: string; amount: number }
interface Group { code: string; name: string; accounts: LineItem[]; total: number }

function StatementSection({ title, groups, total }: { title: string; groups: Group[]; total: number }) {
  return (
    <section className="min-w-0">
      <Table minWidth={360}>
        <THead><TR><TH>{title}</TH><TH className="text-right">KES</TH></TR></THead>
        <TBody>
          {groups.length === 0 && <TR><TD colSpan={2} className="text-ink-400">Nothing recorded.</TD></TR>}
          {groups.map((g) => (
            <GroupRows key={`${g.code}-${g.name}`} group={g} showHeading={groups.length > 1 || g.name !== title} />
          ))}
          <TR className="border-t-2 border-ink-300">
            <TD className="font-semibold text-ink-900">Total {title.toLowerCase()}</TD>
            <Num strong>{kes(total)}</Num>
          </TR>
        </TBody>
      </Table>
    </section>
  );
}

function GroupRows({ group, showHeading }: { group: Group; showHeading: boolean }) {
  return (
    <>
      {showHeading && (
        <TR className="bg-canvas-alt hover:bg-canvas-alt">
          <TD colSpan={2} className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-600">{group.name}</TD>
        </TR>
      )}
      {group.accounts.map((a) => (
        <TR key={`${a.code}-${a.name}`}>
          <TD><span className="mr-2 font-mono text-xs text-ink-500">{a.code}</span>{a.name}</TD>
          <Num>{kes(a.amount)}</Num>
        </TR>
      ))}
    </>
  );
}

function BalanceSheetView({ data }: { data: AccountingData }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <BalancedBadge ok={data.balanced} okText="Assets = liabilities + equity" badText={`Out of balance by ${kes(data.difference)}`} />
        <span className="text-xs text-ink-500">As at {fmtDate(data.end)}</span>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile label="Total assets" value={kes(data.total_assets)} tone="sage" />
        <StatTile label="Total liabilities" value={kes(data.total_liabilities)} tone="coral" />
        <StatTile label="Total equity" value={kes(data.total_equity)} tone="peri" />
      </div>
      <div className="grid min-w-0 gap-5 lg:grid-cols-2">
        <StatementSection title="Assets" groups={data.assets} total={data.total_assets} />
        <div className="min-w-0 space-y-5">
          <StatementSection title="Liabilities" groups={data.liabilities} total={data.total_liabilities} />
          <StatementSection title="Equity" groups={data.equity} total={data.total_equity} />
          <div className="neu-sm flex items-center justify-between p-4">
            <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-500">Liabilities + equity</span>
            <span className="font-display text-lg font-semibold tabular-nums">{kes(data.total_liabilities_and_equity)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Profit and loss ─────────────────────────────────────────────────────────
function PnLView({ data }: { data: AccountingData }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile label="Total income" value={kes(data.total_income)} tone="sage" />
        <StatTile label="Total expenses" value={kes(data.total_expenses)} tone="coral" />
        <StatTile label={data.net_profit >= 0 ? "Net profit" : "Net loss"} value={kes(data.net_profit)}
          tone={data.net_profit >= 0 ? "sage" : "coral"} />
      </div>
      <div className="grid min-w-0 gap-5 lg:grid-cols-2">
        <StatementSection title="Income" groups={data.income} total={data.total_income} />
        <StatementSection title="Expenses" groups={data.expenses} total={data.total_expenses} />
      </div>
      <p className="text-xs text-ink-500">
        From the general ledger by transaction date: rent when received, water when billed, VAT excluded.
      </p>
    </div>
  );
}

// ─── Trial balance ───────────────────────────────────────────────────────────
interface TbRow { code: string; name: string; type: string; debit: number; credit: number }

function TrialBalanceView({ data }: { data: AccountingData }) {
  const rows: TbRow[] = data.rows ?? [];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <BalancedBadge ok={data.balanced} badText="Debits and credits differ" />
        <span className="text-xs text-ink-500">
          {data.mode === "movements"
            ? `Debits and credits posted ${fmtDate(data.start)} – ${fmtDate(data.end)}`
            : `Closing balances at ${fmtDate(data.end)} · income and expenses for the year to date`}
        </span>
      </div>
      <Table minWidth={640}>
        <THead><TR><TH>Code</TH><TH>Account</TH><TH>Type</TH><TH className="text-right">Debit</TH><TH className="text-right">Credit</TH></TR></THead>
        <TBody>
          {rows.length === 0 && <TR><TD colSpan={5} className="text-ink-400">Nothing posted.</TD></TR>}
          {rows.map((r) => (
            <TR key={`${r.code}-${r.name}`}>
              <TD className="font-mono text-xs text-ink-500">{r.code}</TD>
              <TD>{r.name}</TD>
              <TD><Badge tone="neutral">{r.type}</Badge></TD>
              <Num>{money(r.debit, true)}</Num>
              <Num>{money(r.credit, true)}</Num>
            </TR>
          ))}
          <TR className="border-t-2 border-ink-300">
            <TD colSpan={3} className="font-semibold text-ink-900">Total</TD>
            <Num strong>{kes(data.total_debit)}</Num>
            <Num strong>{kes(data.total_credit)}</Num>
          </TR>
        </TBody>
      </Table>
    </div>
  );
}

// ─── General ledger ──────────────────────────────────────────────────────────
/** Ledger tables are long and wide: tighter cells keep Debit, Credit and Balance in view. */
const COMPACT = "text-sm [&_td]:px-3 [&_td]:py-2 [&_th]:px-3 [&_th]:py-2.5";
interface GlLine {
  date: string; entry_id: number; reference: string; description: string; detail: string; source: string;
  kind: string; building: string; debit: number; credit: number; balance: number;
}
interface GlAccount {
  code: string; name: string; type: string; normal_side: string;
  opening: number; debit: number; credit: number; closing: number; lines: GlLine[];
}

function LedgerAccountTable({ acct }: { acct: GlAccount }) {
  return (
    <div className="min-w-0 space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-display text-sm font-semibold text-ink-900">
          <span className="mr-2 font-mono text-xs text-ink-500">{acct.code}</span>{acct.name}
          <span className="ml-2 text-xs font-normal text-ink-500">{acct.type} · {acct.normal_side} balance</span>
        </p>
        <p className="text-xs text-ink-500">
          Opening <span className="font-medium text-ink-900">{kes(acct.opening)}</span> ·
          Closing <span className="font-medium text-ink-900">{kes(acct.closing)}</span>
        </p>
      </div>
      <Table minWidth={980} className={COMPACT}>
        <THead><TR>
          <TH>Date</TH><TH>Reference</TH><TH>Description</TH><TH>Source</TH>
          <TH className="text-right">Debit</TH><TH className="text-right">Credit</TH><TH className="text-right">Balance</TH>
        </TR></THead>
        <TBody>
          <TR className="bg-canvas-alt hover:bg-canvas-alt">
            <TD colSpan={6} className="italic text-ink-500">Opening balance</TD>
            <Num>{kes(acct.opening)}</Num>
          </TR>
          {acct.lines.map((ln, i) => (
            <TR key={`${ln.entry_id}-${i}`}>
              <TD className="whitespace-nowrap text-ink-500">{fmtDate(ln.date)}</TD>
              <TD className="max-w-[11rem] truncate font-mono text-xs" title={ln.reference}>{ln.reference || "—"}</TD>
              <TD className="min-w-[16rem] whitespace-normal">
                {ln.description}
                {ln.detail && <span className="block text-xs text-ink-500">{ln.detail}</span>}
                {ln.kind === "reversal" && <Badge tone="coral" className="ml-2">Reversal</Badge>}
              </TD>
              <TD className="max-w-[10rem] whitespace-normal text-xs text-ink-500">
                {ln.source}
                {ln.building && <span className="block truncate" title={ln.building}>{ln.building}</span>}
              </TD>
              <Num>{money(ln.debit, true)}</Num>
              <Num>{money(ln.credit, true)}</Num>
              <Num className={cn(ln.balance < 0 && "text-status-unpaid")}>{kes(ln.balance)}</Num>
            </TR>
          ))}
          <TR className="border-t-2 border-ink-300">
            <TD colSpan={4} className="font-semibold text-ink-900">Closing balance</TD>
            <Num strong>{kes(acct.debit)}</Num>
            <Num strong>{kes(acct.credit)}</Num>
            <Num strong>{kes(acct.closing)}</Num>
          </TR>
        </TBody>
      </Table>
    </div>
  );
}

function LedgerView({ data }: { data: AccountingData }) {
  const accounts: GlAccount[] = data.accounts ?? [];
  if (accounts.length === 0)
    return <EmptyState title="No ledger lines" description="Nothing was posted in this period for these filters." />;
  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile label="Accounts" value={String(accounts.length)} />
        <StatTile label="Debits shown" value={kes(data.total_debit)} />
        <StatTile label="Credits shown" value={kes(data.total_credit)} />
      </div>
      {data.filtered && (
        <p className="text-xs text-ink-500">Filtered view — running balances still count every line in the period.</p>
      )}
      {accounts.map((a) => <LedgerAccountTable key={a.code} acct={a} />)}
    </div>
  );
}

interface JournalEntryRow {
  id: number; date: string; reference: string; memo: string; source: string; kind: string; building: string;
  amount: number;
  lines: { account_code: string; account_name: string; description: string; debit: number; credit: number }[];
}

function JournalView({ data }: { data: AccountingData }) {
  const entries: JournalEntryRow[] = data.entries ?? [];
  if (entries.length === 0)
    return <EmptyState title="No journal entries" description="Nothing was posted in this period for these filters." />;
  return (
    <div className="space-y-3">
      <p className="text-xs text-ink-500">{entries.length} entries · {kes(data.total)} posted</p>
      <Table minWidth={900} className={COMPACT}>
        <THead><TR>
          <TH>Date</TH><TH>Entry</TH><TH>Account</TH><TH>Description</TH>
          <TH className="text-right">Debit</TH><TH className="text-right">Credit</TH>
        </TR></THead>
        <TBody>
          {entries.map((e) => (
            <JournalEntryRows key={e.id} entry={e} />
          ))}
        </TBody>
      </Table>
    </div>
  );
}

function JournalEntryRows({ entry }: { entry: JournalEntryRow }) {
  return (
    <>
      <TR className="bg-canvas-alt hover:bg-canvas-alt">
        <TD className="whitespace-nowrap font-medium text-ink-900">{fmtDate(entry.date)}</TD>
        <TD className="font-mono text-xs">#{entry.id}{entry.reference ? ` · ${entry.reference}` : ""}</TD>
        <TD colSpan={4} className="max-w-xl whitespace-normal text-ink-700">
          {entry.memo} <span className="text-xs text-ink-500">({entry.source}{entry.building ? ` · ${entry.building}` : ""})</span>
          {entry.kind === "reversal" && <Badge tone="coral" className="ml-2">Reversal</Badge>}
        </TD>
      </TR>
      {entry.lines.map((ln, i) => (
        <TR key={i}>
          <TD /><TD />
          <TD className={cn(ln.credit > 0 && "pl-10")}>
            <span className="mr-2 font-mono text-xs text-ink-500">{ln.account_code}</span>{ln.account_name}
          </TD>
          <TD className="max-w-sm whitespace-normal text-xs text-ink-500">{ln.description}</TD>
          <Num>{money(ln.debit, true)}</Num>
          <Num>{money(ln.credit, true)}</Num>
        </TR>
      ))}
    </>
  );
}

// ─── Chart of accounts ───────────────────────────────────────────────────────
interface CoaRow {
  code: string; name: string; type: string; is_header: boolean;
  opening?: number; debit?: number; credit?: number; closing: number;
}

function CoAView({ data, onOpenLedger }: { data: AccountingData; onOpenLedger: (code: string) => void }) {
  const rows: CoaRow[] = data.accounts ?? [];
  return (
    <Table minWidth={880}>
      <THead><TR>
        <TH>Code</TH><TH>Account</TH><TH>Type</TH>
        <TH className="text-right">Opening</TH><TH className="text-right">Debits</TH>
        <TH className="text-right">Credits</TH><TH className="text-right">Closing</TH>
      </TR></THead>
      <TBody>
        {rows.map((a) => a.is_header ? (
          <TR key={a.code} className="bg-canvas-alt hover:bg-canvas-alt">
            <TD className="font-mono text-xs font-semibold text-ink-700">{a.code}</TD>
            <TD colSpan={5} className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-600">{a.name}</TD>
            <Num strong>{kes(a.closing)}</Num>
          </TR>
        ) : (
          <TR key={a.code}>
            <TD className="pl-6 font-mono text-xs text-ink-500">{a.code}</TD>
            <TD>
              <button type="button" onClick={() => onOpenLedger(a.code)}
                className="text-left font-medium text-ink-900 hover:underline" title="Open in the general ledger">
                {a.name}
              </button>
            </TD>
            <TD><Badge tone="neutral">{a.type}</Badge></TD>
            <Num>{money(a.opening, true)}</Num>
            <Num>{money(a.debit, true)}</Num>
            <Num>{money(a.credit, true)}</Num>
            <Num strong>{money(a.closing, true)}</Num>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

// ─── Petty cash ──────────────────────────────────────────────────────────────
function PettyCashView({ data }: { data: AccountingData }) {
  const lines: GlLine[] = data.entries ?? [];
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Opening balance" value={kes(data.opening)} />
        <StatTile label="Cash in" value={kes(data.cash_in)} tone="sage" />
        <StatTile label="Cash out" value={kes(data.cash_out)} tone="coral" />
        <StatTile label="Closing balance" value={kes(data.closing_balance)} tone="ochre" />
      </div>
      <Table minWidth={720} className={COMPACT}>
        <THead><TR>
          <TH>Date</TH><TH>Description</TH><TH className="text-right">Cash in</TH>
          <TH className="text-right">Cash out</TH><TH className="text-right">Balance</TH>
        </TR></THead>
        <TBody>
          {lines.length === 0 ? (
            <TR><TD colSpan={5} className="text-center text-ink-400">No petty cash movements in this period.</TD></TR>
          ) : lines.map((ln, i) => (
            <TR key={i}>
              <TD className="whitespace-nowrap text-ink-500">{fmtDate(ln.date)}</TD>
              <TD className="max-w-md whitespace-normal">{ln.description}</TD>
              <Num>{money(ln.debit, true)}</Num>
              <Num className="text-status-unpaid">{money(ln.credit, true)}</Num>
              <Num strong>{kes(ln.balance)}</Num>
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}

// ─── Budget ──────────────────────────────────────────────────────────────────
function BudgetingView({ data }: { data: AccountingData }) {
  const rows: { category: string; budgeted: number; actual: number; variance: number }[] = data.rows ?? [];
  const v = Number(data.total_variance ?? 0);
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile label="Budgeted" value={kes(data.total_budgeted)} tone="peri" />
        <StatTile label="Actual" value={kes(data.total_actual)} tone="sage" />
        <StatTile label="Variance" value={`${v >= 0 ? "+" : "−"}${kes(Math.abs(v))}`} tone={v >= 0 ? "sage" : "coral"} />
      </div>
      {data.basis === "rent_roll" && (
        <p className="text-xs text-ink-500">
          No budget has been set for this period, so rent received is compared with the monthly rent of current tenants.
        </p>
      )}
      <Table minWidth={620}>
        <THead><TR><TH>Line</TH><TH className="text-right">Budgeted</TH><TH className="text-right">Actual</TH><TH className="text-right">Variance</TH></TR></THead>
        <TBody>
          {rows.map((r) => (
            <TR key={r.category}>
              <TD className="font-medium">{r.category}</TD>
              <Num>{kes(r.budgeted)}</Num>
              <Num>{kes(r.actual)}</Num>
              <Num className={cn("font-semibold", r.variance >= 0 ? "text-sage-700" : "text-status-unpaid")}>
                {r.variance >= 0 ? "+" : ""}{kes(r.variance)}
              </Num>
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}

// ─── Suite ───────────────────────────────────────────────────────────────────
/**
 * The accounting suite body (tabs, period and filters, statements, downloads)
 * without a page header. Rendered standalone on /accounting and embedded as a
 * tab on the Expenses page.
 */
export function AccountingSuite() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("acct");
  const tab: TabKey = TABS.some((t) => t.key === requested) ? (requested as TabKey) : "balance_sheet";
  const setTab = (key: TabKey) => {
    const next = new URLSearchParams(params);
    next.set("acct", key);
    setParams(next, { replace: true });
  };

  const [preset, setPreset] = useState<Preset>("this_month");
  const [[start, end], setRange] = useState<[string, string]>(() => presetRange("this_month"));
  const [building, setBuilding] = useState<number | null>(null);
  const [view, setView] = useState<"account" | "journal">("account");
  const [account, setAccount] = useState("");
  const [source, setSource] = useState("");
  const [search, setSearch] = useState("");
  const [mode, setMode] = useState<"balances" | "movements">("balances");
  const q = useDebounced(search);
  const { data: accounts } = useAccounts();

  const choosePreset = (p: Preset) => {
    setPreset(p);
    if (p !== "custom") setRange(presetRange(p));
  };
  const setStart = (v: string) => { setPreset("custom"); setRange([v, end]); };
  const setEnd = (v: string) => { setPreset("custom"); setRange([start, v]); };

  const query = useMemo(() => {
    const base: Record<string, string | number | null> = { tab, start, end, building };
    if (tab === "ledger") Object.assign(base, { view, account: view === "account" ? account : "", source, q });
    if (tab === "trial_balance") base.mode = mode;
    return base;
  }, [tab, start, end, building, view, account, source, q, mode]);

  const validRange = Boolean(start && end && start <= end);
  const result = useReport<AccountingData>("/reports/accounting/", query, validRange);
  const { data, isLoading, isError, error } = result;
  // While the next tab or view loads, never show the last one in the wrong layout.
  const fits = data && data.tab === tab && (tab !== "ledger" || data.view === view);

  const openLedger = (code: string) => {
    setAccount(code);
    setView("account");
    setTab("ledger");
  };

  const asAt = tab === "balance_sheet";
  const errorText =
    (error as { response?: { data?: Record<string, string[] | string> } })?.response?.data;

  return (
    <Card variant="glass" padding="md" className="min-w-0">
      <div className="space-y-4">
        <div className="glass -mx-1 flex gap-1 overflow-x-auto rounded-xl p-1" role="tablist">
          {TABS.map((t) => {
            const Icon = t.icon;
            const active = tab === t.key;
            return (
              <button key={t.key} role="tab" aria-selected={active} onClick={() => setTab(t.key)}
                className={cn(
                  "flex items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-2 text-xs font-medium transition-all",
                  active ? "bg-ink-900 text-canvas shadow-float" : "text-ink-600 hover:text-ink-900",
                )}>
                <Icon className="h-3.5 w-3.5" />{t.label}
              </button>
            );
          })}
        </div>

        <div className="flex flex-wrap items-start justify-between gap-3">
          <FilterBar>
            <SelectFilter label="Period" value={preset} onChange={choosePreset} options={PRESETS} />
            <div className="flex flex-wrap items-center gap-1 text-xs text-ink-500">
              {!asAt && <>
                <span>From</span>
                <input type="date" aria-label="Start date" value={start} max={end}
                  onChange={(e) => setStart(e.target.value)} className={selectCls} />
              </>}
              <span>{asAt ? "As at" : "to"}</span>
              <input type="date" aria-label="End date" value={end} min={asAt ? undefined : start}
                onChange={(e) => setEnd(e.target.value)} className={selectCls} />
            </div>
            <BuildingFilter value={building} onChange={setBuilding} />
            <LiveStatus query={result} />
          </FilterBar>
          <DownloadButtons
            disabled={!validRange || !fits}
            onDownload={(format) => downloadFile("/reports/accounting/", {
              params: Object.fromEntries(
                (Object.entries({ ...query, export: format }) as [string, unknown][])
                  .filter(([, v]) => v !== null && v !== ""),
              ),
              fallback: `${tab}-${start}-${end}`,
            })}
          />
        </div>

        {tab === "ledger" && (
          <FilterBar>
            <div className="glass flex overflow-hidden rounded-md">
              {(["account", "journal"] as const).map((v) => (
                <button key={v} onClick={() => setView(v)}
                  className={cn("px-3 py-2 text-xs font-medium", view === v ? "bg-ink-900 text-canvas" : "text-ink-600")}>
                  {v === "account" ? "By account" : "Journal"}
                </button>
              ))}
            </div>
            {view === "account" && (
              <select aria-label="Ledger account" value={account} onChange={(e) => setAccount(e.target.value)} className={selectCls}>
                <option value="">All accounts</option>
                {(accounts ?? []).filter((a) => !a.is_header).map((a) => (
                  <option key={a.code} value={a.code}>{a.code} — {a.name}</option>
                ))}
              </select>
            )}
            <SelectFilter label="Source" value={source} onChange={setSource} options={SOURCES} />
            <SearchBox value={search} onChange={setSearch} placeholder="Search memo or reference…" />
          </FilterBar>
        )}
        {tab === "trial_balance" && (
          <FilterBar>
            <div className="glass flex overflow-hidden rounded-md">
              {([["balances", "Closing balances"], ["movements", "Movements in period"]] as const).map(([v, label]) => (
                <button key={v} onClick={() => setMode(v)}
                  className={cn("px-3 py-2 text-xs font-medium", mode === v ? "bg-ink-900 text-canvas" : "text-ink-600")}>
                  {label}
                </button>
              ))}
            </div>
          </FilterBar>
        )}

        {!validRange ? (
          <EmptyState title="Check the dates" description="The start date must be on or before the end date." />
        ) : isError && !fits ? (
          <ErrorState
            title="Accounting data could not be loaded."
            description={errorText ? String(Object.values(errorText)[0]) : "This is usually temporary — try again in a moment."}
            onRetry={() => void result.refetch()}
          />
        ) : isLoading || !fits ? (
          <div className="space-y-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-12" />)}</div>
        ) : (
          <div key={tab} className="animate-fade-up">
            {tab === "balance_sheet" && <BalanceSheetView data={data} />}
            {tab === "pnl" && <PnLView data={data} />}
            {tab === "trial_balance" && <TrialBalanceView data={data} />}
            {tab === "ledger" && (view === "journal" ? <JournalView data={data} /> : <LedgerView data={data} />)}
            {tab === "coa" && <CoAView data={data} onOpenLedger={openLedger} />}
            {tab === "petty_cash" && <PettyCashView data={data} />}
            {tab === "budgeting" && <BudgetingView data={data} />}
          </div>
        )}
      </div>
    </Card>
  );
}

export default function AccountingPage() {
  return (
    <div className="min-w-0 space-y-6">
      <PageHeader
        eyebrow="Finance"
        title="Accounting Suite"
        description="Balance Sheet, P&L, Trial Balance, General Ledger and more — live from the general ledger, for any period, downloadable as CSV, Excel or PDF."
      />
      <AccountingSuite />
    </div>
  );
}
