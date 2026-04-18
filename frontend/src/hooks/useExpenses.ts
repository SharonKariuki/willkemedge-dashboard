import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export interface ExpenseCategory {
  id: number;
  name: string;
  description: string;
  created_at: string;
}

export interface Expense {
  id: number;
  date: string;
  category: number;
  category_name: string;
  amount: string;
  description: string;
  reference: string;
  period_month: number;
  period_year: number;
  notes: string;
  created_at: string;
  updated_at: string;
}

export function useExpenseCategories() {
  return useQuery<ExpenseCategory[]>({
    queryKey: ["expense-categories"],
    queryFn: async () => {
      const { data } = await api.get("/expenses/categories/");
      return data;
    },
  });
}

export function useCreateExpenseCategory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: { name: string; description?: string }) => {
      const { data } = await api.post("/expenses/categories/", payload);
      return data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["expense-categories"] });
    },
  });
}

export function useExpenses(month?: number, year?: number) {
  return useQuery<Expense[]>({
    queryKey: ["expenses", month, year],
    queryFn: async () => {
      const params: Record<string, number> = {};
      if (month) params.month = month;
      if (year) params.year = year;
      const { data } = await api.get("/expenses/", { params });
      return data;
    },
  });
}

export function useCreateExpense() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      date: string;
      category: number;
      amount: string;
      description: string;
      reference?: string;
      period_month: number;
      period_year: number;
      notes?: string;
    }) => {
      const { data } = await api.post("/expenses/", payload);
      return data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["expenses"] });
    },
  });
}

export function useDeleteExpense() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/expenses/${id}/`);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["expenses"] });
    },
  });
}
