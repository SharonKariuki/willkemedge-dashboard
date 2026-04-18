import { zodResolver } from "@hookform/resolvers/zod";
import { AxiosError } from "axios";
import { Eye, EyeOff, Lock, Mail } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { z } from "zod";

import AuthShell from "@/components/AuthShell";
import { Button } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";

const schema = z.object({
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(1, "Password is required"),
});

type FormValues = z.infer<typeof schema>;

interface LocationState {
  from?: { pathname?: string };
}

const inputCls =
  "w-full rounded-md bg-surface-raised hairline py-2.5 pl-10 pr-10 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-sage-500/40";

export default function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [submitting, setSubmitting] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { email: "", password: "" },
  });

  if (user) {
    const from = (location.state as LocationState | null)?.from?.pathname ?? "/dashboard";
    return <Navigate to={from} replace />;
  }

  const onSubmit = async (values: FormValues) => {
    setSubmitting(true);
    try {
      await login(values.email, values.password);
      toast.success("Welcome back");
      const from = (location.state as LocationState | null)?.from?.pathname ?? "/dashboard";
      navigate(from, { replace: true });
    } catch (err) {
      const axiosErr = err as AxiosError<{ detail?: string }>;
      const status = axiosErr.response?.status;
      if (status === 429) {
        toast.error("Account locked. Try again in 30 minutes.");
      } else if (status === 400) {
        toast.error("Invalid email or password.");
      } else {
        toast.error("Login failed. Check your connection and try again.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthShell title="Sign in to your portfolio" subtitle="Manage your buildings, tenants, and collections.">
      <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
        <div>
          <label htmlFor="email" className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
            Email
          </label>
          <div className="relative">
            <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
            <input
              id="email"
              type="email"
              autoComplete="email"
              autoFocus
              {...register("email")}
              className={inputCls}
              placeholder="you@clinic.com"
            />
          </div>
          {errors.email && <p className="mt-1 text-[11px] text-status-unpaid">{errors.email.message}</p>}
        </div>

        <div>
          <div className="mb-1 flex items-center justify-between">
            <label htmlFor="password" className="text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
              Password
            </label>
            <Link to="/reset-password" className="text-[11px] text-sage-600 hover:text-sage-700 dark:text-sage-400">
              Forgot?
            </Link>
          </div>
          <div className="relative">
            <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
            <input
              id="password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              {...register("password")}
              className={inputCls}
              placeholder="••••••••"
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-400 hover:text-ink-700"
              aria-label={showPassword ? "Hide password" : "Show password"}
            >
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
          {errors.password && (
            <p className="mt-1 text-[11px] text-status-unpaid">{errors.password.message}</p>
          )}
        </div>

        <Button type="submit" size="lg" loading={submitting} className="w-full">
          Sign in
        </Button>
      </form>
    </AuthShell>
  );
}
