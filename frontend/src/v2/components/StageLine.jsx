// Lifecycle position in one line (F0 §14 D, Appendix A: replaces the giant 8-node track on the case
// page). The text says where the case is; the 8-tick micro-bar is a non-interactive position display
// (never a stepper, never clickable), kept as the accessible "Case lifecycle position" group.
import { STAGES } from "../model/status.js";
import { stageLineOf } from "../model/lifecycle.js";

export function StageLine({ alert }) {
  const line = stageLineOf(alert);
  const pos = line.position;
  return (
    <div className="wb-stageline">
      <p className="wb-stageline-text">
        <span className="wb-stageline-pos">{line.text}</span>
        {line.context.length ? <span className="wb-stageline-ctx"> · {line.context.join(" · ")}</span> : null}
      </p>
      <div className={`wb-micro ${line.exception ? "is-exception" : ""}`} role="group" aria-label="Case lifecycle position">
        <ol className="wb-micro-list">
          {STAGES.map((s) => {
            const state = pos == null ? "future" : s.n < pos ? "done" : s.n === pos && !line.exception ? "current" : s.n === pos ? "origin" : "future";
            return (
              <li key={s.key} className={`wb-micro-tick is-${state} ${s.key === "AWAITING_DECISION" ? "has-hold" : ""}`}
                aria-current={state === "current" ? "step" : undefined}>
                <span className="wb-sr">{s.label}{state === "done" ? " (completed)" : state === "current" ? " (current)" : state === "origin" ? " (where the exception occurred)" : ""}</span>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}
