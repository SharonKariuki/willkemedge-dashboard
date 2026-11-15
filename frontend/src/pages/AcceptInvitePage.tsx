/**
 * Where an invite link lands: the invited person chooses their password and
 * the account switches on. Public - they have no account to sign in with yet.
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { CheckCircle2, Lock, MailX } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { Link, useNavigate, useParams } from "react-router-dom";
import { z } from "zod";

import AuthShell from "@/components/AuthShell";
import { Button, Skeleton } from "@/components/ui";
import { useInvite } from "@/hooks/useUsers";
import { api } from "@/lib/api";
import { getErrorMessage } from "@/lib/apiError";

const schema = z
  .object({
    password: z.string().min(12, "Password must be at least 12 characters"),
    confirm: z.string(),
  })
  .refine((d) => d.password === d.confirm, { message: "Passwords do not match", path: ["confirm"] });

type FormValues = z.infer<typeof schema>;

const inputCls =
  "w-full rounded-md bg-surface-raised hairline py-2.5 pl-10 pr-3 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-sage-500/40";

export default function AcceptInvitePage() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const { data: invite, isLoading, isError } = useInvite(token);
  const [done, setDone] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  const onSubmit = async ({ password }: FormValues) => {
    try {
      await api.post("/auth/invite/accept/", { token, new_password: password });
      setDone(true);
      setTimeout(() => navigate("/login"), 2500);
    } catch (e) {
      toast.error(getErrorMessage(e, "This invite link is invalid or has expired."));
    }
  };

  if (isLoading) {
    return (
      <AuthShell title="Opening your invite" subtitle="One moment…">
        <Skeleton className="h-24" />
      </AuthShell>
    );
  }

  if (isError || !invite) {
    return (
      <AuthShell
        title="This invite link no longer works"
        subtitle="It has been used, has expired, or the invite was withdrawn."
      >
        <div className="space-y-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-surface-sunk text-ink-500">
            <MailX className="h-6 w-6" />
          </div>
          <p className="text-sm text-ink-700">
            Ask whoever invited you to send a new invite. If you've already set your password, sign in instead.
          </p>
          <Link to="/login" className="block text-center text-sm text-ink-500 hover:text-ink-900">
            Go to sign in
          </Link>
        </div>
      </AuthShell>
    );
  }

  if (done) {
    return (
      <AuthShell title="You're all set" subtitle="Taking you to sign in…">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-sage-50 text-sage-600 dark:bg-sage-700/20">
          <CheckCircle2 className="h-6 w-6" />
        </div>
        <p className="mt-4 text-sm text-ink-700">
          Sign in with <span className="font-medium">{invite.email}</span> and the password you just chose.
        </p>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title={`Welcome${invite.first_name ? `, ${invite.first_name}` : ""}`}
      subtitle={`You've been given access as ${invite.role_display}. Choose a password to finish setting up.`}
    >
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
        <div>
          <p className="mb-1 text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">You'll sign in as</p>
          <p className="text-sm font-medium text-ink-900">{invite.email}</p>
        </div>
        <div>
          <label htmlFor="invite-password" className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
            Password
          </label>
          <div className="relative">
            <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
            <input
              id="invite-password"
              type="password"
              autoComplete="new-password"
              {...register("password")}
              className={inputCls}
            />
          </div>
          {errors.password && <p className="mt-1 text-[11px] text-status-unpaid">{errors.password.message}</p>}
        </div>
        <div>
          <label htmlFor="invite-confirm" className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
            Confirm password
          </label>
          <div className="relative">
            <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
            <input
              id="invite-confirm"
              type="password"
              autoComplete="new-password"
              {...register("confirm")}
              className={inputCls}
            />
          </div>
          {errors.confirm && <p className="mt-1 text-[11px] text-status-unpaid">{errors.confirm.message}</p>}
        </div>
        <p className="text-[11px] leading-relaxed text-ink-500">
          At least 12 characters. A short sentence you'll remember works well.
        </p>
        <Button type="submit" size="lg" loading={isSubmitting} className="w-full">
          Set password and finish
        </Button>
      </form>
    </AuthShell>
  );
}
