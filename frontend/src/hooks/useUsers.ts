import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export type UserStatus = "active" | "invited" | "deactivated" | "expired";

export interface BuildingRef {
  id: number;
  name: string;
}

export interface ManagedUser {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  full_name: string;
  role: string;
  role_display: string;
  status: UserStatus;
  is_superuser: boolean;
  last_login: string | null;
  date_joined: string;
  invited_at: string | null;
  invited_by_email: string | null;
  invite_expires_at: string | null;
  deactivated_at: string | null;
  is_self: boolean;
  /** Caretakers only: the buildings they look after. */
  buildings: BuildingRef[];
  /** Access ends at the start of this day (ISO date); required for an auditor. */
  access_expires_on: string | null;
  /** This person's own changes to their role. */
  extra_capabilities: string[];
  removed_capabilities: string[];
  /** What they can actually do, changes applied. */
  capabilities: string[];
}

/** Who looks after what, and until when - sent with an invite or an edit. */
export interface AccessFields {
  role: string;
  buildings?: number[];
  access_expires_on?: string | null;
  extra_capabilities?: string[];
  removed_capabilities?: string[];
}

/** One line of the permission checklist, as the API will judge it. */
export interface PermissionOption {
  value: string;
  area: string;
  label: string;
  hint: string;
  /** Needs these on as well. */
  requires: string[];
  /** Whether the signed-in person may give it to someone whose role lacks it. */
  grantable: boolean;
}

export interface RoleOption {
  value: string;
  label: string;
}

interface UsersResponse {
  users: ManagedUser[];
  /** The roles the signed-in person may give - the owner can't make another owner. */
  assignable_roles: RoleOption[];
  permissions: PermissionOption[];
  /** What each role includes before anyone's own changes. */
  role_capabilities: Record<string, string[]>;
  /** Roles limited to their buildings: their permissions can only be taken away. */
  scoped_roles: string[];
}

export function useUsers() {
  return useQuery<UsersResponse>({
    queryKey: ["users"],
    queryFn: async () => (await api.get("/auth/users/")).data,
  });
}

function useUserMutation<TVars>(fn: (vars: TVars) => Promise<ManagedUser>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export interface InvitePayload extends AccessFields {
  email: string;
  first_name?: string;
  last_name?: string;
}

export const useInviteUser = () =>
  useUserMutation(async (payload: InvitePayload) => (await api.post("/auth/users/", payload)).data);

export type UpdatePayload = { id: number; first_name?: string; last_name?: string } & Partial<AccessFields>;

export const useUpdateUser = () =>
  useUserMutation(async ({ id, ...patch }: UpdatePayload) =>
    (await api.patch(`/auth/users/${id}/`, patch)).data);

export type UserAction = "resend" | "deactivate" | "reactivate";

export const useUserAction = () =>
  useUserMutation(async ({ id, action }: { id: number; action: UserAction }) =>
    (await api.post(`/auth/users/${id}/${action}/`)).data);

/** Public: who an invite link is for. 404 when it is used, expired or switched off. */
export interface InviteDetails {
  email: string;
  first_name: string;
  role_display: string;
  expires_at: string;
}

export function useInvite(token: string | undefined) {
  return useQuery<InviteDetails>({
    queryKey: ["invite", token],
    queryFn: async () => (await api.get(`/auth/invite/${token}/`)).data,
    enabled: Boolean(token),
    retry: false,
  });
}
