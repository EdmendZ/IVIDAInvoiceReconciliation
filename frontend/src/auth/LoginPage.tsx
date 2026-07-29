import { FormEvent, useState } from "react";
import { api, type User } from "../api/client";

export function LoginPage({
  onLogin,
  onNavigate,
}: {
  onLogin: (user: User) => void;
  onNavigate: (path: string) => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const user = await api<User>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      onLogin(user);
      onNavigate("/");
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Sign in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-card">
        <span className="eyebrow">IVIDA FINANCE CONTROL</span>
        <h1>Review extracted documents</h1>
        <p>
          Verify invoices and receive notes before they are released for
          reconciliation.
        </p>
        <form onSubmit={submit}>
          <label>
            Username
            <input
              id="username"
              name="username"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required
            />
          </label>
          <label>
            Password
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>
          {error && <div className="error-banner">{error}</div>}
          <button className="primary" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </section>
    </main>
  );
}
