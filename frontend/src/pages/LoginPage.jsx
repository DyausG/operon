import { useEffect, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useSession, validateCredentials } from "../state/session.jsx";
import { useTheme } from "../state/theme.jsx";
import { useEngineState } from "../state/engine.jsx";
import { Btn, Icons, Dot } from "../primitives/index.jsx";
import { Field, Input } from "../components/index.jsx";
import { ROUTES } from "../app/routes.js";

export function LoginPage() {
  const { signedIn, signIn } = useSession();
  const { resolved, toggle } = useTheme();
  const { state } = useEngineState();
  const navigate = useNavigate();
  const location = useLocation();
  const [form, setForm] = useState({ email: "", password: "", remember: true });
  const [errors, setErrors] = useState({});
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState(null);
  const [forgot, setForgot] = useState(false);
  const dest = location.state?.from || ROUTES.dashboard;

  useEffect(() => { document.title = "Sign in · Operon"; }, []);
  if (signedIn) return <Navigate to={dest} replace />;

  const submit = async (e) => {
    e.preventDefault();
    const errs = validateCredentials(form);
    setErrors(errs);
    setFailure(null);
    if (Object.keys(errs).length) return;
    setBusy(true);
    const res = await signIn(form);
    setBusy(false);
    if (!res.ok) { setErrors(res.errors || {}); setFailure("Sign-in refused. Check the fields above."); return; }
    navigate(dest, { replace: true });
  };
  const set = (k) => (e) => { setForm((f) => ({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value })); setErrors((er) => ({ ...er, [k]: undefined })); };

  return (
    <div className="login">
      <aside className="login-side" aria-hidden="true">
        <div className="login-side-inner">
          <div className="wordmark"><span className="mark" />OPERON</div>
          <h2 className="login-tag">Autonomous reliability operations for industrial systems</h2>
          <ul className="login-points">
            <li><Dot tone="auth" /><span>Predictive signals open durable incidents. Nothing executes from a signal.</span></li>
            <li><Dot tone="adv" dashed /><span>Specialist agents reason over frozen evidence. Their output is advisory.</span></li>
            <li><Dot tone="ok" /><span>Every intervention passes a human hold point and is verified from post-intervention telemetry.</span></li>
          </ul>
          <div className="login-status mono">
            <span className={`activity ${state.connected ? "on" : "off"}`} />
            <span>{state.connected ? `engine connected · ${state.meta.plant || "plant"}` : "engine not reachable · sign-in still works"}</span>
          </div>
        </div>
      </aside>
      <main className="login-main">
        <button type="button" className="btn btn-quiet btn-icon login-theme" onClick={toggle} title={`Switch to ${resolved === "dark" ? "light" : "dark"} theme`} aria-label="Toggle theme">{resolved === "dark" ? Icons.sun({}) : Icons.moon({})}</button>
        <form className="login-card" onSubmit={submit} noValidate>
          <div className="login-head">
            <span className="lbl">Sign in</span>
            <h1 className="login-title">Operon operations portal</h1>
            <p className="t3">Use your work email to open the plant's reliability command view.</p>
          </div>
          {!forgot ? (
            <>
              <Field label="Work email" error={errors.email}>
                <Input type="email" name="email" autoComplete="username" placeholder="name@plant.example" value={form.email} onChange={set("email")} aria-invalid={!!errors.email} autoFocus />
              </Field>
              <Field label="Password" error={errors.password}>
                <div className="input-wrap">
                  <Input type={show ? "text" : "password"} name="password" autoComplete="current-password" placeholder="At least 8 characters" value={form.password} onChange={set("password")} aria-invalid={!!errors.password} />
                  <button type="button" className="input-aff" onClick={() => setShow((v) => !v)} aria-label={show ? "Hide password" : "Show password"} aria-pressed={show}>{show ? Icons.eyeOff({}) : Icons.eye({})}</button>
                </div>
              </Field>
              <div className="login-row">
                <label className="check"><input type="checkbox" checked={form.remember} onChange={set("remember")} /><span>Remember me on this device</span></label>
                <button type="button" className="link-btn" onClick={() => setForgot(true)}>Forgot password?</button>
              </div>
              {failure ? <div className="banner banner-crit" role="alert">{Icons.warn({})}<span>{failure}</span></div> : null}
              <Btn primary type="submit" className="login-submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</Btn>
              <p className="login-note t3">{Icons.lock({ size: 12 })} Demo sign-in. This session lives only in your browser: the Operon host has no authentication layer yet, and the engine records approvals as the dashboard operator.</p>
            </>
          ) : (
            <>
              <p className="t2">Password recovery is handled by your plant identity provider once Operon is connected to one. In the demo build there is nothing to reset: any work email with a password of 8+ characters opens a browser-local session.</p>
              <Btn onClick={() => setForgot(false)}>Back to sign in</Btn>
            </>
          )}
        </form>
        <footer className="login-foot t4 mono">Operon · {state.meta.tagline}</footer>
      </main>
    </div>
  );
}
