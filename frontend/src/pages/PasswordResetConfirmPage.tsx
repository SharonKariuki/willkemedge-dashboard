import { zodResolver } from "@hookform/resolvers/zod";
import { CheckCircle2, Lock } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { Link, useNavigate, useParams } from "react-router-dom";
import { z } from "zod";

import AuthShell from "@/components/AuthShell";
import { Button } from "@/components/ui";
import { api } from "@/lib/api";

const schema = z
  .object({
    password: z.string().min(12, "Password must be at least 12 characters"),
    confirm: z.string(),
  })
  .refine((d) => d.password === d.confirm, {
    message: "Passwords do not match",
    path: ["confirm"],
  });

type FormValues = z.infer<typeof schema>;

const inputCls =
  "w-full rounded-md bg-surface-raised hairline py-2.5 pl-10 pr-3 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-sage-500/40";

export default function PasswordResetConfirmPage() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const [done, setDone] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

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
      <AuthShell title="Password updated" subtitle="Redirecting you to login…">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-sage-50 text-sage-600 dark:bg-sage-700/20">
          <CheckCircle2 className="h-6 w-6" />
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Set a new password" subtitle="Choose a password at least 12 characters long.">
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
        <div>
          <label className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
            New password
          </label>
          <div className="relative">
            <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
            <input type="password" {...register("password")} autoFocus className={inputCls} />
          </div>
          {errors.password && <p className="mt-1 text-[11px] text-status-unpaid">{errors.password.message}</p>}
        </div>
        <div>
          <label className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
            Confirm password
          </label>
          <div className="relative">
            <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
            <input type="password" {...register("confirm")} className={inputCls} />
          </div>
          {errors.confirm && <p className="mt-1 text-[11px] text-status-unpaid">{errors.confirm.message}</p>}
        </div>
        <Button type="submit" size="lg" loading={isSubmitting} className="w-full">
          Update password
        </Button>
        <Link to="/login" className="block text-center text-sm text-ink-500 hover:text-ink-900">
          Back to login
        </Link>
      </form>
    </AuthShell>
  );
}
