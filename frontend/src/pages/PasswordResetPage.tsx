/**
 * PasswordResetPage — user submits their email to request a reset link.
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { z } from "zod";
import { api } from "@/lib/api";

const schema = z.object({ email: z.string().email("Enter a valid email") });
type FormValues = z.infer<typeof schema>;

export default function PasswordResetPage() {
  const [sent, setSent] = useState(false);
  const { register, handleSubmit, formState: { errors, isSubmitting } } =
    useForm<FormValues>({ resolver: zodResolver(schema) });

  const onSubmit = async ({ email }: FormValues) => {
    await api.post("/auth/password-reset/", { email });
    setSent(true);
  };

  if (sent) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
        <div className="w-full max-w-sm rounded-2xl bg-white p-8 shadow-sm text-center">
          <div className="text-4xl mb-3">📧</div>
          <h2 className="text-xl font-bold text-slate-900">Check your email</h2>
          <p className="mt-2 text-sm text-slate-500">
            If that address is registered, a reset link is on its way. It expires in 15 minutes.
          </p>
          <Link to="/login" className="mt-6 inline-block text-sm text-slate-600 underline">
            Back to login
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-sm rounded-2xl bg-white p-8 shadow-sm">
        <h2 className="text-xl font-bold text-slate-900">Reset password</h2>
        <p className="mt-1 text-sm text-slate-500">
          Enter your email and we'll send a reset link.
        </p>
        <form onSubmit={handleSubmit(onSubmit)} className="mt-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700">Email</label>
            <input
              type="email" {...register("email")} autoFocus
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-400"
            />
            {errors.email && <p className="mt-1 text-xs text-red-600">{errors.email.message}</p>}
          </div>
          <button
            type="submit" disabled={isSubmitting}
            className="w-full rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-60"
          >
            {isSubmitting ? "Sending..." : "Send reset link"}
          </button>
        </form>
        <Link to="/login" className="mt-4 block text-center text-sm text-slate-500 underline">
          Back to login
        </Link>
      </div>
    </div>
  );
}
