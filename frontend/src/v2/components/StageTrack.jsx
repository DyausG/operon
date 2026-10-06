// Stage track (07 §13.2): a lifecycle position display, never a stepper (R-22). Not clickable,
// doesn't navigate, never advances anything. One 1 px line through eight square nodes with a
// hold-point bar before "Awaiting decision" (the governed human gate).
import { STAGES, stageOf } from "../model/status.js";

export function StageTrack({ phase, inspectionLoops = 0 }) {
  const current = stageOf(phase);
  const exception = current?.exception ? current : null;
  // Exceptions sit below the stage where they occurred; approximate with the last reached stage.
  const pos = exception ? null : current?.n ?? null;
  const caption = current
    ? `${current.label}${current.n ? ` · ${current.n} of 8` : ""}`
    : "Stage not reported";
  return (
    <div className="wb-track" role="group" aria-label="Case lifecycle position">
      <ol className="wb-track-list">
        {STAGES.map((s) => {
          const state = pos == null ? "future" : s.n < pos ? "done" : s.n === pos ? "current" : "future";
          return (
            <li key={s.key} className={`wb-track-stage is-${state} ${s.key === "AWAITING_DECISION" ? "has-hold" : ""}`}
              aria-current={state === "current" ? "step" : undefined}>
              {s.key === "AWAITING_DECISION" ? (
                <span className="wb-track-hold" title="Human decision: the governed gate" aria-hidden="true" />
              ) : null}
              <span className="wb-track-node" aria-hidden="true">
                {state === "done" ? <svg width="10" height="10" viewBox="0 0 10 10"><path d="M2.2 5.2 4.2 7l3.6-4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg> : null}
              </span>
              <span className="wb-track-label">
                {s.label}
                <span className="wb-sr">{state === "done" ? " (completed)" : state === "current" ? " (current)" : ""}</span>
              </span>
              {s.key === "INVESTIGATING" && current?.key === "AWAITING_INSPECTION" ? (
                <span className="wb-track-loop">
                  <span className="wb-track-loop-node" aria-hidden="true" />
                  Awaiting inspection{inspectionLoops > 1 ? ` · ${inspectionLoops}×` : ""}
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>
      {exception ? <p className="wb-track-exception">Exception: {exception.label}</p> : null}
      <p className="wb-track-caption">
        <span className="wb-track-current">{caption}</span>
        <span className="wb-track-next">Next: {current?.next || "Not reported"}</span>
      </p>
    </div>
  );
}
