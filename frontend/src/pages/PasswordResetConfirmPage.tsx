/**
 * PasswordResetConfirmPage — user sets a new password using the token from email.
 * Route: /reset-password/confirm/:token
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useParams } from "react-router-dom";
import toast from "react-hot-toast";
import { z } from "zod";
import { api } from "@/lib/api";

const schema = z.object({
  password: z.string().min(12, "Password must be at least 12 characters"),
  confirm:  z.string(),
}).refine((d) => d.password === d.confirm, {
  message: "Passwords do not match",
  path: ["confirm"],
});

type FormValues = z.infer<typeof schema>;

export default function PasswordResetConfirmPage() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const [done, setDone] = useState(false);

  const { register, handleSubmit, formState: { errors, isSubmitting } } =
    useForm<FormValues>({ resolver: zodResolver(schema) });

  const onSubmit = async ({ password }: FormValues) => {
    try {
      await api.post("/auth/password-reset/confirm/", { token, password });
      setDone(true);
      setTimeout(() => navigate("/login"), 2500);
    } catch {
      toast.error("Reset link is invalid or has expired.");
    }
  };

  if (done) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
        <div className="w-full max-w-sm rounded-2xl bg-white p-8 shadow-sm text-center">
          <div className="text-4xl mb-3">✅</div>
          <h2 className="text-xl font-bold text-slate-900">Password updated</h2>
          <p className="mt-2 text-sm text-slate-500">Redirecting you to login…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-sm rounded-2xl bg-white p-8 shadow-sm">
        <h2 className="text-xl font-bold text-slate-900">Set new password</h2>
        <form onSubmit={handleSubmit(onSubmit)} className="mt-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700">New password</label>
            <input
              type="password" {...register("password")} autoFocus
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-400"
            />
            {errors.password && <p className="mt-1 text-xs text-red-600">{errors.password.message}</p>}
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700">Confirm password</label>
            <input
              type="password" {...register("confirm")}
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-400"
            />
            {errors.confirm && <p className="mt-1 text-xs text-red-600">{errors.confirm.message}</p>}
          </div>
          <button
            type="submit" disabled={isSubmitting}
            className="w-full rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-60"
          >
            {isSubmitting ? "Updating..." : "Update password"}
          </button>
        </form>
        <Link to="/login" className="mt-4 block text-center text-sm text-slate-500 underline">
          Back to login
        </Link>
      </div>
    </div>
  );
}
