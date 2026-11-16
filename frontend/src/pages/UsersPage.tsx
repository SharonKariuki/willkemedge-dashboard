/**
 * Users - who can sign in, and what each person may do.
 *
 * Nobody signs themselves up. The owner (or the superadmin) invites a person
 * by email with a role; they receive a link to choose their own password.
 * From here the owner changes roles and switches accounts off, which signs
 * the person out at once. The API holds the rules; this page shows only the
 * controls the signed-in person may actually use.
 */
import { MailPlus, Power, RotateCw, ShieldCheck, SlidersHorizontal, UserPlus } from "lucide-react";
import { useMemo, useState } from "react";
import toast from "react-hot-toast";
import { useSearchParams } from "react-router-dom";

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
import { PermissionChecklist } from "@/features/users/PermissionChecklist";
import { type Changes, NO_CHANGES, type PermissionCatalog } from "@/features/users/permissions";
import { useAuth } from "@/hooks/useAuth";
import { useBuildings } from "@/hooks/useBuildings";
import {
  type AccessFields,
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
  caretaker: "Water readings and maintenance for the buildings you pick below. Sees no money.",
  auditor: "Reads the books and the activity log until the end date, and changes nothing.",
  viewer: "Can look at the books and properties but change nothing.",
};

const labelCls = "mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500";

const tomorrowIso = () => {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  // Local date, not toISOString(): that is UTC and lags a day just after midnight in Nairobi.
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

/** A role, the buildings (caretaker) or end date (auditor) it needs, and this person's own changes. */
interface AccessDraft {
  role: string;
  buildings: number[];
  endsOn: string;
  changes: Changes;
}

/** Why the draft can't be sent yet, mirroring the API's rules; null when it can.
 *  An end date already on the account and left alone (an audit that's over)
 *  may stay; a new one must be in the future. */
function accessProblem(d: AccessDraft, endsOnBefore = ""): string | null {
  if (!d.role) return "Pick a role.";
  if (d.role === "caretaker" && !d.buildings.length) return "Pick at least one building for the caretaker.";
  if (d.role === "auditor" && !d.endsOn) return "An auditor needs an end date.";
  if (d.endsOn && d.endsOn !== endsOnBefore && d.endsOn < tomorrowIso()) return "The end date must be in the future.";
  return null;
}

/** Only the fields that apply to the role go to the API. */
function accessPayload(d: AccessDraft): AccessFields {
  return {
    role: d.role,
    buildings: d.role === "caretaker" ? d.buildings : [],
    access_expires_on: d.endsOn || null,
    extra_capabilities: d.changes.added,
    removed_capabilities: d.changes.removed,
  };
}

function AccessFieldset({
  idPrefix,
  roles,
  catalog,
  draft,
  onChange,
  endsOnBefore = "",
  heldBefore = [],
  showPermissions = true,
}: {
  idPrefix: string;
  roles: RoleOption[];
  catalog: PermissionCatalog;
  draft: AccessDraft;
  onChange: (d: AccessDraft) => void;
  endsOnBefore?: string;
  heldBefore?: string[];
  /** Off for the superadmin, who can do everything whatever is ticked. */
  showPermissions?: boolean;
}) {
  const { data: buildings, isLoading } = useBuildings();
  const toggle = (id: number) =>
    onChange({
      ...draft,
      buildings: draft.buildings.includes(id) ? draft.buildings.filter((b) => b !== id) : [...draft.buildings, id],
    });

  return (
    <>
      <div>
        <label htmlFor={`${idPrefix}-role`} className={labelCls}>Role *</label>
        <select
          id={`${idPrefix}-role`}
          value={draft.role}
          // A new role starts from its own defaults; changes made against
          // the old one would mean something different here.
          onChange={(e) => onChange({ ...draft, role: e.target.value, changes: NO_CHANGES })}
          className={inputCls}
        >
          {roles.map((r) => (
            <option key={r.value} value={r.value}>{r.label}</option>
          ))}
        </select>
        {ROLE_HINTS[draft.role] && <p className="mt-1.5 text-xs text-ink-500">{ROLE_HINTS[draft.role]}</p>}
      </div>

      {draft.role === "caretaker" && (
        <fieldset>
          <legend className={labelCls}>Buildings they look after *</legend>
          {isLoading ? (
            <p className="text-xs text-ink-500">Loading buildings…</p>
          ) : (
            <div className="max-h-48 space-y-1 overflow-y-auto rounded-md hairline p-2">
              {(buildings ?? []).map((b) => (
                <label key={b.id} className="flex items-center gap-2 rounded px-1.5 py-1 text-sm text-ink-900 hover:bg-surface-raised">
                  <input
                    type="checkbox"
                    checked={draft.buildings.includes(b.id)}
                    onChange={() => toggle(b.id)}
                    className="h-4 w-4 accent-sage-600"
                  />
                  {b.name}
                </label>
              ))}
            </div>
          )}
        </fieldset>
      )}

      {showPermissions && catalog.permissions.length > 0 && (
        <PermissionChecklist
          idPrefix={idPrefix}
          catalog={catalog}
          role={draft.role}
          changes={draft.changes}
          heldBefore={heldBefore}
          onChange={(changes) => onChange({ ...draft, changes })}
        />
      )}

      <div>
        <label htmlFor={`${idPrefix}-ends`} className={labelCls}>
          Access ends on{draft.role === "auditor" ? " *" : " (optional)"}
        </label>
        <input
          id={`${idPrefix}-ends`}
          type="date"
          min={tomorrowIso()}
          value={draft.endsOn}
          onChange={(e) => onChange({ ...draft, endsOn: e.target.value })}
          className={inputCls}
          aria-describedby={`${idPrefix}-ends-hint`}
        />
        <p id={`${idPrefix}-ends-hint`} className="mt-1.5 text-xs text-ink-500">
          {draft.role === "auditor"
            ? "An audit is a visit: from this date they can't sign in, and an open session is stopped."
            : "For temporary staff. Leave empty for no end."}
        </p>
      </div>

      {draft.role && accessProblem(draft, endsOnBefore) && (
        <p role="status" className="text-xs text-orange-600">{accessProblem(draft, endsOnBefore)}</p>
      )}
    </>
  );
}

/** The labels behind someone's changes, for the list and its tooltip. */
function changeLabels(user: ManagedUser, catalog: PermissionCatalog): string {
  const label = (c: string) => catalog.permissions.find((p) => p.value === c)?.label ?? c;
  return [
    ...user.extra_capabilities.map((c) => `+ ${label(c)}`),
    ...user.removed_capabilities.map((c) => `− ${label(c)}`),
  ].join(", ");
}

function EditAccessModal({
  user, roles, catalog, onClose,
}: { user: ManagedUser; roles: RoleOption[]; catalog: PermissionCatalog; onClose: () => void }) {
  const update = useUpdateUser();
  const name = user.full_name || user.email;
  // An owner being edited by the superadmin keeps "owner" on the list.
  const choices = roles.some((r) => r.value === user.role)
    ? roles
    : [{ value: user.role, label: user.role_display }, ...roles];
  const endsOnBefore = user.access_expires_on ?? "";
  const [draft, setDraft] = useState<AccessDraft>({
    role: user.role,
    buildings: user.buildings.map((b) => b.id),
    endsOn: endsOnBefore,
    changes: { added: user.extra_capabilities, removed: user.removed_capabilities },
  });
  const problem = accessProblem(draft, endsOnBefore);

  const save = async () => {
    if (problem) return;
    try {
      await update.mutateAsync({ id: user.id, ...accessPayload(draft) });
      toast.success(`Access updated for ${name}`);
      onClose();
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not update access"));
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      eyebrow="Users"
      title={`Access for ${name}`}
      closeOnBackdrop={false}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={save} loading={update.isPending} disabled={Boolean(problem)} title={problem ?? undefined}>
            Save
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <AccessFieldset
          idPrefix="edit"
          roles={choices}
          catalog={catalog}
          draft={draft}
          onChange={setDraft}
          endsOnBefore={endsOnBefore}
          heldBefore={user.role === draft.role ? user.extra_capabilities : []}
          showPermissions={!user.is_superuser}
        />
        {user.is_superuser && (
          <p className="text-xs text-ink-500">The superadmin can do everything, whatever the role says.</p>
        )}
        <p className="text-[11px] leading-relaxed text-ink-500">
          Changes apply on their next click - nobody needs to sign out and back in.
        </p>
      </div>
    </Modal>
  );
}

/** "Block A, Block B" for a caretaker; "until 31 Dec 2026" for a dated account. */
function AccessSummary({ user, catalog }: { user: ManagedUser; catalog: PermissionCatalog }) {
  const parts: string[] = [];
  const changes = user.extra_capabilities.length + user.removed_capabilities.length;
  const changeBadge = changes > 0 && !user.is_superuser && (
    <span
      className="ml-1.5 rounded bg-teal-600/10 px-1.5 py-0.5 text-[10px] font-semibold text-teal-700"
      title={changeLabels(user, catalog)}
    >
      {[
        user.extra_capabilities.length ? `+${user.extra_capabilities.length}` : "",
        user.removed_capabilities.length ? `−${user.removed_capabilities.length}` : "",
      ].filter(Boolean).join(" ")}
      <span className="sr-only"> changes: {changeLabels(user, catalog)}</span>
    </span>
  );
  if (user.role === "caretaker") {
    parts.push(user.buildings.length ? user.buildings.map((b) => b.name).join(", ") : "No buildings yet");
  }
  if (user.access_expires_on) {
    const end = new Date(`${user.access_expires_on}T00:00:00`).toLocaleDateString("en-GB", {
      day: "2-digit", month: "short", year: "numeric",
    });
    parts.push(`ends ${end}`);
  }
  return (
    <>
      {changeBadge}
      {parts.length > 0 && <span className="mt-0.5 block text-xs text-ink-500">{parts.join(" · ")}</span>}
    </>
  );
}

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
  if (user.status === "expired") return <Badge tone="vacant" withDot>Access ended</Badge>;
  return <Badge tone="paid" withDot>Active</Badge>;
}

/** The invite is saved either way; say plainly when its email didn't go, and why. */
function reportEmail(emailError: string | null | undefined, sent: string) {
  if (!emailError) {
    toast.success(sent);
    return;
  }
  toast.error(
    `The invite is saved, but the email didn't send: ${emailError}. Fix that, then use Resend invite.`,
    { duration: 15000 },
  );
}

/** Whether the signed-in person may change this account (mirrors the API's rule). */
function editable(user: ManagedUser, meIsSuperuser: boolean): boolean {
  if (user.is_self) return false;
  if (meIsSuperuser) return true;
  return !user.is_superuser && user.role !== "owner";
}

function InviteModal({
  roles, catalog, onClose,
}: { roles: RoleOption[]; catalog: PermissionCatalog; onClose: () => void }) {
  const invite = useInviteUser();
  const [email, setEmail] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [draft, setDraft] = useState<AccessDraft>({
    role: roles.find((r) => r.value === "viewer")?.value ?? roles[0]?.value ?? "",
    buildings: [],
    endsOn: "",
    changes: NO_CHANGES,
  });
  const problem = accessProblem(draft);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (problem) return;
    try {
      const saved = await invite.mutateAsync({
        email: email.trim(), first_name: firstName, last_name: lastName, ...accessPayload(draft),
      });
      reportEmail(saved.email_error, `Invite sent to ${email.trim()}`);
      onClose();
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not send the invite"));
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      eyebrow="Users"
      title="Invite someone"
      closeOnBackdrop={false}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button
            type="submit"
            form="invite-form"
            loading={invite.isPending}
            disabled={!email.trim() || Boolean(problem)}
            title={problem ?? undefined}
          >
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
        <AccessFieldset idPrefix="invite" roles={roles} catalog={catalog} draft={draft} onChange={setDraft} />
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
  const action = useUserAction();
  const [inviting, setInviting] = useState(false);
  const [editing, setEditing] = useState<ManagedUser | null>(null);
  const [switchingOff, setSwitchingOff] = useState<ManagedUser | null>(null);

  const meIsSuperuser = Boolean(me?.is_superuser);
  const roles = data?.assignable_roles ?? [];
  const catalog = useMemo<PermissionCatalog>(() => ({
    permissions: data?.permissions ?? [],
    roleCapabilities: data?.role_capabilities ?? {},
    scopedRoles: data?.scoped_roles ?? [],
  }), [data]);

  // Quick actions → "Invite user" lands here with ?invite=1.
  const [params, setParams] = useSearchParams();
  const inviteOpen = inviting || (params.get("invite") === "1" && roles.length > 0);
  const closeInvite = () => {
    setInviting(false);
    if (params.has("invite")) {
      setParams((p) => { p.delete("invite"); return p; }, { replace: true });
    }
  };

  const run = async (user: ManagedUser, act: "resend" | "reactivate", done: string) => {
    try {
      const saved = await action.mutateAsync({ id: user.id, action: act });
      reportEmail(saved.email_error, done);
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
                    <span className="text-sm text-ink-700" title={ROLE_HINTS[u.role]}>{u.role_display}</span>
                    <AccessSummary user={u} catalog={catalog} />
                  </TD>
                  <TD><StatusBadge user={u} /></TD>
                  <TD className="text-sm text-ink-500">{when(u.last_login)}</TD>
                  <TD>
                    <div className="flex justify-end gap-1.5">
                      {canEdit && u.status !== "deactivated" && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setEditing(u)}
                          aria-label={`Change access for ${u.full_name || u.email}`}
                        >
                          <SlidersHorizontal className="h-3.5 w-3.5" />
                          Access
                        </Button>
                      )}
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

      {inviteOpen && <InviteModal roles={roles} catalog={catalog} onClose={closeInvite} />}
      {editing && <EditAccessModal user={editing} roles={roles} catalog={catalog} onClose={() => setEditing(null)} />}
      {switchingOff && <SwitchOffModal user={switchingOff} onClose={() => setSwitchingOff(null)} />}
    </div>
  );
}
