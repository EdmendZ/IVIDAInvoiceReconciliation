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
      setError(problem instanceof Error ? problem.message : "登录失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-card">
        <span className="eyebrow">IVIDA 财务管理</span>
        <h1>审核提取的单据</h1>
        <p>
          核实发票与收货单的提取内容，批准后即可进行对账。
        </p>
        <form onSubmit={submit}>
          <label>
            用户名
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
            密码
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
            {busy ? "正在登录…" : "登录"}
          </button>
        </form>
      </section>
    </main>
  );
}
