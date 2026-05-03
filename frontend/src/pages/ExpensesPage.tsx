import { zodResolver } from "@hookform/resolvers/zod";
import {
  BookOpen, Calculator, ChevronDown, ChevronRight,
  DollarSign, FileBarChart2, PlusCircle, Tag, Trash2,
} from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { z } from "zod";

import {
  Badge, Button, Card, EmptyState,
  PageHeader, Skeleton, Table, TBody, TD, TH, THead, TR,
} from "@/components/ui";
import { useBuildings } from "@/hooks/useBuildings";
import {
  useCreateExpense, useCreateExpenseCategory,
  useDeleteExpense, useExpenseCategories, useExpenses,
} from "@/hooks/useExpenses";
import { useReportsAccounting } from "@/hooks/useReports";
import { cn } from "@/lib/cn";

const expenseSchema = z.object({
  date: z.string().min(1, "Date is required"),
  building: z.string().optional(),
  category: z.coerce.number().min(1, "Category is required"),
  amount: z.string().min(1, "Amount is required"),
  description: z.string().min(2, "Description is required"),
  reference: z.string().optional(),
  period_month: z.coerce.number().min(1).max(12),
  period_year: z.coerce.number().min(2000),
  notes: z.string().optional(),
});
type ExpenseFormData = z.infer<typeof expenseSchema>;

const categorySchema = z.object({
  name: z.string().min(1, "Category name is required"),
  description: z.string().optional(),
});
type CategoryFormData = z.infer<typeof categorySchema>;

const inputCls =
  "w-full rounded-md bg-surface-raised hairline px-3 py-2.5 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-sage-500/40";
const selectCls =
  "glass rounded-md px-3 py-2 text-sm text-ink-900 focus:outline-none";

function Field({ label, error, children, className }: {
  label: string; error?: string; children: React.ReactNode; className?: string;
}) {
  return (
    <div className={className}>
      <label className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
        {label}
      </label>
      {children}
      {error && <p className="mt-1 text-[11px] text-status-unpaid">{error}</p>}
    </div>
  );
}

// ─── Accounting tab components ───────────────────────────────────────────────
function AccountingPanel() {
  const now = new Date();
  const [tab, setTab] = useState<"balance_sheet"|"pnl"|"ledger"|"coa"|"petty_cash"|"budgeting">("balance_sheet");
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());
  const { data, isLoading } = useReportsAccounting(tab, month, year);

  const TABS = [
    { key: "balance_sheet",  label: "Balance Sheet", icon: BookOpen },
    { key: "pnl",            label: "Profit & Loss", icon: FileBarChart2 },
    { key: "ledger",         label: "General Ledger", icon: ChevronRight },
    { key: "coa",            label: "Chart of Accounts", icon: Calculator },
    { key: "petty_cash",     label: "Petty Cash", icon: DollarSign },
    { key: "budgeting",      label: "Income & Budgeting", icon: FileBarChart2 },
  ] as const;

  return (
    <div className="space-y-4">
      {/* Sub-tabs */}
      <div className="glass -mx-1 flex gap-1 overflow-x-auto rounded-xl p-1">
        {TABS.map((t) => {
          const Icon = t.icon;
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key as typeof tab)}
              className={cn(
                "flex items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-2 text-xs font-medium transition-all",
                active ? "bg-ink-900 text-canvas shadow-float" : "text-ink-600 hover:text-ink-900",
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {t.label}
            </button>
          );
        })}
      </div>

      {/* Period filter */}
      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-[11px] font-medium uppercase tracking-wider text-ink-500">Period:</span>
        <select value={month} onChange={(e) => setMonth(Number(e.target.value))} className={selectCls}>
          {Array.from({ length: 12 }, (_, i) => (
            <option key={i + 1} value={i + 1}>
              {new Date(2000, i).toLocaleString("default", { month: "long" })}
            </option>
          ))}
        </select>
        <input
          type="number" min={2020} max={2100} value={year}
          onChange={(e) => setYear(Number(e.target.value))}
          className={selectCls + " w-24"}
        />
      </div>

      {isLoading ? (
        <div className="space-y-2">{Array.from({length:4}).map((_,i) => <Skeleton key={i} className="h-12" />)}</div>
      ) : !data ? (
        <EmptyState title="No data" description="No accounting data for this period." />
      ) : (
        <AccountingContent tab={tab} data={data} />
      )}
    </div>
  );
}

function AccountingContent({ tab, data }: { tab: string; data: Record<string, unknown> }) {
  if (tab === "balance_sheet") return <BalanceSheetView data={data} />;
  if (tab === "pnl")           return <PnLView data={data} />;
  if (tab === "ledger")        return <LedgerView data={data} />;
  if (tab === "coa")           return <CoAView data={data} />;
  if (tab === "petty_cash")    return <PettyCashView data={data} />;
  if (tab === "budgeting")     return <BudgetingView data={data} />;
  return null;
}

function KV({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className={cn("flex justify-between gap-4 rounded-md px-3 py-2 text-sm",
      highlight ? "bg-sage-500/8 font-semibold" : "bg-white/40 dark:bg-white/5")}>
      <span className="text-ink-500">{label}</span>
      <span className={cn("tabular-nums", highlight ? "text-sage-700" : "text-ink-900")}>{value}</span>
    </div>
  );
}

function BalanceSheetView({ data }: { data: Record<string, unknown> }) {
  const assets = data.assets as Record<string, number> ?? {};
  const liabilities = data.liabilities as Record<string, number> ?? {};
  const equity = data.equity as number ?? 0;
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="space-y-2">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-500">Assets</p>
        {Object.entries(assets).map(([k, v]) => (
          <KV key={k} label={k} value={`KES ${Number(v).toLocaleString()}`} />
        ))}
        <KV label="TOTAL ASSETS" value={`KES ${Object.values(assets).reduce((a, b) => a + b, 0).toLocaleString()}`} highlight />
      </div>
      <div className="space-y-2">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-500">Liabilities & Equity</p>
        {Object.entries(liabilities).map(([k, v]) => (
          <KV key={k} label={k} value={`KES ${Number(v).toLocaleString()}`} />
        ))}
        <KV label="Owner Equity" value={`KES ${Number(equity).toLocaleString()}`} />
        <KV label="TOTAL LIABILITIES + EQUITY"
          value={`KES ${(Object.values(liabilities).reduce((a, b) => a + b, 0) + equity).toLocaleString()}`}
          highlight />
      </div>
    </div>
  );
}

function PnLView({ data }: { data: Record<string, unknown> }) {
  const income = Number(data.income ?? 0);
  const expenses = Number(data.total_expenses ?? 0);
  const net = Number(data.net_profit ?? 0);
  const breakdown = (data.expense_breakdown as { category: string; amount: number }[]) ?? [];
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-3">
        {[
          { label: "Total Income", val: income, tone: "sage" },
          { label: "Total Expenses", val: expenses, tone: "coral" },
          { label: "Net Profit", val: net, tone: net >= 0 ? "sage" : "coral" },
        ].map((s) => (
          <div key={s.label} className={cn("rounded-lg p-4 text-center",
            s.tone === "sage" ? "bg-sage-500/8" : "bg-status-unpaid/8")}>
            <p className="text-[11px] uppercase tracking-wider text-ink-500">{s.label}</p>
            <p className={cn("mt-1 font-display text-xl font-semibold",
              s.tone === "sage" ? "text-sage-700" : "text-status-unpaid")}>
              KES {Number(s.val).toLocaleString()}
            </p>
          </div>
        ))}
      </div>
      {breakdown.length > 0 && (
        <Table>
          <THead><TR><TH>Expense Category</TH><TH className="text-right">Amount (KES)</TH></TR></THead>
          <TBody>
            {breakdown.map((r) => (
              <TR key={r.category}><TD>{r.category}</TD><TD className="text-right tabular-nums">{Number(r.amount).toLocaleString()}</TD></TR>
            ))}
          </TBody>
        </Table>
      )}
    </div>
  );
}

function LedgerView({ data }: { data: Record<string, unknown> }) {
  const entries = (data.entries as { date: string; description: string; debit: number; credit: number; balance: number }[]) ?? [];
  return (
    <Table>
      <THead><TR><TH>Date</TH><TH>Description</TH><TH className="text-right">Debit</TH><TH className="text-right">Credit</TH><TH className="text-right">Balance</TH></TR></THead>
      <TBody>
        {entries.length === 0 ? (
          <TR><TD colSpan={5} className="text-center text-ink-400">No ledger entries for this period</TD></TR>
        ) : entries.map((e, i) => (
          <TR key={i}>
            <TD className="text-ink-500 whitespace-nowrap">{e.date}</TD>
            <TD>{e.description}</TD>
            <TD className="text-right tabular-nums">{e.debit > 0 ? `KES ${Number(e.debit).toLocaleString()}` : "—"}</TD>
            <TD className="text-right tabular-nums">{e.credit > 0 ? `KES ${Number(e.credit).toLocaleString()}` : "—"}</TD>
            <TD className={cn("text-right tabular-nums font-semibold", e.balance >= 0 ? "text-sage-700" : "text-status-unpaid")}>
              KES {Number(e.balance).toLocaleString()}
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

function CoAView({ data }: { data: Record<string, unknown> }) {
  const accounts = (data.accounts as { code: string; name: string; type: string; balance: number }[]) ?? [];
  return (
    <Table>
      <THead><TR><TH>Code</TH><TH>Account Name</TH><TH>Type</TH><TH className="text-right">Balance (KES)</TH></TR></THead>
      <TBody>
        {accounts.map((a) => (
          <TR key={a.code}>
            <TD className="font-mono text-xs">{a.code}</TD>
            <TD className="font-medium">{a.name}</TD>
            <TD><Badge tone="peri">{a.type}</Badge></TD>
            <TD className="text-right tabular-nums">{Number(a.balance).toLocaleString()}</TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

function PettyCashView({ data }: { data: Record<string, unknown> }) {
  const entries = (data.entries as { date: string; description: string; amount: number; running_balance: number }[]) ?? [];
  const balance = Number(data.closing_balance ?? 0);
  return (
    <div className="space-y-3">
      <div className="rounded-lg bg-ochre-500/8 p-4 flex items-center justify-between">
        <p className="text-sm font-medium text-ink-700">Petty Cash Balance</p>
        <p className="font-display text-2xl font-semibold text-ochre-700">KES {balance.toLocaleString()}</p>
      </div>
      <Table>
        <THead><TR><TH>Date</TH><TH>Description</TH><TH className="text-right">Cash Out (KES)</TH><TH className="text-right">Running Balance</TH></TR></THead>
        <TBody>
          {entries.length === 0 ? (
            <TR><TD colSpan={4} className="text-center text-ink-400">No petty cash transactions this period</TD></TR>
          ) : entries.map((e, i) => (
            <TR key={i}>
              <TD className="whitespace-nowrap text-ink-500">{e.date}</TD>
              <TD>{e.description}</TD>
              <TD className="text-right tabular-nums text-status-unpaid">{Number(e.amount).toLocaleString()}</TD>
              <TD className="text-right tabular-nums font-medium">{Number(e.running_balance).toLocaleString()}</TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}

function BudgetingView({ data }: { data: Record<string, unknown> }) {
  const rows = (data.rows as { category: string; budgeted: number; actual: number; variance: number }[]) ?? [];
  const totalBudgeted = Number(data.total_budgeted ?? 0);
  const totalActual = Number(data.total_actual ?? 0);
  const totalVariance = Number(data.total_variance ?? 0);
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg bg-peri-500/8 p-4 text-center">
          <p className="text-[11px] uppercase tracking-wider text-ink-500">Budgeted Income</p>
          <p className="mt-1 font-display text-xl font-semibold text-peri-700">KES {totalBudgeted.toLocaleString()}</p>
        </div>
        <div className="rounded-lg bg-sage-500/8 p-4 text-center">
          <p className="text-[11px] uppercase tracking-wider text-ink-500">Actual Income</p>
          <p className="mt-1 font-display text-xl font-semibold text-sage-700">KES {totalActual.toLocaleString()}</p>
        </div>
        <div className={cn("rounded-lg p-4 text-center", totalVariance >= 0 ? "bg-sage-500/8" : "bg-status-unpaid/8")}>
          <p className="text-[11px] uppercase tracking-wider text-ink-500">Variance</p>
          <p className={cn("mt-1 font-display text-xl font-semibold", totalVariance >= 0 ? "text-sage-700" : "text-status-unpaid")}>
            {totalVariance >= 0 ? "+" : ""}KES {totalVariance.toLocaleString()}
          </p>
        </div>
      </div>
      <Table>
        <THead><TR><TH>Building</TH><TH className="text-right">Budgeted</TH><TH className="text-right">Actual</TH><TH className="text-right">Variance</TH></TR></THead>
        <TBody>
          {rows.map((r) => (
            <TR key={r.category}>
              <TD className="font-medium">{r.category}</TD>
              <TD className="text-right tabular-nums">{Number(r.budgeted).toLocaleString()}</TD>
              <TD className="text-right tabular-nums">{Number(r.actual).toLocaleString()}</TD>
              <TD className={cn("text-right tabular-nums font-semibold",
                r.variance >= 0 ? "text-sage-700" : "text-status-unpaid")}>
                {r.variance >= 0 ? "+" : ""}{Number(r.variance).toLocaleString()}
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────
const MAIN_TABS = [
  { key: "expenses",   label: "Expenses Log" },
  { key: "accounting", label: "Accounting" },
] as const;

type MainTab = (typeof MAIN_TABS)[number]["key"];

export default function ExpensesPage() {
  const now = new Date();
  const [mainTab, setMainTab] = useState<MainTab>("expenses");
  const [filterMonth, setFilterMonth] = useState(now.getMonth() + 1);
  const [filterYear, setFilterYear] = useState(now.getFullYear());
  const [filterBuilding, setFilterBuilding] = useState<"" | "none" | string>("");
  const [showForm, setShowForm] = useState(false);
  const [showCategoryForm, setShowCategoryForm] = useState(false);

  const buildingParam: number | "none" | null =
    filterBuilding === "" ? null : filterBuilding === "none" ? "none" : Number(filterBuilding);

  const { data: expenses, isLoading } = useExpenses(filterMonth, filterYear, buildingParam);
  const { data: categories } = useExpenseCategories();
  const { data: buildings } = useBuildings();
  const createExpense = useCreateExpense();
  const deleteExpense = useDeleteExpense();
  const createCategory = useCreateExpenseCategory();

  const form = useForm<ExpenseFormData>({
    resolver: zodResolver(expenseSchema),
    defaultValues: {
      date: now.toISOString().split("T")[0],
      period_month: now.getMonth() + 1,
      period_year: now.getFullYear(),
    },
  });

  const catForm = useForm<CategoryFormData>({ resolver: zodResolver(categorySchema) });

  const onSubmitExpense = (values: ExpenseFormData) => {
    const { building, ...rest } = values;
    createExpense.mutate(
      {
        ...rest,
        building: building && building !== "" ? Number(building) : null,
        reference: values.reference ?? "",
        notes: values.notes ?? "",
      },
      {
        onSuccess: () => {
          toast.success("Expense recorded");
          form.reset({
            date: now.toISOString().split("T")[0],
            period_month: now.getMonth() + 1,
            period_year: now.getFullYear(),
          });
          setShowForm(false);
        },
        onError: () => toast.error("Failed to save expense"),
      },
    );
  };

  const onSubmitCategory = (values: CategoryFormData) => {
    createCategory.mutate(
      { name: values.name, description: values.description ?? "" },
      {
        onSuccess: () => {
          toast.success(`Category "${values.name}" saved`);
          catForm.reset();
          setShowCategoryForm(false);
        },
        onError: () => toast.error("Failed to save category. It may already exist."),
      },
    );
  };

  const total = expenses?.reduce((sum, e) => sum + parseFloat(e.amount), 0) ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Spending"
        title="Expenses & Accounting"
        description="Record costs, review spending, and access your full accounting suite."
        actions={
          mainTab === "expenses" ? (
            <>
              <Button variant="glass" onClick={() => setShowCategoryForm((v) => !v)}>
                <Tag className="h-4 w-4" />
                {showCategoryForm ? "Cancel" : "Add Category"}
              </Button>
              <Button onClick={() => setShowForm((v) => !v)}>
                <PlusCircle className="h-4 w-4" />
                {showForm ? "Cancel" : "Record Expense"}
              </Button>
            </>
          ) : null
        }
      />

      {/* Main tab switch */}
      <div className="glass -mx-1 flex gap-1 overflow-x-auto rounded-xl p-1">
        {MAIN_TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setMainTab(t.key)}
            className={cn(
              "whitespace-nowrap rounded-md px-4 py-2 text-xs font-medium transition-all",
              mainTab === t.key
                ? "bg-ink-900 text-canvas shadow-float dark:bg-ink-100 dark:text-canvas"
                : "text-ink-600 hover:text-ink-900",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Accounting tab ── */}
      {mainTab === "accounting" && (
        <Card variant="glass" padding="md">
          <div className="mb-4">
            <p className="font-display text-lg font-semibold text-ink-900">Accounting Suite</p>
            <p className="text-xs text-ink-500">
              Full double-entry accounting — Balance Sheet, P&amp;L, General Ledger, Chart of
              Accounts, Petty Cash, and Income &amp; Budgeting.
            </p>
          </div>
          <AccountingPanel />
        </Card>
      )}

      {/* ── Expenses tab ── */}
      {mainTab === "expenses" && (
        <>
          {/* Total summary */}
          <Card variant="glass" padding="md" className="relative overflow-hidden">
            <div className="pointer-events-none absolute -right-16 -top-16 h-52 w-52 rounded-full bg-coral-400/25 blur-3xl" />
            <div className="relative flex flex-wrap items-end justify-between gap-4">
              <div>
                <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-ink-500">
                  Total for{" "}
                  {new Date(filterYear, filterMonth - 1).toLocaleString("default", { month: "long" })}{" "}
                  {filterYear}
                </p>
                <p className="mt-1 font-display text-4xl font-semibold text-status-unpaid">
                  KES {total.toLocaleString()}
                </p>
                <p className="mt-1 text-xs text-ink-500">
                  Across {expenses?.length ?? 0} entr{(expenses?.length ?? 0) === 1 ? "y" : "ies"}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <select
                  value={filterBuilding}
                  onChange={(e) => setFilterBuilding(e.target.value as "" | "none" | string)}
                  className="glass rounded-md px-3 py-2 text-sm text-ink-900 focus:outline-none"
                >
                  <option value="">All buildings</option>
                  <option value="none">Portfolio-wide only</option>
                  {buildings?.map((b) => (
                    <option key={b.id} value={b.id}>{b.name}</option>
                  ))}
                </select>
                <select
                  value={filterMonth}
                  onChange={(e) => setFilterMonth(Number(e.target.value))}
                  className="glass rounded-md px-3 py-2 text-sm text-ink-900 focus:outline-none"
                >
                  {Array.from({ length: 12 }, (_, i) => (
                    <option key={i + 1} value={i + 1}>
                      {new Date(2000, i).toLocaleString("default", { month: "long" })}
                    </option>
                  ))}
                </select>
                <input
                  type="number" min="2000" max="2100" value={filterYear}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    if (Number.isFinite(v) && v >= 2000) setFilterYear(v);
                  }}
                  className="glass w-24 rounded-md px-3 py-2 text-sm text-ink-900 focus:outline-none"
                />
              </div>
            </div>
          </Card>

          {/* Category form */}
          {showCategoryForm && (
            <Card variant="glass" padding="md" className="animate-fade-up">
              <p className="mb-4 font-display text-lg font-semibold text-ink-900">New expense category</p>
              <form onSubmit={catForm.handleSubmit(onSubmitCategory)} className="flex flex-wrap gap-3">
                <div className="min-w-[200px] flex-1">
                  <input
                    {...catForm.register("name")}
                    placeholder="Category name (e.g. Repairs, Utilities…)"
                    className={inputCls}
                  />
                  {catForm.formState.errors.name && (
                    <p className="mt-1 text-[11px] text-status-unpaid">
                      {catForm.formState.errors.name.message}
                    </p>
                  )}
                </div>
                <div className="min-w-[200px] flex-1">
                  <input
                    {...catForm.register("description")}
                    placeholder="Short description (optional)"
                    className={inputCls}
                  />
                </div>
                <Button type="submit" loading={createCategory.isPending} variant="primary">
                  Save category
                </Button>

              </form>
            </Card>
          )}

          {/* Expense form */}
          {showForm && (
            <Card variant="glass" padding="md" className="animate-fade-up">
              <p className="mb-5 font-display text-lg font-semibold text-ink-900">Record expense</p>
              <form onSubmit={form.handleSubmit(onSubmitExpense)} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                <DatePicker
                  label="Date *"
                  {...form.register("date")}
                  error={form.formState.errors.date?.message}
                />

                <Field label="Building">
                  <select {...form.register("building")} className={inputCls}>
                    <option value="">Portfolio-wide (no building)</option>
                    {buildings?.map((b) => (
                      <option key={b.id} value={b.id}>{b.name}</option>
                    ))}
                  </select>
                </Field>
                <Field label="Category *" error={form.formState.errors.category?.message}>
                  <select {...form.register("category")} disabled={!categories || categories.length === 0} className={inputCls}>
                    <option value="">Select category…</option>
                    {categories?.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                  {categories && categories.length === 0 && (
                    <p className="mt-1 text-[11px] text-ochre-600">
                      No categories yet — add one above first.
                    </p>
                  )}
                </Field>
                <Field label="Amount (KES) *" error={form.formState.errors.amount?.message}>
                  <input type="number" step="0.01" min="0" {...form.register("amount")} placeholder="0.00" className={inputCls} />
                </Field>
                <Field label="Description *" error={form.formState.errors.description?.message} className="sm:col-span-2">
                  <input {...form.register("description")} placeholder="e.g. Fixed leak in Unit A3 bathroom" className={inputCls} />
                </Field>
                <Field label="Reference">
                  <input {...form.register("reference")} placeholder="Receipt / invoice number" className={inputCls} />
                </Field>
                <Field label="Period">
                  <div className="flex gap-2">
                    <select {...form.register("period_month")} className={inputCls}>
                      {Array.from({ length: 12 }, (_, i) => (
                        <option key={i + 1} value={i + 1}>
                          {new Date(2000, i).toLocaleString("default", { month: "short" })}
                        </option>
                      ))}
                    </select>
                    <input type="number" {...form.register("period_year")} className={inputCls + " w-24"} />
                  </div>
                </Field>
                <Field label="Notes" className="sm:col-span-2">
                  <textarea {...form.register("notes")} rows={2} className={inputCls} />
                </Field>
                <div className="flex items-end">
                  <Button type="submit" loading={createExpense.isPending} className="w-full">
                    Save expense
                  </Button>
                </div>
              </form>
            </Card>
          )}

          {/* Expenses table */}
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-14" />)}
            </div>
          ) : !expenses?.length ? (
            <Card variant="glass" padding="none" className="py-4">
              <EmptyState icon={<PlusCircle className="h-5 w-5" />} title="No expenses recorded"
                description="This period has no recorded expenses yet." />
            </Card>
          ) : (
            <div className="hidden md:block">
              <Table>
                <THead>
                  <TR>
                    <TH>Date</TH><TH>Building</TH><TH>Category</TH>
                    <TH>Description</TH><TH className="text-right">Amount</TH>
                    <TH>Reference</TH><TH></TH>
                  </TR>
                </THead>
                <TBody>
                  {expenses.map((e) => (
                    <TR key={e.id}>
                      <TD className="whitespace-nowrap text-ink-700">{e.date}</TD>
                      <TD className="whitespace-nowrap text-ink-500">
                        {e.building_name ?? <span className="italic">Portfolio</span>}
                      </TD>
                      <TD><Badge tone="peri">{e.category_name}</Badge></TD>
                      <TD className="max-w-xs truncate">{e.description}</TD>
                      <TD className="text-right whitespace-nowrap font-semibold tabular-nums text-status-unpaid">
                        KES {parseFloat(e.amount).toLocaleString()}
                      </TD>
                      <TD className="font-mono text-[11px] text-ink-400">{e.reference || "—"}</TD>
                      <TD>
                        <button
                          type="button"
                          onClick={() => { if (window.confirm("Delete this expense?")) deleteExpense.mutate(e.id); }}
                          className="rounded-md p-1.5 text-ink-400 hover:bg-status-unpaid/10 hover:text-status-unpaid"
                          aria-label="Delete expense"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
