import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, LogOut, Mail, Pencil, Save, Shield, User, X, XCircle } from "lucide-react";
import { useState } from "react";
import toast from "react-hot-toast";

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

const inputCls =
  "w-full rounded-md border border-gray-300 bg-white px-3 py-2.5 text-sm text-gray-900 placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20";

export default function SettingsPage() {
  const { user, logout } = useAuth();
  const qc = useQueryClient();
  const { data: audit, isLoading } = useLoginAudit();

  const [editing, setEditing] = useState(false);
  const [profileForm, setProfileForm] = useState({
    first_name: user?.first_name ?? "",
    last_name: user?.last_name ?? "",
    email: user?.email ?? "",
    phone: (user as Record<string, unknown>)?.phone as string ?? "",
  });
  const [pwForm, setPwForm] = useState({ current_password: "", new_password: "", confirm_password: "" });
  const [pwEditing, setPwEditing] = useState(false);
  const [pwSaving, setPwSaving] = useState(false);

  const saveProfile = useMutation({
    mutationFn: async (data: typeof profileForm) => {
      const res = await api.patch("/auth/me/", data);
      return res.data;
    },
    onSuccess: () => {
      toast.success("Profile updated");
      qc.invalidateQueries({ queryKey: ["me"] });
      setEditing(false);
    },
    onError: () => toast.error("Failed to update profile"),
  });

  const handlePwSave = async () => {
    if (pwForm.new_password !== pwForm.confirm_password) {
      toast.error("Passwords do not match");
      return;
    }
    if (pwForm.new_password.length < 8) {
      toast.error("Password must be at least 8 characters");
      return;
    }
    setPwSaving(true);
    try {
      await api.post("/auth/change-password/", {
        current_password: pwForm.current_password,
        new_password: pwForm.new_password,
      });
      toast.success("Password changed successfully");
      setPwEditing(false);
      setPwForm({ current_password: "", new_password: "", confirm_password: "" });
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Failed to change password";
      toast.error(msg);
    } finally {
      setPwSaving(false);
    }
  };

  const displayUserName = user?.first_name && user?.last_name
    ? `${user.first_name} ${user.last_name}`
    : displayName(user?.email?.split("@")[0]) || "User";

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Preferences"
        title="Settings"
        description="Edit your profile, change your password, and review login activity."
      />

      {/* Profile card */}
      <Card variant="glass" padding="md" className="relative overflow-hidden">
        <div className="pointer-events-none absolute -right-20 -top-20 h-64 w-64 rounded-full bg-sage-400/20 blur-3xl" />
        <div className="relative flex flex-col items-start gap-4 sm:flex-row sm:items-start">
          <div className="relative shrink-0">
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
              {displayUserName}
            </p>
            <p className="flex items-center gap-1.5 text-sm text-ink-500">
              <Mail className="h-3.5 w-3.5" />
              {displayName(user?.email)}
            </p>
          </div>
          <div className="flex gap-2 mt-2 sm:mt-0">
            <Button variant="outline" size="sm" onClick={() => setEditing(!editing)}>
              {editing ? <X className="h-4 w-4" /> : <Pencil className="h-4 w-4" />}
              {editing ? "Cancel" : "Edit profile"}
            </Button>
            <Button variant="outline" onClick={() => void logout()}>
              <LogOut className="h-4 w-4" />
              Sign out
            </Button>
          </div>
        </div>

        {/* Inline edit form */}
        {editing && (
          <div className="mt-6 rounded-xl border border-gray-200 bg-gray-50 p-4">
            <p className="mb-4 text-sm font-semibold text-gray-800">Edit profile information</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-wider text-gray-500">First name</label>
                <input
                  className={inputCls}
                  value={profileForm.first_name}
                  onChange={(e) => setProfileForm((f) => ({ ...f, first_name: e.target.value }))}
                  placeholder="First name"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-wider text-gray-500">Last name</label>
                <input
                  className={inputCls}
                  value={profileForm.last_name}
                  onChange={(e) => setProfileForm((f) => ({ ...f, last_name: e.target.value }))}
                  placeholder="Last name"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-wider text-gray-500">Email address</label>
                <input
                  type="email"
                  className={inputCls}
                  value={profileForm.email}
                  onChange={(e) => setProfileForm((f) => ({ ...f, email: e.target.value }))}
                  placeholder="Email"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-wider text-gray-500">Phone number</label>
                <input
                  className={inputCls}
                  value={profileForm.phone}
                  onChange={(e) => setProfileForm((f) => ({ ...f, phone: e.target.value }))}
                  placeholder="+254…"
                />
              </div>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setEditing(false)}
                className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => saveProfile.mutate(profileForm)}
                disabled={saveProfile.isPending}
                className="flex items-center gap-2 rounded-lg bg-gray-900 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-800 disabled:opacity-60 transition-colors"
              >
                <Save className="h-4 w-4" />
                {saveProfile.isPending ? "Saving…" : "Save changes"}
              </button>
            </div>
          </div>
        )}
      </Card>

      {/* Account info + Change password */}
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
              <dt className="text-ink-500">Display name</dt>
              <dd className="truncate font-medium text-ink-900">{displayUserName}</dd>
            </div>
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
              <dd><Badge tone="sage">Administrator</Badge></dd>
            </div>
          </dl>
        </Card>

        <Card variant="glass" padding="md">
          <CardHeader>
            <div className="flex items-center gap-2">
              <Shield className="h-4 w-4 text-sage-600" />
              <CardTitle>Change Password</CardTitle>
            </div>
            {!pwEditing && (
              <Button size="sm" variant="glass" onClick={() => setPwEditing(true)}>
                <Pencil className="h-3.5 w-3.5" /> Change
              </Button>
            )}
          </CardHeader>
          {pwEditing ? (
            <div className="space-y-3">
              {[
                { key: "current_password", label: "Current password" },
                { key: "new_password", label: "New password" },
                { key: "confirm_password", label: "Confirm new password" },
              ].map(({ key, label }) => (
                <div key={key}>
                  <label className="mb-1 block text-xs font-medium uppercase tracking-wider text-gray-500">{label}</label>
                  <input
                    type="password"
                    className={inputCls}
                    value={pwForm[key as keyof typeof pwForm]}
                    onChange={(e) => setPwForm((f) => ({ ...f, [key]: e.target.value }))}
                    placeholder={label}
                  />
                </div>
              ))}
              <div className="flex justify-end gap-2 pt-1">
                <button onClick={() => { setPwEditing(false); setPwForm({ current_password: "", new_password: "", confirm_password: "" }); }}
                  className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors">
                  Cancel
                </button>
                <button
                  onClick={handlePwSave}
                  disabled={pwSaving}
                  className="flex items-center gap-2 rounded-lg bg-gray-900 px-3 py-2 text-sm font-semibold text-white hover:bg-gray-800 disabled:opacity-60 transition-colors"
                >
                  <Save className="h-4 w-4" />
                  {pwSaving ? "Saving…" : "Update password"}
                </button>
              </div>
            </div>
          ) : (
            <p className="text-sm text-ink-500">Your password was last changed when your account was set up. Click "Change" to update it.</p>
          )}
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
