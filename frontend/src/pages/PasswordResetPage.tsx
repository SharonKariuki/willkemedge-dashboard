import { zodResolver } from "@hookform/resolvers/zod";
import { CheckCircle2, Mail } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { z } from "zod";

import AuthShell from "@/components/AuthShell";
import { Button } from "@/components/ui";
import { api } from "@/lib/api";

const schema = z.object({ email: z.string().email("Enter a valid email") });
type FormValues = z.infer<typeof schema>;

const inputCls =
  "w-full rounded-md bg-surface-raised hairline py-2.5 pl-10 pr-3 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-sage-500/40";

export default function PasswordResetPage() {
  const [sent, setSent] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  const onSubmit = async ({ email }: FormValues) => {
    await api.post("/auth/password-reset/", { email });
    setSent(true);
  };

  if (sent) {
    return (
      <AuthShell
        title="Check your email"
        subtitle="If that address is registered, a reset link is on its way. It expires in 15 minutes."
      >
        <div className="flex flex-col items-start gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-sage-50 text-sage-600 dark:bg-sage-700/20">
            <CheckCircle2 className="h-6 w-6" />
          </div>
          <Link to="/login" className="text-sm font-medium text-sage-600 hover:text-sage-700 dark:text-sage-400">
            ← Back to login
          </Link>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Reset your password"
      subtitle="Enter your email and we'll send you a secure link to set a new one."
    >
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
        <div>
          <label className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
            Email
          </label>
          <div className="relative">
            <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
            <input
              type="email"
              {...register("email")}
              autoFocus
              className={inputCls}
              placeholder="you@clinic.com"
            />
          </div>
          {errors.email && <p className="mt-1 text-[11px] text-status-unpaid">{errors.email.message}</p>}
        </div>
        <Button type="submit" size="lg" loading={isSubmitting} className="w-full">
          Send reset link
        </Button>
        <Link
          to="/login"
          className="block text-center text-sm text-ink-500 hover:text-ink-900"
        >
          Back to login
        </Link>
      </form>
    </AuthShell>
  );
}
