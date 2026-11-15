/**
 * Users - who can sign in, and what each person may do.
 *
 * Nobody signs themselves up. The owner (or the superadmin) invites a person
 * by email with a role; they receive a link to choose their own password.
 * From here the owner changes roles and switches accounts off, which signs
 * the person out at once. The API holds the rules; this page shows only the
 * controls the signed-in person may actually use.
 */
import { MailPlus, Power, RotateCw, ShieldCheck, UserPlus } from "lucide-react";
import { useState } from "react";
import toast from "react-hot-toast";

import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Modal,
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
import {
  type ManagedUser,
  type RoleOption,
  useInviteUser,
  useUpdateUser,
  useUserAction,
  useUsers,
} from "@/hooks/useUsers";
import { getErrorMessage } from "@/lib/apiError";

const inputCls =
  "w-full rounded-md bg-surface-raised hairline px-3 py-2.5 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-sage-500/40";

/** What each role may do, in a sentence - shown when choosing one. */
const ROLE_HINTS: Record<string, string> = {
  owner: "Everything, including voiding payments, waiving arrears and managing users.",
  accountant: "Records payments, expenses and income, and runs reports. Can't void or waive.",
  caretaker: "Day-to-day work on the properties they look after.",
  viewer: "Can look at everything but change nothing.",
};

const when = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })
    : "Never";

const day = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short" }) : "";

function StatusBadge({ user }: { user: ManagedUser }) {
  if (user.status === "invited") {
    return (
      <Badge tone="partial" withDot title={user.invited_by_email ? `Invited by ${user.invited_by_email}` : undefined}>
        Invited{user.invite_expires_at ? ` · link expires ${day(user.invite_expires_at)}` : " · link expired"}
      </Badge>
    );
  }
  if (user.status === "deactivated") return <Badge tone="vacant" withDot>Switched off</Badge>;
  return <Badge tone="paid" withDot>Active</Badge>;
}

/** Whether the signed-in person may change this account (mirrors the API's rule). */
function editable(user: ManagedUser, meIsSuperuser: boolean): boolean {
  if (user.is_self) return false;
  if (meIsSuperuser) return true;
  return !user.is_superuser && user.role !== "owner";
}

function InviteModal({ roles, onClose }: { roles: RoleOption[]; onClose: () => void }) {
  const invite = useInviteUser();
  const [email, setEmail] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [role, setRole] = useState(roles.find((r) => r.value === "viewer")?.value ?? roles[0]?.value ?? "");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await invite.mutateAsync({ email: email.trim(), role, first_name: firstName, last_name: lastName });
      toast.success(`Invite sent to ${email.trim()}`);
      onClose();
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not send the invite"));
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      size="md"
      eyebrow="Users"
      title="Invite someone"
      closeOnBackdrop={false}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" form="invite-form" loading={invite.isPending} disabled={!email.trim() || !role}>
            <MailPlus className="h-4 w-4" />
            Send invite
          </Button>
        </>
      }
    >
      <form id="invite-form" onSubmit={submit} className="space-y-4">
        <div>
          <label htmlFor="invite-email" className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
            Email *
          </label>
          <input
            id="invite-email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="name@example.com"
            className={inputCls}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="invite-first" className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
              First name
            </label>
            <input id="invite-first" value={firstName} onChange={(e) => setFirstName(e.target.value)} className={inputCls} />
          </div>
          <div>
            <label htmlFor="invite-last" className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
              Last name
            </label>
            <input id="invite-last" value={lastName} onChange={(e) => setLastName(e.target.value)} className={inputCls} />
          </div>
        </div>
        <div>
          <label htmlFor="invite-role" className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500">
            Role *
          </label>
          <select id="invite-role" value={role} onChange={(e) => setRole(e.target.value)} className={inputCls}>
            {roles.map((r) => (
              <option key={r.value} value={r.value}>{r.label}</option>
            ))}
          </select>
          {ROLE_HINTS[role] && <p className="mt-1.5 text-xs text-ink-500">{ROLE_HINTS[role]}</p>}
        </div>
        <p className="text-[11px] leading-relaxed text-ink-500">
          They'll get an email with a link to choose their own password. The link works once and
          expires in 3 days. Nobody else ever sees their password.
        </p>
      </form>
    </Modal>
  );
}

function SwitchOffModal({ user, onClose }: { user: ManagedUser; onClose: () => void }) {
  const action = useUserAction();
  const name = user.full_name || user.email;
  const confirm = async () => {
    try {
      await action.mutateAsync({ id: user.id, action: "deactivate" });
      toast.success(`${name} is switched off`);
      onClose();
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not switch the account off"));
    }
  };
  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      eyebrow="Users"
      title="Switch this account off?"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="danger" onClick={confirm} loading={action.isPending}>
            <Power className="h-4 w-4" />
            Switch off
          </Button>
        </>
      }
    >
      <p className="text-sm text-ink-900">
        <span className="font-medium">{name}</span> will be signed out straight away and won't be able to sign in.
      </p>
      <p className="mt-2 text-xs text-ink-500">
        Nothing is deleted - everything they recorded stays on the books under their name, and you can switch
        the account back on at any time.
      </p>
    </Modal>
  );
}

export default function UsersPage() {
  const { user: me } = useAuth();
  const { data, isLoading, isError, refetch } = useUsers();
  const update = useUpdateUser();
  const action = useUserAction();
  const [inviting, setInviting] = useState(false);
  const [switchingOff, setSwitchingOff] = useState<ManagedUser | null>(null);

  const meIsSuperuser = Boolean(me?.is_superuser);
  const roles = data?.assignable_roles ?? [];

  const changeRole = async (user: ManagedUser, role: string) => {
    try {
      await update.mutateAsync({ id: user.id, role });
      toast.success(`${user.full_name || user.email} is now ${roles.find((r) => r.value === role)?.label ?? role}`);
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not change the role"));
    }
  };

  const run = async (user: ManagedUser, act: "resend" | "reactivate", done: string) => {
    try {
      await action.mutateAsync({ id: user.id, action: act });
      toast.success(done);
    } catch (err) {
      toast.error(getErrorMessage(err, "That didn't work"));
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Administration"
        title="Users"
        description="Invite people to the dashboard and choose what each of them can do."
        actions={
          <Button onClick={() => setInviting(true)} disabled={!roles.length}>
            <UserPlus className="h-4 w-4" />
            Invite someone
          </Button>
        }
      />

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-14" />)}
        </div>
      ) : isError ? (
        <Card variant="glass" padding="none" className="py-4">
          <ErrorState title="Users could not be loaded." description="This is usually temporary." onRetry={() => void refetch()} />
        </Card>
      ) : !data?.users.length ? (
        <Card variant="glass" padding="none" className="py-4">
          <EmptyState icon={<UserPlus className="h-5 w-5" />} title="No users yet" description="Invite someone to get started." />
        </Card>
      ) : (
        <Table minWidth={860}>
          <THead>
            <TR>
              <TH>Person</TH>
              <TH>Role</TH>
              <TH>Status</TH>
              <TH>Last signed in</TH>
              <TH className="text-right">Actions</TH>
            </TR>
          </THead>
          <TBody>
            {data.users.map((u) => {
              const canEdit = editable(u, meIsSuperuser);
              const roleChoices = roles.some((r) => r.value === u.role)
                ? roles
                : [{ value: u.role, label: u.role_display }, ...roles];
              return (
                <TR key={u.id}>
                  <TD>
                    <div className="flex flex-col">
                      <span className="flex items-center gap-2 font-medium text-ink-900">
                        {u.full_name || u.email}
                        {u.is_self && <Badge tone="neutral">You</Badge>}
                        {u.is_superuser && (
                          <Badge tone="info" title="Technical support and break-glass access">
                            <ShieldCheck className="h-3 w-3" />
                            Superadmin
                          </Badge>
                        )}
                      </span>
                      {u.full_name && <span className="text-xs text-ink-500">{u.email}</span>}
                    </div>
                  </TD>
                  <TD>
                    {canEdit && u.status !== "deactivated" ? (
                      <select
                        value={u.role}
                        onChange={(e) => void changeRole(u, e.target.value)}
                        disabled={update.isPending}
                        aria-label={`Role for ${u.full_name || u.email}`}
                        title={ROLE_HINTS[u.role]}
                        className="rounded-md bg-surface-raised hairline px-2 py-1.5 text-sm text-ink-900 focus:outline-none focus:ring-2 focus:ring-sage-500/40"
                      >
                        {roleChoices.map((r) => (
                          <option key={r.value} value={r.value}>{r.label}</option>
                        ))}
                      </select>
                    ) : (
                      <span className="text-sm text-ink-700" title={ROLE_HINTS[u.role]}>{u.role_display}</span>
                    )}
                  </TD>
                  <TD><StatusBadge user={u} /></TD>
                  <TD className="text-sm text-ink-500">{when(u.last_login)}</TD>
                  <TD>
                    <div className="flex justify-end gap-1.5">
                      {canEdit && u.status === "invited" && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => void run(u, "resend", `New invite sent to ${u.email}`)}
                          disabled={action.isPending}
                        >
                          <RotateCw className="h-3.5 w-3.5" />
                          Resend invite
                        </Button>
                      )}
                      {canEdit && u.status !== "deactivated" && (
                        <Button variant="ghost" size="sm" onClick={() => setSwitchingOff(u)}>
                          <Power className="h-3.5 w-3.5" />
                          Switch off
                        </Button>
                      )}
                      {canEdit && u.status === "deactivated" && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => void run(u, "reactivate", `${u.full_name || u.email} is switched back on`)}
                          disabled={action.isPending}
                        >
                          <Power className="h-3.5 w-3.5" />
                          Switch on
                        </Button>
                      )}
                    </div>
                  </TD>
                </TR>
              );
            })}
          </TBody>
        </Table>
      )}

      <p className="text-xs leading-relaxed text-ink-500">
        Switching an account off signs the person out straight away. Accounts are never deleted, so the activity
        log and the payments they recorded keep their name.
        {!meIsSuperuser && " Only the superadmin can add another owner/director."}
      </p>

      {inviting && <InviteModal roles={roles} onClose={() => setInviting(false)} />}
      {switchingOff && <SwitchOffModal user={switchingOff} onClose={() => setSwitchingOff(null)} />}
    </div>
  );
}
