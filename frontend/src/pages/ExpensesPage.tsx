import { zodResolver } from "@hookform/resolvers/zod";
import { PlusCircle, Tag, Trash2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import {
  Badge,
  Button,
  Card,
  EmptyState,
  PageHeader,
  Skeleton,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/components/ui";
import { useBuildings } from "@/hooks/useBuildings";
import {
  useCreateExpense,
  useCreateExpenseCategory,
  useDeleteExpense,
  useExpenseCategories,
  useExpenses,
} from "@/hooks/useExpenses";

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
  name: z.string().min(1, "Name is required"),
  description: z.string().optional(),
});
type CategoryFormData = z.infer<typeof categorySchema>;

const inputCls =
  "w-full rounded-md bg-surface-raised hairline px-3 py-2.5 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-sage-500/40";

function Field({
  label,
  error,
  children,
  className,
}: {
  label: string;
  error?: string;
  children: React.ReactNode;
  className?: string;
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

export default function ExpensesPage() {
  const now = new Date();
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
          form.reset({
            date: now.toISOString().split("T")[0],
            period_month: now.getMonth() + 1,
            period_year: now.getFullYear(),
          });
          setShowForm(false);
        },
      }
    );
  };

  const onSubmitCategory = (values: CategoryFormData) => {
    createCategory.mutate(
      { name: values.name, description: values.description ?? "" },
      {
        onSuccess: () => {
          catForm.reset();
          setShowCategoryForm(false);
        },
      }
    );
  };

  const total = expenses?.reduce((sum, e) => sum + parseFloat(e.amount), 0) ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Spending"
        title="Expenses"
        description="Record and review property-related costs — maintenance, utilities, taxes, and more."
        actions={
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
        }
      />

      {/* Total summary */}
      <Card variant="glass" padding="md" className="relative overflow-hidden">
        <div className="pointer-events-none absolute -right-16 -top-16 h-52 w-52 rounded-full bg-coral-400/25 blur-3xl" />
        <div className="relative flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-ink-500">
              Total for {new Date(filterYear, filterMonth - 1).toLocaleString("default", { month: "long" })}{" "}
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
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
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
              type="number"
              min="2000"
              max="2100"
              value={filterYear}
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
          <p className="mb-4 font-display text-lg font-semibold text-ink-900">New category</p>
          <form onSubmit={catForm.handleSubmit(onSubmitCategory)} className="flex flex-wrap gap-3">
            <div className="min-w-[160px] flex-1">
              <input
                {...catForm.register("name")}
                placeholder="Category name (e.g. Repairs)"
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
                placeholder="Description (optional)"
                className={inputCls}
              />
            </div>
            <Button type="submit" loading={createCategory.isPending}>
              Save category
            </Button>
          </form>
        </Card>
      )}

      {/* Expense form */}
      {showForm && (
        <Card variant="glass" padding="md" className="animate-fade-up">
          <p className="mb-5 font-display text-lg font-semibold text-ink-900">Record expense</p>
          <form
            onSubmit={form.handleSubmit(onSubmitExpense)}
            className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
          >
            <Field label="Date *" error={form.formState.errors.date?.message}>
              <input type="date" {...form.register("date")} className={inputCls} />
            </Field>
            <Field label="Building">
              <select {...form.register("building")} className={inputCls}>
                <option value="">Portfolio-wide (no building)</option>
                {buildings?.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Category *" error={form.formState.errors.category?.message}>
              <select
                {...form.register("category")}
                disabled={!categories || categories.length === 0}
                className={inputCls}
              >
                <option value="">Select category…</option>
                {categories?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
              {categories && categories.length === 0 && (
                <p className="mt-1 text-[11px] text-ochre-600">
                  No categories yet — add one above first.
                </p>
              )}
            </Field>
            <Field label="Amount (KES) *" error={form.formState.errors.amount?.message}>
              <input
                type="number"
                step="0.01"
                min="0"
                {...form.register("amount")}
                placeholder="0.00"
                className={inputCls}
              />
            </Field>
            <Field
              label="Description *"
              error={form.formState.errors.description?.message}
              className="sm:col-span-2"
            >
              <input
                {...form.register("description")}
                placeholder="e.g. Fixed leak in Unit A3 bathroom"
                className={inputCls}
              />
            </Field>
            <Field label="Reference">
              <input
                {...form.register("reference")}
                placeholder="Receipt / invoice number"
                className={inputCls}
              />
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
                <input
                  type="number"
                  {...form.register("period_year")}
                  className={inputCls + " w-24"}
                />
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
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-14" />
          ))}
        </div>
      ) : !expenses?.length ? (
        <Card variant="glass" padding="none" className="py-4">
          <EmptyState
            icon={<PlusCircle className="h-5 w-5" />}
            title="No expenses recorded"
            description="This period has no recorded expenses yet."
          />
        </Card>
      ) : (
        <>
          <div className="hidden md:block">
            <Table>
              <THead>
                <TR>
                  <TH>Date</TH>
                  <TH>Building</TH>
                  <TH>Category</TH>
                  <TH>Description</TH>
                  <TH className="text-right">Amount</TH>
                  <TH>Reference</TH>
                  <TH></TH>
                </TR>
              </THead>
              <TBody>
                {expenses.map((e) => (
                  <TR key={e.id}>
                    <TD className="whitespace-nowrap text-ink-700">{e.date}</TD>
                    <TD className="whitespace-nowrap text-ink-500">
                      {e.building_name ?? <span className="italic">Portfolio</span>}
                    </TD>
                    <TD>
                      <Badge tone="peri">{e.category_name}</Badge>
                    </TD>
                    <TD className="max-w-xs truncate">{e.description}</TD>
                    <TD className="text-right whitespace-nowrap font-semibold tabular-nums text-status-unpaid">
                      KES {parseFloat(e.amount).toLocaleString()}
                    </TD>
                    <TD className="font-mono text-[11px] text-ink-400">{e.reference || "—"}</TD>
                    <TD>
                      <button
                        type="button"
                        onClick={() => {
                          if (window.confirm("Delete this expense?")) {
                            deleteExpense.mutate(e.id);
                          }
                        }}
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

          <div className="grid gap-3 md:hidden">
            {expenses.map((e) => (
              <Card key={e.id} variant="glass" padding="sm">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <Badge tone="peri">{e.category_name}</Badge>
                      <span className="text-[11px] text-ink-500">{e.date}</span>
                    </div>
                    <p className="mt-2 text-sm font-medium text-ink-900">{e.description}</p>
                    <p className="mt-1 text-[11px] text-ink-500">
                      {e.building_name ?? "Portfolio-wide"}
                      {e.reference ? ` · ${e.reference}` : ""}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-semibold tabular-nums text-status-unpaid">
                      KES {parseFloat(e.amount).toLocaleString()}
                    </p>
                    <button
                      type="button"
                      onClick={() => {
                        if (window.confirm("Delete this expense?")) {
                          deleteExpense.mutate(e.id);
                        }
                      }}
                      className="mt-2 rounded-md p-1.5 text-ink-400 hover:bg-status-unpaid/10 hover:text-status-unpaid"
                      aria-label="Delete expense"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
