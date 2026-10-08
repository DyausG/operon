// Preview containers (CH-2, Phase 4A prototype hypothesis):
//  • ≥ 1280: a docked, non-modal pane (role="complementary") that pushes content; focus enters on Tab.
//  • 768–1279: a modal drawer (scrim, focus trapped, background inert; Esc / Close / Back return
//    focus to the originating row).
// There is never an "overlay but not modal, no scrim, queue still interactive" state.
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { IconX } from "@tabler/icons-react";
import { IconButton } from "./ui.jsx";

export const BP = { phone: 0, tablet: 768, laptop: 1024, desktop: 1280, workstation: 1440, wide: 1920 };

export function useMedia(query, fallback = false) {
  const get = () => { try { return typeof window !== "undefined" ? window.matchMedia(query).matches : fallback; } catch { return fallback; } };
  const [match, setMatch] = useState(get);
  useEffect(() => {
    let mq;
    try { mq = window.matchMedia(query); } catch { return undefined; }
    const on = () => setMatch(mq.matches);
    on();
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, [query]);
  return match;
}

/** Layout class for preview behaviour: "docked" ≥ 1280, "modal" 768–1279, "phone" < 768. */
export function usePreviewMode() {
  const docked = useMedia(`(min-width: ${BP.desktop}px)`, true);
  const tablet = useMedia(`(min-width: ${BP.tablet}px)`, true);
  return docked ? "docked" : tablet ? "modal" : "phone";
}

export function DockedPane({ title, titleId, onClose, children, closeLabel = "Close preview", className = "" }) {
  return (
    <aside className={`wb-pane ${className}`} role="complementary" aria-labelledby={titleId}
      onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } }}>
      <div className="wb-pane-head">
        <h2 className="wb-pane-title" id={titleId}>{title}</h2>
        <IconButton icon={IconX} label={closeLabel} onClick={onClose} />
      </div>
      <div className="wb-pane-body">{children}</div>
    </aside>
  );
}

const FOCUSABLE = 'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

export function ModalDrawer({ title, titleId, onClose, children, portalTarget, closeLabel = "Close preview", className = "" }) {
  const panel = useRef(null);
  const heading = useRef(null);
  useEffect(() => {
    const inertTarget = document.querySelector("[data-wb-inert]");
    if (inertTarget) inertTarget.inert = true;
    heading.current?.focus();
    const onKey = (e) => {
      if (e.key === "Escape") { e.stopPropagation(); onClose(); return; }
      if (e.key !== "Tab" || !panel.current) return;
      const items = [...panel.current.querySelectorAll(FOCUSABLE)].filter((el) => !el.hasAttribute("aria-hidden"));
      if (!items.length) { e.preventDefault(); return; }
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && (document.activeElement === first || document.activeElement === heading.current)) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      if (inertTarget) inertTarget.inert = false;
    };
  }, [onClose]);
  const target = portalTarget || (typeof document !== "undefined" ? document.querySelector("[data-wb-portal]") : null);
  const node = (
    <div className="wb-drawer-layer">
      <div className="wb-scrim" onClick={onClose} aria-hidden="true" />
      <div className={`wb-drawer ${className}`} role="dialog" aria-modal="true" aria-labelledby={titleId} ref={panel}>
        <div className="wb-pane-head">
          <h2 className="wb-pane-title" id={titleId} tabIndex={-1} ref={heading}>{title}</h2>
          <IconButton icon={IconX} label={closeLabel} onClick={onClose} />
        </div>
        <div className="wb-pane-body">{children}</div>
      </div>
    </div>
  );
  return target ? createPortal(node, target) : node;
}
