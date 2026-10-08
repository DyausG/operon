// F1.1 recovery and dispatch commands for the current case (F4.1, in Now). The interface offers only
// commands whose backend preconditions hold (lifecycle.availableCommands) and gates them by
// environment, declared role and connection; the backend still decides each one. Every command
// states its consequence before it is sent, needs a reason (except dispatch, which takes none and
// records no actor), and is bound to the case revision it was confirmed against: if the case
// changes, the person reviews the change first. Refusals keep their lead, a cleaned server reason
// and the HTTP status; a server body is never rendered as-is.
import { useEffect, useId, useRef, useState } from "react";
import { Button, InlineAlert, TextArea } from "../components/ui.jsx";
import { RATIONALE_MAX, actionGate, availableCommands, commandRequest, revisionOf } from "../model/lifecycle.js";
import { postJson } from "../model/refusal.js";
import { clock } from "../model/format.js";
import { DISPATCH_IS_NOT_WORK } from "../model/workBoundary.js";

const boundOf = (alert) => ({
  revision: revisionOf(alert),
  interventionId: alert?.lifecycle?.intervention_id || null,
  interventionHash: alert?.lifecycle?.intervention_hash || null,
});
const sameBound = (a, b) => a.revision === b.revision && a.interventionId === b.interventionId && a.interventionHash === b.interventionHash;

export function RecoveryActions({ c, session, role, connected, now, decisionPending = false, post = postJson }) {
  const commands = availableCommands(c.alert, { now });
  const gate = actionGate({ environment: c.environment, sessionRole: role?.id, connected });
  const [openId, setOpenId] = useState(null);
  const opened = useRef(null);
  const [, setRebound] = useState(0);
  const [rationale, setRationale] = useState("");
  const [touched, setTouched] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState(null);
  const [done, setDone] = useState(null);
  const [gone, setGone] = useState(null);
  const headId = useId(), reasonId = useId(), panelId = useId(), rationaleId = useId(), changeId = useId();

  const open = commands.find((x) => x.command === openId) || null;
  const current = boundOf(c.alert);
  const changed = !!open && !!opened.current && !sameBound(opened.current, current);
  const keys = commands.map((x) => x.command).join(",");

  // The case moved on while a confirmation was open and the command is no longer valid: close it.
  useEffect(() => {
    if (openId && !commands.some((x) => x.command === openId)) {
      setGone(openId);
      setOpenId(null);
    }
  }, [keys]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!commands.length) return null;
  const heading = decisionPending ? "Other actions on this case" : "Actions on this case";

  if (!gate.allowed) {
    return (
      <section className="wb-actions" aria-labelledby={headId}>
        <h3 className="wb-subhead" id={headId}>{heading}</h3>
        <p className="wb-secondary">{gate.reason}</p>
        <p className="wb-caption">Valid on this case now, for a permitted person: {commands.map((x) => x.label).join(" · ")}.</p>
      </section>
    );
  }

  const toggle = (cmd) => {
    setRefusal(null); setDone(null); setGone(null);
    if (openId === cmd.command) { setOpenId(null); return; }
    opened.current = boundOf(c.alert);
    setOpenId(cmd.command);
    setRationale(""); setTouched(false); setSubmitted(false);
  };

  const needsReason = open?.endpoint === "command";
  const text = rationale.trim();
  const level = (() => {
    if (!needsReason || !(touched || submitted)) return null;
    if (!text) return "error";
    if (text.length > RATIONALE_MAX) return "error";
    if (text.length < 10) return "warning";
    return null;
  })();
  const message = level === "error"
    ? (text ? `Keep the reason under ${RATIONALE_MAX.toLocaleString("en-GB")} characters (the backend’s limit).` : "A reason is required.")
    : level === "warning" ? "This reason is short. It will be recorded as written." : null;

  let block = null;
  if (gate.inactive) block = gate.inactive;
  else if (changed) block = "The case changed since you opened this. Review the change first.";

  const confirm = async () => {
    setRefusal(null);
    setSubmitted(true);
    if (needsReason && (!text || text.length > RATIONALE_MAX)) { document.getElementById(rationaleId)?.focus(); return; }
    if (block) return;
    const cmd = open;
    const req = commandRequest(c.incidentId, cmd, {
      actorId: session?.email || "declared-operator", actorRole: role?.id, rationale: text, bound: opened.current,
    });
    setBusy(true);
    const result = await post(req.url, req.body);
    setBusy(false);
    if (result?.ok) {
      setDone({ label: cmd.label, endpoint: cmd.endpoint, at: Date.now() });
      setOpenId(null);
    } else {
      setRefusal({ label: cmd.label, ...(result?.refusal || { status: null, lead: "The command was refused.", detail: null }) });
    }
  };

  return (
    <section className="wb-actions" aria-labelledby={headId}>
      <h3 className="wb-subhead" id={headId}>{heading}</h3>
      <div className="wb-actions-row">
        {commands.map((cmd) => (
          <Button key={cmd.command} variant={cmd.intent === "primary" ? "primary" : "secondary"} size="md"
            inactive={!!gate.inactive} reasonId={reasonId}
            aria-expanded={openId === cmd.command} aria-controls={openId === cmd.command ? panelId : undefined}
            onClick={() => toggle(cmd)}>
            {cmd.label}…
          </Button>
        ))}
      </div>
      {gate.inactive ? <p className="wb-secondary" id={reasonId}>{gate.inactive}</p> : null}

      {open ? (
        <div className="wb-confirm" id={panelId} role="group" aria-label={`Confirm: ${open.label}`}>
          <p>{open.consequence}</p>
          {open.endpoint === "execute" ? <p className="wb-secondary">{DISPATCH_IS_NOT_WORK}</p> : null}
          {changed ? (
            <div className="wb-decision-change" id={changeId} tabIndex={-1} role="alert">
              <p><strong>Changed since you opened this</strong> (R{opened.current.revision} → R{current.revision}). The command is sent against the revision you reviewed.</p>
              <Button variant="secondary" size="sm" onClick={() => { opened.current = boundOf(c.alert); setRebound((n) => n + 1); }}>I have reviewed the change</Button>
            </div>
          ) : null}
          {needsReason ? (
            <TextArea id={rationaleId} label="Reason" hint={`Required · recorded with ${gate.recordedAs}`} value={rationale}
              onChange={setRationale} onBlur={() => setTouched(true)} message={message} level={level} rows={2} />
          ) : (
            <p className="wb-caption">Dispatch takes no reason and records no actor in this build. It is bound to the exact approved work package <span className="wb-mono">{String(opened.current?.interventionHash || "").slice(0, 6)}</span>.</p>
          )}
          {block ? <p className="wb-sr" id={`${panelId}-why`}>{block}</p> : null}
          <div className="wb-confirm-controls">
            <Button variant={open.intent === "danger" ? "danger" : "primary"} size="md" inactive={!!block} reasonId={`${panelId}-why`}
              onBlocked={() => document.getElementById(changeId)?.focus()} busy={busy} busyLabel="Sending…" onClick={confirm}>
              {open.label}
            </Button>
            <Button variant="secondary" size="md" onClick={() => setOpenId(null)}>Go back</Button>
            {block ? <span className="wb-decision-reason" aria-hidden="true">{block}</span> : null}
          </div>
          <p className="wb-caption">Sent as <span className="wb-mono">{session?.email || "declared-operator"}</span>, {String(role?.label || "").toLowerCase()} · bound to R{opened.current?.revision ?? "?"}{open.endpoint === "command" ? <> · the server assigns the actor kind</> : null}</p>
        </div>
      ) : null}

      {refusal ? (
        <InlineAlert tone="critical" title={`The backend refused “${refusal.label}”`} role="alert">
          {refusal.lead}{refusal.detail ? <> Server reason: “{refusal.detail}”</> : null}{refusal.status ? <span className="wb-secondary"> (HTTP {refusal.status})</span> : null}
        </InlineAlert>
      ) : null}
      {done ? (
        <p className="wb-actions-done" role="status">
          {done.endpoint === "execute"
            ? <>The backend accepted the dispatch at {clock(done.at, { seconds: true })}. {DISPATCH_IS_NOT_WORK}</>
            : <>“{done.label}” accepted by the backend at {clock(done.at, { seconds: true })}. The case updates from the live stream.</>}
        </p>
      ) : null}
      {gone ? <p className="wb-secondary" role="status">That action is no longer valid: the case changed. The actions shown are the ones valid now.</p> : null}
    </section>
  );
}
