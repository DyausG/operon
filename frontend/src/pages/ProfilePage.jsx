import { useState } from "react";
import { useSession, initialsOf, ROLES } from "../state/session.jsx";
import { useEngineState } from "../state/engine.jsx";
import { useTheme } from "../state/theme.jsx";
import { PageHeader, Section, Field, Input, Select, Toggle } from "../components/index.jsx";
import { Btn, Icons, Tag, KV } from "../primitives/index.jsx";
import { dateTime, title } from "../lib/format.js";

export function ProfilePage() {
  const { session, update, signOut } = useSession();
  const { state } = useEngineState();
  const { mode } = useTheme();
  const [form, setForm] = useState({ name: session?.name || "", role: session?.role || "maintenance_approver" });
  const [saved, setSaved] = useState(false);
  const dirty = form.name !== session?.name || form.role !== session?.role;
  const save = (e) => { e.preventDefault(); if (!form.name.trim()) return; update({ name: form.name.trim(), role: form.role }); setSaved(true); setTimeout(() => setSaved(false), 1600); };
  return (
    <div className="page">
      <div className="page-body">
        <PageHeader eyebrow="Account" title="Profile" />
        <div className="grid-main">
          <div className="stack">
            <Section label="Identity">
              <div className="profile-head">
                <span className="avatar avatar-xl">{initialsOf(session?.name)}</span>
                <div className="profile-id">
                  <span className="profile-name">{session?.name}</span>
                  <span className="t3">{session?.email}</span>
                  <div className="pill-row"><Tag>{ROLES.find((r) => r.id === session?.role)?.label || title(session?.role || "")}</Tag><Tag tone="adv" dashed>Demo session</Tag></div>
                </div>
              </div>
              <form className="stack" onSubmit={save}>
                <div className="form-grid">
                  <Field label="Display name" hint="Shown in the user menu and recorded nowhere else."><Input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} required /></Field>
                  <Field label="Role" hint="Presentation only. The engine records approvals under the dashboard operator identity until authentication exists."><Select value={form.role} onChange={(v) => setForm((f) => ({ ...f, role: v }))} options={ROLES.map((r) => ({ value: r.id, label: r.label }))} /></Field>
                </div>
                <div className="row-wrap"><Btn primary type="submit" disabled={!dirty || !form.name.trim()}>{saved ? "Saved" : "Save changes"}</Btn><Btn quiet type="button" onClick={() => setForm({ name: session?.name || "", role: session?.role || "" })} disabled={!dirty}>Reset</Btn></div>
              </form>
            </Section>
            <Section label="Organisation & site" flush>
              <div className="kvgrid kvgrid-2">
                <KV label="Plant" value={state.meta.plant || null} /><KV label="Application" value={`${state.meta.appName || "Operon"} · ${state.meta.tagline || ""}`} />
                <KV label="Authority path" mono value={state.authorityPath || null} /><KV label="Reasoning backend" mono value={state.reasoningProvenance?.backend || null} />
              </div>
            </Section>
          </div>
          <div className="stack">
            <Section label="Account" flush>
              <div className="kvgrid kvgrid-2">
                <KV label="Email" mono value={session?.email} /><KV label="Signed in" mono value={dateTime(session?.signedInAt)} />
                <KV label="Session storage" value={session?.remember ? "Persistent (remember me)" : "This tab only"} /><KV label="Theme preference" value={title(mode)} />
              </div>
            </Section>
            <Section label="Where this is stored">
              <div className="note-box">{Icons.info({})}<span>Profile fields are kept in this browser's storage under the Operon session. No backend endpoint stores operator profiles yet; when one exists this page should write through the same session provider.</span></div>
              <Btn onClick={signOut}>{Icons.logout({})} Sign out</Btn>
            </Section>
          </div>
        </div>
      </div>
    </div>
  );
}
