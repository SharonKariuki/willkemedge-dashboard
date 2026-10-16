import { ChevronDown, ChevronRight, History, Lock, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  Badge,
  Button,
  Card,
  DatePicker,
  EmptyState,
  ErrorState,
  Input,
  PageHeader,
  Skeleton,
  Switch,
} from "@/components/ui";
import { useActivity, type ActivityFilters } from "@/hooks/useActivity";
import { useAuth } from "@/hooks/useAuth";
import {
  SOURCE_LABELS,
  changedFields,
  dayHeading,
  describeDevice,
  groupActivity,
  timeOfDay,
  whoDidIt,
  type ActivityGroup,
  type ActivityRow,
  type ActivitySource,
} from "@/lib/activity";

const selectCls =
  "w-full rounded-md border border-border bg-surface px-3 py-2.5 text-sm text-content focus:border-teal-600 focus:outline-none focus:ring-2 focus:ring-ring/25";
const labelCls = "mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500";

function KindBadge({ group }: { group: ActivityGroup }) {
  const { head } = group;
  if (head.kind === "denied") return <Badge tone="unpaid">Refused</Badge>;
  if (head.action === "auth.login_failed" || head.action === "auth.locked_out") {
    return <Badge tone="partial">Failed sign-in</Badge>;
  }
  if (head.kind === "auth") return <Badge tone="neutral">Sign-in</Badge>;
  if (group.isFinancial) return <Badge tone="coral">Money</Badge>;
  return null;
}

function Diff({ row }: { row: ActivityRow }) {
  const fields = changedFields(row);
  if (!fields.length) return null;
  return (
    <dl className="mt-1.5 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-xs">
      {fields.map((f) => (
        <div key={f.field} className="contents">
          <dt className="capitalize text-ink-500">{f.field}</dt>
          <dd className="min-w-0 break-words text-ink-700">
            <span className="text-ink-400 line-through">{f.before}</span> → {f.after}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Entry({ group }: { group: ActivityGroup }) {
  const [open, setOpen] = useState(false);
  const { head, details } = group;
  const device = describeDevice(head.user_agent);
  const meta = [
    whoDidIt(head),
    SOURCE_LABELS[head.source] ?? head.source,
    device,
    head.ip_address,
  ].filter(Boolean);
  const expandable = details.length > 0 || changedFields(head).length > 0;

  return (
    <li className="flex gap-3 py-3.5 sm:gap-4">
      <span className="w-11 shrink-0 pt-0.5 text-sm tabular-nums text-ink-500">
        {timeOfDay(head.created_at)}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-start gap-x-2 gap-y-1">
          <p className="min-w-0 break-words text-sm font-medium text-ink-900">{head.summary}</p>
          <KindBadge group={group} />
        </div>
        <p className="mt-0.5 break-words text-xs text-ink-500">{meta.join(" · ")}</p>

        {expandable && (
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            className="mt-1.5 inline-flex items-center gap-1 text-xs font-medium text-teal-700 hover:text-teal-800 dark:text-teal-500"
          >
            {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            {open ? "Hide details" : details.length ? `Details (${details.length + 1})` : "Details"}
          </button>
        )}

        {open && (
          <div className="mt-2 space-y-2.5 rounded-md bg-surface-sunk px-3 py-2.5">
            <Diff row={head} />
            {details.map((row) => (
              <div key={row.id}>
                <p className="break-words text-xs text-ink-700">{row.summary}</p>
                <Diff row={row} />
              </div>
            ))}
            {head.session_id && (
              <p className="text-[11px] text-ink-400">Sign-in session {head.session_id.slice(0, 8)}</p>
            )}
          </div>
        )}
      </div>
    </li>
  );
}

/** Groups split into days, in the order they arrive (newest first). */
function byDay(groups: ActivityGroup[]): { day: string; groups: ActivityGroup[] }[] {
  const days: { day: string; groups: ActivityGroup[] }[] = [];
  for (const g of groups) {
    const day = dayHeading(g.head.created_at);
    const last = days[days.length - 1];
    if (last?.day === day) last.groups.push(g);
    else days.push({ day, groups: [g] });
  }
  return days;
}

export default function ActivityPage() {
  const { user } = useAuth();
  const [filters, setFilters] = useState<ActivityFilters>({});
  const [search, setSearch] = useState("");

  // Search as the director types, without a request per keystroke.
  useEffect(() => {
    const t = window.setTimeout(() => {
      setFilters((f) => (f.q === search.trim() ? f : { ...f, q: search.trim() }));
    }, 300);
    return () => window.clearTimeout(t);
  }, [search]);

  const isOwner = Boolean(user?.can_forgive_money);
  const { data, isLoading, isError, refetch, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useActivity(filters, isOwner);

  const people = data?.pages[0]?.people ?? [];
  const days = useMemo(
    () => byDay(groupActivity(data?.pages.flatMap((p) => p.results) ?? [])),
    [data],
  );

  const set = (patch: Partial<ActivityFilters>) => setFilters((f) => ({ ...f, ...patch }));
  const filtered = Boolean(
    filters.actor || filters.source || filters.financial || filters.date_from || filters.date_to || filters.q,
  );

  if (!isOwner) {
    return (
      <div className="space-y-6">
        <PageHeader eyebrow="Oversight" title="Activity" />
        <Card>
          <EmptyState
            icon={<Lock className="h-5 w-5" />}
            title="Only the director can see the activity log."
            description="It records what every member of staff does in the system, so it is kept to the owner's account."
          />
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Oversight"
        title="Activity"
        description="Everything done in the system: who did it, when, and from which device. Nothing here can be edited or deleted. Only you can see this page."
      />

      <Card padding="sm">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <div className="min-w-0 sm:col-span-2 lg:col-span-1">
            <label htmlFor="activity-search" className={labelCls}>Search</label>
            <Input
              id="activity-search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Unit, tenant, person…"
              leftIcon={<Search className="h-4 w-4" />}
            />
          </div>
          <div className="min-w-0">
            <label htmlFor="activity-person" className={labelCls}>Person</label>
            <select
              id="activity-person"
              value={filters.actor ?? ""}
              onChange={(e) => set({ actor: e.target.value || undefined })}
              className={selectCls}
            >
              <option value="">Everyone</option>
              {people.map((p) => (
                <option key={p.id} value={String(p.id)}>
                  {p.label} ({p.role})
                </option>
              ))}
              <option value="system">System (no one signed in)</option>
            </select>
          </div>
          <div className="min-w-0">
            <label htmlFor="activity-source" className={labelCls}>Done through</label>
            <select
              id="activity-source"
              value={filters.source ?? ""}
              onChange={(e) => set({ source: (e.target.value || "") as ActivitySource | "" })}
              className={selectCls}
            >
              <option value="">Anywhere</option>
              {(Object.keys(SOURCE_LABELS) as ActivitySource[]).map((s) => (
                <option key={s} value={s}>{SOURCE_LABELS[s]}</option>
              ))}
            </select>
          </div>
          <DatePicker
            label="From"
            value={filters.date_from ?? ""}
            onChange={(e) => set({ date_from: e.target.value || undefined })}
            wrapperClassName="min-w-0"
          />
          <DatePicker
            label="To"
            value={filters.date_to ?? ""}
            onChange={(e) => set({ date_to: e.target.value || undefined })}
            wrapperClassName="min-w-0"
          />
          <div className="flex min-w-0 items-end gap-3 pb-2">
            <Switch
              id="activity-money"
              checked={Boolean(filters.financial)}
              onChange={(v) => set({ financial: v || undefined })}
              label="Money only"
            />
            <label htmlFor="activity-money" className="text-sm text-ink-700">Money only</label>
            {filtered && (
              <Button
                variant="ghost"
                size="sm"
                className="ml-auto"
                onClick={() => {
                  setSearch("");
                  setFilters({});
                }}
              >
                Clear
              </Button>
            )}
          </div>
        </div>
      </Card>

      <Card padding="sm">
        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        ) : isError ? (
          <ErrorState
            title="The activity log could not be loaded."
            onRetry={() => void refetch()}
          />
        ) : !days.length ? (
          <EmptyState
            icon={<History className="h-5 w-5" />}
            title={filtered ? "Nothing matches these filters" : "Nothing recorded yet"}
            description={
              filtered
                ? "Try a wider date range, or clear the filters."
                : "Actions appear here as soon as anyone signs in and changes something."
            }
          />
        ) : (
          <div className="space-y-5">
            {days.map(({ day, groups }) => (
              <section key={day}>
                <h2 className="border-b border-border pb-2 text-xs font-semibold uppercase tracking-wider text-ink-500">
                  {day}
                </h2>
                <ul className="divide-y divide-border">
                  {groups.map((g) => (
                    <Entry key={g.key} group={g} />
                  ))}
                </ul>
              </section>
            ))}
            {hasNextPage && (
              <div className="flex justify-center pt-2">
                <Button variant="outline" onClick={() => void fetchNextPage()} disabled={isFetchingNextPage}>
                  {isFetchingNextPage ? "Loading…" : "Show older"}
                </Button>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
