/**
 * Expenses page — record property expenses and browse existing ones.
 */
import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { PlusCircle, Trash2, Tag } from "lucide-react";

import {
  useExpenses,
  useExpenseCategories,
  useCreateExpense,
  useCreateExpenseCategory,
  useDeleteExpense,
} from "@/hooks/useExpenses";

// ---------------------------------------------------------------------------
// Validation schema
// ---------------------------------------------------------------------------
const expenseSchema = z.object({
  date: z.string().min(1, "Date is required"),
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

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function ExpensesPage() {
  const now = new Date();
  const [filterMonth, setFilterMonth] = useState(now.getMonth() + 1);
  const [filterYear, setFilterYear] = useState(now.getFullYear());
  const [showForm, setShowForm] = useState(false);
  const [showCategoryForm, setShowCategoryForm] = useState(false);

  const { data: expenses, isLoading } = useExpenses(filterMonth, filterYear);
  const { data: categories } = useExpenseCategories();
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

  const catForm = useForm<CategoryFormData>({
    resolver: zodResolver(categorySchema),
  });

  const onSubmitExpense = (values: ExpenseFormData) => {
    createExpense.mutate(
      {
        ...values,
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

  const totalForPeriod = expenses?.reduce(
    (sum, e) => sum + parseFloat(e.amount),
    0
  ) ?? 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-2xl font-bold text-slate-900 dark:text-slate-100">Expenses</h2>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setShowCategoryForm((v) => !v)}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
          >
            <Tag className="h-4 w-4" />
            {showCategoryForm ? "Cancel" : "Add Category"}
          </button>
          <button
            type="button"
            onClick={() => setShowForm((v) => !v)}
            className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-200"
          >
            <PlusCircle className="h-4 w-4" />
            {showForm ? "Cancel" : "Record Expense"}
          </button>
        </div>
      </div>

      {/* Category form */}
      {showCategoryForm && (
        <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
          <h3 className="mb-4 text-base font-semibold text-slate-900 dark:text-slate-100">New Category</h3>
          <form onSubmit={catForm.handleSubmit(onSubmitCategory)} className="flex flex-wrap gap-3">
            <div className="flex-1 min-w-[160px]">
              <input
                {...catForm.register("name")}
                placeholder="Category name (e.g. Repairs)"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
              />
              {catForm.formState.errors.name && (
                <p className="mt-1 text-xs text-red-600">{catForm.formState.errors.name.message}</p>
              )}
            </div>
            <div className="flex-1 min-w-[200px]">
              <input
                {...catForm.register("description")}
                placeholder="Description (optional)"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
              />
            </div>
            <button
              type="submit"
              disabled={createCategory.isPending}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
            >
              {createCategory.isPending ? "Saving..." : "Save Category"}
            </button>
          </form>
        </div>
      )}

      {/* Expense form */}
      {showForm && (
        <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
          <h3 className="mb-4 text-base font-semibold text-slate-900 dark:text-slate-100">Record Expense</h3>
          <form onSubmit={form.handleSubmit(onSubmitExpense)} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {/* Date */}
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">Date</label>
              <input
                type="date"
                {...form.register("date")}
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
              />
              {form.formState.errors.date && (
                <p className="mt-1 text-xs text-red-600">{form.formState.errors.date.message}</p>
              )}
            </div>

            {/* Category */}
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">Category</label>
              <select
                {...form.register("category")}
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
              >
                <option value="">Select category...</option>
                {categories?.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
              {form.formState.errors.category && (
                <p className="mt-1 text-xs text-red-600">{form.formState.errors.category.message}</p>
              )}
            </div>

            {/* Amount */}
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">Amount (KES)</label>
              <input
                type="number"
                step="0.01"
                min="0"
                {...form.register("amount")}
                placeholder="0.00"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
              />
              {form.formState.errors.amount && (
                <p className="mt-1 text-xs text-red-600">{form.formState.errors.amount.message}</p>
              )}
            </div>

            {/* Description */}
            <div className="sm:col-span-2">
              <label className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">Description</label>
              <input
                {...form.register("description")}
                placeholder="e.g. Fixed leak in Unit A3 bathroom"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
              />
              {form.formState.errors.description && (
                <p className="mt-1 text-xs text-red-600">{form.formState.errors.description.message}</p>
              )}
            </div>

            {/* Reference */}
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">Reference (optional)</label>
              <input
                {...form.register("reference")}
                placeholder="Receipt / invoice number"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
              />
            </div>

            {/* Period */}
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">Period</label>
              <div className="flex gap-2">
                <select
                  {...form.register("period_month")}
                  className="flex-1 rounded-lg border border-slate-200 px-2 py-2 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                >
                  {Array.from({ length: 12 }, (_, i) => (
                    <option key={i + 1} value={i + 1}>
                      {new Date(2000, i).toLocaleString("default", { month: "short" })}
                    </option>
                  ))}
                </select>
                <input
                  type="number"
                  {...form.register("period_year")}
                  className="w-20 rounded-lg border border-slate-200 px-2 py-2 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                />
              </div>
            </div>

            {/* Notes */}
            <div className="sm:col-span-2">
              <label className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">Notes (optional)</label>
              <textarea
                {...form.register("notes")}
                rows={2}
                placeholder="Any additional details..."
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
              />
            </div>

            {/* Submit */}
            <div className="flex items-end">
              <button
                type="submit"
                disabled={createExpense.isPending}
                className="w-full rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
              >
                {createExpense.isPending ? "Saving..." : "Save Expense"}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm font-medium text-slate-600 dark:text-slate-400">Filter period:</span>
        <select
          value={filterMonth}
          onChange={(e) => setFilterMonth(Number(e.target.value))}
          className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
        >
          {Array.from({ length: 12 }, (_, i) => (
            <option key={i + 1} value={i + 1}>
              {new Date(2000, i).toLocaleString("default", { month: "long" })}
            </option>
          ))}
        </select>
        <input
          type="number"
          value={filterYear}
          onChange={(e) => setFilterYear(Number(e.target.value))}
          className="w-20 rounded-lg border border-slate-200 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
        />
        {expenses && expenses.length > 0 && (
          <span className="ml-auto text-sm font-semibold text-slate-700 dark:text-slate-300">
            Total: <span className="text-red-600">KES {totalForPeriod.toLocaleString()}</span>
          </span>
        )}
      </div>

      {/* Table */}
      <div className="rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
        {isLoading ? (
          <p className="p-6 text-sm text-slate-500">Loading...</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs font-medium uppercase text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                <tr>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Category</th>
                  <th className="px-4 py-3">Description</th>
                  <th className="px-4 py-3">Amount</th>
                  <th className="px-4 py-3">Reference</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {!expenses || expenses.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-slate-400">
                      No expenses recorded for this period.
                    </td>
                  </tr>
                ) : (
                  expenses.map((e) => (
                    <tr key={e.id} className="hover:bg-slate-50 dark:hover:bg-slate-800">
                      <td className="px-4 py-3 text-slate-700 dark:text-slate-300 whitespace-nowrap">{e.date}</td>
                      <td className="px-4 py-3">
                        <span className="inline-block rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 dark:bg-slate-700 dark:text-slate-300">
                          {e.category_name}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-700 dark:text-slate-300 max-w-xs truncate">{e.description}</td>
                      <td className="px-4 py-3 font-medium text-red-600 whitespace-nowrap">
                        KES {parseFloat(e.amount).toLocaleString()}
                      </td>
                      <td className="px-4 py-3 text-slate-500 dark:text-slate-400">{e.reference || "—"}</td>
                      <td className="px-4 py-3">
                        <button
                          type="button"
                          onClick={() => {
                            if (window.confirm("Delete this expense?")) {
                              deleteExpense.mutate(e.id);
                            }
                          }}
                          className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/20"
                          aria-label="Delete expense"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
