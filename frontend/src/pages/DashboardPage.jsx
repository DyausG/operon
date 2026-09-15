import { useEngineState } from "../state/engine.jsx";
import { OperationsBoard } from "../features/OperationsBoard.jsx";
import { LoadingState } from "../components/index.jsx";

export function DashboardPage() {
  const { state, ...actions } = useEngineState();
  if (!state.frames && !state.fleet.length) {
    return <div className="page"><div className="page-body"><LoadingState /></div></div>;
  }
  return (
    <div className="page-fill page-ops">
      <OperationsBoard state={state} actions={actions} />
    </div>
  );
}
