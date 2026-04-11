/**
 * Settings page — login audit viewer + account info.
 */
import { useQuery } from "@tanstack/react-query";
import { CheckCircle, Shield, XCircle } from "lucide-react";

import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";

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
  const { user } = useAuth();
  const { data: audit, isLoading } = useLoginAudit();

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-slate-900">Settings</h2>

      {/* Account info */}
      <div className="rounded-xl border border-slate-200 bg-white p-5">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900 mb-3">
          <Shield className="h-4 w-4" /> Account
        </h3>
        <div className="grid gap-3 sm:grid-cols-2 text-sm">
          <div>
            <p className="text-slate-500">Email</p>
            <p className="font-medium text-slate-900">{user?.email}</p>
          </div>
          <div>
            <p className="text-slate-500">Username</p>
            <p className="font-medium text-slate-900">{user?.username}</p>
          </div>
        </div>
      </div>

      {/* Login audit */}
      <div className="rounded-xl border border-slate-200 bg-white p-5">
        <h3 className="text-sm font-semibold text-slate-900 mb-3">Login Audit Log</h3>
        {isLoading ? (
          <p className="text-sm text-slate-500">Loading...</p>
        ) : !audit?.length ? (
          <p className="text-sm text-slate-500">No login attempts recorded.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs font-medium uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Email</th>
                  <th className="px-4 py-3">IP Address</th>
                  <th className="px-4 py-3">Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {audit.map((a, i) => (
                  <tr key={i} className="hover:bg-slate-50">
                    <td className="px-4 py-3">
                      {a.successful ? (
                        <span className="inline-flex items-center gap-1 text-green-700">
                          <CheckCircle className="h-3.5 w-3.5" /> Success
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-red-600">
                          <XCircle className="h-3.5 w-3.5" /> Failed
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-700">{a.email}</td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-500">
                      {a.ip_address || "—"}
                    </td>
                    <td className="px-4 py-3 text-slate-500">
                      {new Date(a.attempted_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
