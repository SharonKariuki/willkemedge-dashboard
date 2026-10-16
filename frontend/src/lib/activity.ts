/**
 * activity.ts — shaping the audit log for the director's Activity page.
 *
 * The API returns one row per thing written, newest first. One click often
 * writes several: voiding a payment records the named action *and* the field
 * changes on the payment underneath it. Rows from the same request share a
 * `request_id`, and are shown as one entry with the rest folded under it.
 */

export type ActivityKind = "event" | "change" | "auth" | "denied";
export type ActivitySource = "web" | "admin" | "bank" | "cron" | "command" | "system";

export interface ActivityRow {
  id: number;
  created_at: string;
  kind: ActivityKind;
  action: string;
  summary: string;
  object_type: string;
  object_id: number | null;
  object_label: string;
  old_values: Record<string, unknown>;
  new_values: Record<string, unknown>;
  is_financial: boolean;
  actor: number | null;
  actor_label: string;
  actor_role: string;
  source: ActivitySource;
  source_detail: string;
  ip_address: string | null;
  user_agent: string;
  session_id: string;
  request_id: string;
}

export interface ActivityGroup {
  key: string;
  /** The row the entry is headed by: the named action if the request had one. */
  head: ActivityRow;
  /** Everything else the same request wrote, newest first. */
  details: ActivityRow[];
  isFinancial: boolean;
}

/** Fold consecutive rows that share a request into one entry. */
export function groupActivity(rows: ActivityRow[]): ActivityGroup[] {
  const groups: ActivityRow[][] = [];
  for (const row of rows) {
    const last = groups[groups.length - 1];
    if (last && row.request_id && last[0].request_id === row.request_id) {
      last.push(row);
    } else {
      groups.push([row]);
    }
  }
  return groups.map((members) => {
    const head = members.find((r) => r.kind !== "change") ?? members[0];
    return {
      key: String(members[0].id),
      head,
      details: members.filter((r) => r !== head),
      isFinancial: members.some((r) => r.is_financial),
    };
  });
}

export const SOURCE_LABELS: Record<ActivitySource, string> = {
  web: "Dashboard",
  admin: "Admin site",
  bank: "Bank notification",
  cron: "Scheduled job",
  command: "Server command",
  system: "System",
};

const ROLE_LABELS: Record<string, string> = {
  owner: "Owner",
  accountant: "Accountant",
  caretaker: "Caretaker",
  viewer: "Viewer",
};

/** Who did it, as a person reads it: "Grace (Accountant)", or what the system was doing. */
export function whoDidIt(row: ActivityRow): string {
  if (row.actor_label) {
    const role = ROLE_LABELS[row.actor_role];
    return role ? `${row.actor_label} (${role})` : row.actor_label;
  }
  if (row.source === "command" && row.source_detail) return `Server command: ${row.source_detail}`;
  if (row.source === "cron" && row.source_detail) return `Scheduled job: ${row.source_detail}`;
  if (row.source === "bank") return "Bank notification";
  if (row.kind === "auth") return row.object_label || "Unknown";
  return "System";
}

/** "Chrome on Android" from a user-agent string; "" when there is nothing to read. */
export function describeDevice(ua: string): string {
  if (!ua) return "";
  const browser =
    /Edg\//.test(ua) ? "Edge"
    : /OPR\/|Opera/.test(ua) ? "Opera"
    : /Firefox\//.test(ua) ? "Firefox"
    : /Chrome\//.test(ua) ? "Chrome"
    : /Safari\//.test(ua) ? "Safari"
    : "";
  const os =
    /Android/.test(ua) ? "Android"
    : /iPhone|iPad/.test(ua) ? "iPhone"
    : /Windows/.test(ua) ? "Windows"
    : /Mac OS X|Macintosh/.test(ua) ? "Mac"
    : /Linux/.test(ua) ? "Linux"
    : "";
  if (browser && os) return `${browser} on ${os}`;
  return browser || os || "";
}

const NAIROBI = "Africa/Nairobi";

/** "Monday, 28 September 2026", in Nairobi time whatever the browser's zone. */
export function dayHeading(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    timeZone: NAIROBI, weekday: "long", day: "numeric", month: "long", year: "numeric",
  });
}

/** "14:05", Nairobi time. */
export function timeOfDay(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", {
    timeZone: NAIROBI, hour: "2-digit", minute: "2-digit",
  });
}

/** Field-by-field before → after for a row that has both, skipping hidden values. */
export function changedFields(row: ActivityRow): { field: string; before: string; after: string }[] {
  const keys = Object.keys(row.new_values).filter((k) => k in row.old_values);
  const text = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : String(v));
  return keys.map((k) => ({
    field: k.replace(/_id$/, "").replace(/_/g, " "),
    before: text(row.old_values[k]),
    after: text(row.new_values[k]),
  }));
}
