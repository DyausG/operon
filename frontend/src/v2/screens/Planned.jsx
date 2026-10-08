// V2-native placeholders. A planned destination (08 §2) that has no screen yet says so inside the
// workbench; it never renders a legacy page. The only way to a legacy page is an explicit link that
// names the legacy portal (`data-legacy-exit`), opened in the same tab so Back returns here.
import { Link } from "react-router-dom";
import { usePageTitle } from "../shell/WbShell.jsx";
import { EmptyLine } from "../components/ui.jsx";
import { WB_ROUTES } from "../shell/routes.js";

export function Planned({ label, legacy }) {
  usePageTitle(label);
  return (
    <div className="wb-page">
      <div className="wb-page-head">
        <h1 className="wb-page-title">{label}</h1>
      </div>
      <EmptyLine>{label} isn’t available in this version of the workbench yet.</EmptyLine>
      {legacy ? (
        <p className="wb-secondary">
          The current {legacy.label} page is still available:{" "}
          <Link to={legacy.to} data-legacy-exit="">open {legacy.label} in the legacy portal</Link>.
        </p>
      ) : null}
    </div>
  );
}

export function NotFound() {
  usePageTitle("Page not found");
  return (
    <div className="wb-page">
      <div className="wb-page-head">
        <h1 className="wb-page-title">Page not found</h1>
      </div>
      <EmptyLine>There’s no workbench page at this address.</EmptyLine>
      <p><Link to={WB_ROUTES.overview}>Go to Overview</Link></p>
    </div>
  );
}
