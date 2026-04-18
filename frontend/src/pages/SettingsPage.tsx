import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, LogOut, Mail, Shield, User, XCircle } from "lucide-react";

import {
  Badge,
  Button,
  Card,
  CardHeader,
  CardTitle,
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
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";
import { displayName } from "@/lib/displayName";
import { avatarFor } from "@/lib/images";

interface LoginAttempt {
  email: string;
  ip_address: string | null;
  user_agent: string;
  successful: boolean;
  attempted_at: string;
}

function useLoginAudit() {
  return useQuery<LoginAttempt[]>({
    queryKey: ["login-audit"],
    queryFn: async () => {
      const { data } = await api.get("/auth/login-audit/");
      return data;
    },
  });
}

export default function SettingsPage() {
  const { user, logout } = useAuth();
  const { data: audit, isLoading } = useLoginAudit();

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Preferences"
        title="Settings"
        description="Account details, appearance, and login activity."
      />

      {/* Profile card */}
      <Card variant="glass" padding="md" className="relative overflow-hidden">
        <div className="pointer-events-none absolute -right-20 -top-20 h-64 w-64 rounded-full bg-sage-400/20 blur-3xl" />
        <div className="relative flex flex-col items-start gap-4 sm:flex-row sm:items-center">
          <div className="relative">
            <img
              src={avatarFor(user?.email ?? "user")}
              alt=""
              aria-hidden
              className="h-20 w-20 rounded-full shadow-float"
            />
            <span className="absolute bottom-0 right-0 h-5 w-5 rounded-full border-2 border-canvas bg-status-paid" />
          </div>
          <div className="min-w-0 flex-1">
            <Badge tone="sage" withDot>Admin</Badge>
            <p className="mt-2 font-display text-2xl font-semibold text-ink-900">
              {displayName(user?.email?.split("@")[0]) || "User"}
            </p>
            <p className="flex items-center gap-1.5 text-sm text-ink-500">
              <Mail className="h-3.5 w-3.5" />
              {displayName(user?.email)}
            </p>
          </div>
          <Button variant="outline" onClick={() => void logout()}>
            <LogOut className="h-4 w-4" />
            Sign out
          </Button>
        </div>
      </Card>

      {/* Details + appearance */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card variant="glass" padding="md">
          <CardHeader>
            <div className="flex items-center gap-2">
              <User className="h-4 w-4 text-sage-600" />
              <CardTitle>Account</CardTitle>
            </div>
          </CardHeader>
          <dl className="space-y-3 text-sm">
            <div className="flex items-center justify-between gap-3 rounded-md bg-white/40 p-3 dark:bg-white/5">
              <dt className="text-ink-500">Email</dt>
              <dd className="truncate font-medium text-ink-900">{displayName(user?.email)}</dd>
            </div>
            <div className="flex items-center justify-between gap-3 rounded-md bg-white/40 p-3 dark:bg-white/5">
              <dt className="text-ink-500">Username</dt>
              <dd className="truncate font-medium text-ink-900">{displayName(user?.username)}</dd>
            </div>
            <div className="flex items-center justify-between gap-3 rounded-md bg-white/40 p-3 dark:bg-white/5">
              <dt className="text-ink-500">Role</dt>
              <dd>
                <Badge tone="sage">Administrator</Badge>
              </dd>
            </div>
          </dl>
        </Card>

      </div>

      {/* Login audit */}
      <Card variant="glass" padding="md">
        <CardHeader>
          <div className="flex items-center gap-2">
            <Shield className="h-4 w-4 text-coral-500" />
            <CardTitle>Login activity</CardTitle>
          </div>
          {audit && <Badge tone="neutral">{audit.length} recent attempts</Badge>}
        </CardHeader>

        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-14" />
            ))}
          </div>
        ) : !audit?.length ? (
          <EmptyState
            icon={<Shield className="h-5 w-5" />}
            title="No login attempts recorded"
            description="Activity will appear here."
          />
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Status</TH>
                <TH>Email</TH>
                <TH>IP address</TH>
                <TH>Time</TH>
              </TR>
            </THead>
            <TBody>
              {audit.map((a, i) => (
                <TR key={i}>
                  <TD>
                    {a.successful ? (
                      <Badge tone="sage" withDot>
                        <CheckCircle2 className="h-3 w-3" />
                        Success
                      </Badge>
                    ) : (
                      <Badge tone="unpaid" withDot>
                        <XCircle className="h-3 w-3" />
                        Failed
                      </Badge>
                    )}
                  </TD>
                  <TD>{displayName(a.email)}</TD>
                  <TD className="font-mono text-[11px] text-ink-500">{a.ip_address || "—"}</TD>
                  <TD className="text-ink-500">{new Date(a.attempted_at).toLocaleString()}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </div>
  );
}
