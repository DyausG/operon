// One engine connection for the whole application. Pages read the mirrored state through
// useEngineState(); a test harness may inject a pre-built engine instead of opening a socket.
import { createContext, useContext } from "react";
import { useEngine } from "./useEngine.js";

const Ctx = createContext(null);

function LiveEngine({ children }) {
  const engine = useEngine();
  return <Ctx.Provider value={engine}>{children}</Ctx.Provider>;
}

export function EngineProvider({ engine, children }) {
  if (engine) return <Ctx.Provider value={engine}>{children}</Ctx.Provider>;
  return <LiveEngine>{children}</LiveEngine>;
}

export function useEngineState() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useEngineState outside EngineProvider");
  return ctx;
}
