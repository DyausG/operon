import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useNotifications } from "../state/notifications.jsx";
import { useEngineState } from "../state/engine.jsx";
import { ROUTES } from "../app/routes.js";
import { PageHeader, Segmented, FilterBar, Section, EmptyState, LoadingState } from "../components/index.jsx";
import { Btn, Dot, Icons, Tag } from "../primitives/index.jsx";
import { dateTime, ago, title } from "../lib/format.js";

const CATS = [{ value: "all", label: "All" }, { value: "unread", label: "Unread" }, { value: "critical", label: "Critical" }, { value: "approvals", label: "Approvals" }, { value: "maintenance", label: "Maintenance" }, { value: "agent", label: "Agent" }, { value: "connection", label: "Engine" }];

export function NotificationsPage() {
  const { state } = useEngineState();
  const { items, unread, markRead, markUnread, markAllRead } = useNotifications();
  const [cat, setCat] = useState("all");
  const shown = useMemo(() => items.filter((n) => cat === "all" || (cat === "unread" ? !n.read : n.category === cat)), [items, cat]);
  if (!state.frames && !state.fleet.length) return <div className="page"><div className="page-body"><LoadingState /></div></div>;
  const count = (c) => items.filter((n) => c === "all" || (c === "unread" ? !n.read : n.category === c)).length;
  return (
    <div className="page">
      <div className="page-body">
        <PageHeader eyebrow="Review" title="Notifications" meta={<><span>{items.length} from the engine stream this session</span><span>{unread} unread</span></>} actions={<><Btn small onClick={markAllRead} disabled={!unread}>{Icons.check({})} Mark all read</Btn><Link className="btn btn-small btn-quiet" to={`${ROUTES.settings}#notifications`}>{Icons.settings({})} Preferences</Link></>} />
        <FilterBar><Segmented ariaLabel="Category" value={cat} onChange={setCat} options={CATS.map((c) => ({ ...c, count: count(c.value) }))} /></FilterBar>
        <Section label="Inbox" flush>
          {shown.length ? shown.map((n) => (
            <div key={n.id} className={`ntf-row ${n.read ? "" : "is-unread"}`}>
              <Dot tone={n.tone === "normal" ? "normal" : n.tone} />
              <div className="ntf-text">
                <span className="ntf-title">{n.title}{n.action ? <Tag tone="warn" className="ntf-cat" style={{ marginLeft: 8 }}>needs action</Tag> : null}</span>
                <span className="ntf-body">{n.body}{n.incidentId ? <> · <Link className="inline-link mono" to={ROUTES.incident(n.incidentId)} onClick={() => markRead(n.id)}>{n.incidentId}</Link></> : n.machineId ? <> · <Link className="inline-link mono" to={ROUTES.machine(n.machineId)} onClick={() => markRead(n.id)}>{n.machineId}</Link></> : null}</span>
              </div>
              <span className="mono t4" title={dateTime(n.at)}>{ago(n.at)}</span>
              <div className="ntf-actions">
                <Tag className="ntf-cat">{title(n.category)}</Tag>
                <button type="button" className="btn btn-quiet btn-small" onClick={() => (n.read ? markUnread(n.id) : markRead(n.id))}>{n.read ? "Mark unread" : "Mark read"}</button>
              </div>
            </div>
          )) : <EmptyState compact title={items.length ? "Nothing in this category" : "No notifications yet"} body={items.length ? "" : "Notifications are derived from events the engine actually streamed to this browser: incident phase changes, approvals, execution, recovery, failures and engine control. Start the Guided Demo to see the lifecycle."} />}
        </Section>
        <p className="t4" style={{ fontSize: 11.5 }}>Read state is kept in this browser only. Notifications are not persisted server-side and disappear on reload; the Activity page holds the durable record.</p>
      </div>
    </div>
  );
}
