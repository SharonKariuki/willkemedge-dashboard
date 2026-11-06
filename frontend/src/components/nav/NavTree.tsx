import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";

import { cn } from "@/lib/cn";
import { linkHref, navItem, type NavNode } from "@/lib/nav";

type LinkNode = Extract<NavNode, { kind: "link" }>;
type GroupNode = Extract<NavNode, { kind: "group" }>;

export interface NavTreeProps {
  nodes: NavNode[];
  /** Ids from useNavTree: the active link last, the groups above it first. */
  active: string[];
  isOpen: (id: string) => boolean;
  onToggle: (id: string) => void;
  /** Called after a link is chosen (the phone drawer closes itself). */
  onNavigate?: () => void;
  /** 44px rows for touch (the phone drawer). */
  touch?: boolean;
  /** Keeps element ids unique: the sidebar and the drawer are both mounted. */
  idPrefix: string;
}

/**
 * The menu tree on the navy sidebar surface. Top-level rows carry an 18px icon;
 * the rows inside a group hang off a hairline guide under the group's icon, so
 * the hierarchy reads without deep indentation. Accounting's third level sits
 * on a second guide under its own headings.
 */
export default function NavTree(props: NavTreeProps) {
  return (
    <ul className="flex flex-col gap-0.5">
      {props.nodes.map((n) => (
        <Node key={n.id} node={n} depth={0} {...props} />
      ))}
    </ul>
  );
}

interface NodeProps extends NavTreeProps {
  node: NavNode;
  depth: number;
}

function Node({ node, depth, ...props }: NodeProps) {
  if (node.kind === "link") return <LinkRow node={node} depth={depth} {...props} />;
  if (node.kind === "group") return <GroupRow node={node} depth={depth} {...props} />;
  return (
    <li className="pt-2 first:pt-0.5">
      <p className="px-2.5 pb-1 pt-1 text-[10.5px] font-semibold uppercase tracking-[0.1em] text-white/35">
        {node.label}
      </p>
      <ul className="flex flex-col gap-0.5" aria-label={node.label}>
        {node.children.map((c) => (
          <Node key={c.id} node={c} depth={depth} {...props} />
        ))}
      </ul>
    </li>
  );
}

const rowBase =
  "group relative flex w-full items-center rounded-lg text-left outline-none transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-teal-500/70";

function LinkRow({ node, depth, active, onNavigate, touch }: NodeProps & { node: LinkNode }) {
  const item = navItem(node.page);
  const label = node.label ?? item.label;
  // Pages carry their icon; Accounting's statements are plain text rows.
  const Icon = node.icon ?? (node.tab ? undefined : item.icon);
  const current = active[active.length - 1] === node.id;
  const top = depth === 0;

  return (
    <li>
      <Link
        to={linkHref(node)}
        onClick={onNavigate}
        aria-current={current ? "page" : undefined}
        className={cn(
          rowBase,
          top ? "gap-3 px-2.5 text-[13.5px] font-medium" : "gap-2.5 px-2.5 text-[13px]",
          touch ? "min-h-[44px]" : top ? "h-9" : "h-8",
          current
            ? "bg-white/[0.09] text-white"
            : top
            ? "text-white/70 hover:bg-white/[0.05] hover:text-white"
            : "text-white/60 hover:bg-white/[0.05] hover:text-white",
          current && !top && "font-medium"
        )}
      >
        {/* Inside a group the marker sits on the guide line itself */}
        {current && !top && (
          <span aria-hidden className="absolute -left-[11px] top-1/2 h-4 w-[2px] -translate-y-1/2 rounded-full bg-teal-500" />
        )}
        {Icon && (
          <Icon
            aria-hidden
            className={cn(
              "shrink-0 transition-colors",
              top ? "h-[18px] w-[18px]" : "h-4 w-4",
              current ? "text-teal-500" : "text-white/45 group-hover:text-white/75"
            )}
          />
        )}
        <span className="truncate">{label}</span>
      </Link>
    </li>
  );
}

function GroupRow({ node, depth, ...props }: NodeProps & { node: GroupNode }) {
  const { active, isOpen, onToggle, touch, idPrefix } = props;
  const open = isOpen(node.id);
  const holdsActive = active.includes(node.id);
  const top = depth === 0;
  const Icon = node.icon;
  const listId = `${idPrefix}-${node.id}`;

  return (
    <li>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => onToggle(node.id)}
        className={cn(
          rowBase,
          top ? "gap-3 px-2.5 text-[13.5px] font-medium" : "gap-2.5 px-2.5 text-[13px]",
          touch ? "min-h-[44px]" : top ? "h-9" : "h-8",
          holdsActive ? "text-white" : top ? "text-white/70" : "text-white/60",
          "hover:bg-white/[0.05] hover:text-white"
        )}
      >
        <Icon
          aria-hidden
          className={cn(
            "shrink-0 transition-colors",
            top ? "h-[18px] w-[18px]" : "h-4 w-4",
            holdsActive ? "text-white/90" : "text-white/45 group-hover:text-white/75"
          )}
        />
        <span className="flex-1 truncate">{node.label}</span>
        {/* Folded away, the group still says it holds the page on screen */}
        {holdsActive && !open && <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-teal-500" />}
        <ChevronRight
          aria-hidden
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-white/35 transition-transform duration-200 ease-out motion-reduce:transition-none group-hover:text-white/60",
            open && "rotate-90"
          )}
        />
      </button>

      {/* Height animates through grid rows (0fr → 1fr); folded rows are inert
          so Tab never lands on a link you cannot see. */}
      <div
        id={listId}
        className={cn(
          // visibility flips at the end of the fold, so the rows fade out first.
          "grid transition-[grid-template-rows,opacity,visibility] duration-200 ease-out motion-reduce:transition-none",
          open ? "visible grid-rows-[1fr] opacity-100" : "invisible grid-rows-[0fr] opacity-0"
        )}
        {...(open ? {} : { inert: "" })}
      >
        <div className="min-h-0 overflow-hidden">
          <ul
            aria-label={node.label}
            className={cn(
              "flex flex-col gap-0.5 border-l border-white/[0.09] py-1 pl-2.5",
              // The guide hangs from the centre of the group's icon.
              top ? "ml-[19px]" : "ml-[17px]"
            )}
          >
            {node.children.map((c) => (
              <Node key={c.id} node={c} depth={depth + 1} {...props} />
            ))}
          </ul>
        </div>
      </div>
    </li>
  );
}
