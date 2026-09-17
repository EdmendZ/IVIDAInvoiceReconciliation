import { useEffect, useState } from "react";

import { api, type User } from "../api/client";
import { LoginPage } from "../auth/LoginPage";
import { CaseDetailPage } from "../cases/CaseDetailPage";
import { CaseQueuePage } from "../cases/CaseQueuePage";
import { ExperimentLabPage } from "../experiments/ExperimentLabPage";
import { HistoryPage } from "../history/HistoryPage";
import { label } from "../i18n";
import { ReconciliationPage } from "../reconcile/ReconciliationPage";
import { ReviewDocumentPage } from "../review/ReviewDocumentPage";
import { ReviewQueuePage } from "../review/ReviewQueuePage";
import { UploadPage } from "../upload/UploadPage";
import { DocumentPage } from "../workspace/DocumentPage";
import { WorkspacePage } from "../workspace/WorkspacePage";
import { getRuntime } from "../workspace/workspaceClient";
import type { RuntimeView } from "../workspace/workspaceTypes";

export function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [runtime, setRuntime] = useState<RuntimeView | null | undefined>(undefined);
  const [runtimeError, setRuntimeError] = useState("");
  const [path, setPath] = useState(window.location.pathname);

  function navigate(nextPath: string, replace = false) {
    if (replace) window.history.replaceState({}, "", nextPath);
    else window.history.pushState({}, "", nextPath);
    setPath(nextPath);
  }

  async function loadRuntime() {
    setRuntimeError("");
    try {
      setRuntime(await getRuntime());
    } catch (problem) {
      setRuntime(null);
      setRuntimeError(problem instanceof Error ? problem.message : "无法读取工作台配置");
    }
  }

  useEffect(() => {
    api<User>("/api/auth/me").then(setUser).catch(() => setUser(null));
    const unauthorized = () => {
      setUser(null);
      setRuntime(undefined);
      navigate("/login");
    };
    const popstate = () => setPath(window.location.pathname);
    window.addEventListener("ivida:unauthorized", unauthorized);
    window.addEventListener("popstate", popstate);
    return () => {
      window.removeEventListener("ivida:unauthorized", unauthorized);
      window.removeEventListener("popstate", popstate);
    };
  }, []);

  useEffect(() => {
    if (user) void loadRuntime();
  }, [user]);

  if (user === undefined) return <div className="loading">正在加载 IVIDA 审核工作台…</div>;
  if (!user) {
    if (path !== "/login") window.history.replaceState({}, "", "/login");
    return <LoginPage onLogin={setUser} onNavigate={navigate} />;
  }
  if (runtime === undefined) return <div className="loading">正在读取工作台配置…</div>;
  if (runtime === null) {
    return <div className="page"><div className="error-banner">{runtimeError}</div><button onClick={() => void loadRuntime()}>重试</button></div>;
  }

  const versionMatch = path.match(/^\/review\/([^/]+)$/);
  const caseMatch = path.match(/^\/cases\/([^/]+)$/);
  const documentMatch = path.match(/^\/documents\/([^/]+)$/);
  const historyMatch = path.match(/^\/history\/(?!legacy$)([^/]+)$/);
  const workspaceEnabled = runtime.enabled;
  const historyActive = path.startsWith("/history") || path === "/cases" || Boolean(caseMatch) || path === "/reconcile" || Boolean(versionMatch);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div><span className="eyebrow">IVIDA 运营管理</span><h1>采购单据核对工作台</h1></div>
        {workspaceEnabled ? (
          <nav className="primary-nav" aria-label="主导航">
            <button className={path === "/" || Boolean(documentMatch) ? "active" : ""} onClick={() => navigate("/")}>工作台</button>
            <button className={historyActive ? "active" : ""} onClick={() => navigate("/history")}>历史记录</button>
          </nav>
        ) : (
          <nav className="primary-nav" aria-label="主导航">
            <button className={path === "/upload" ? "active" : ""} onClick={() => navigate("/upload")}>上传单据</button>
            <button className={path === "/" || Boolean(versionMatch) ? "active" : ""} onClick={() => navigate("/")}>单据审核</button>
            <button className={path === "/reconcile" ? "active" : ""} onClick={() => navigate("/reconcile")}>单据对账</button>
            <button className={path === "/cases" || Boolean(caseMatch) ? "active" : ""} onClick={() => navigate("/cases")}>差异处理</button>
            {user.role === "admin" && <button className={path === "/lab" ? "active" : ""} onClick={() => navigate("/lab")}>质量评测</button>}
          </nav>
        )}
        <div className="user-chip">
          {workspaceEnabled && user.role === "admin" && <button className="management-link" onClick={() => navigate("/lab")}>管理工具</button>}
          <span>{user.username}</span><small>{label(user.role)}</small>
          <button className="link-button" onClick={async () => { await api("/api/auth/logout", { method: "POST" }); setUser(null); setRuntime(undefined); }}>退出登录</button>
        </div>
      </header>
      <main>
        {path === "/lab" ? (
          user.role === "admin" ? <ExperimentLabPage /> : <div className="page"><p className="error-banner">需要管理员权限。</p></div>
        ) : workspaceEnabled ? (
          documentMatch ? (
            <DocumentPage
              allowAdvancedJson={user.role === "admin"}
              autoOpenRelated={new URLSearchParams(window.location.search).get("uploaded") === "1"}
              documentId={decodeURIComponent(documentMatch[1])}
              onNavigate={navigate}
            />
          ) : historyMatch ? (
            <HistoryPage confirmationId={decodeURIComponent(historyMatch[1])} onNavigate={navigate} />
          ) : path === "/history" ? (
            <HistoryPage onNavigate={navigate} />
          ) : caseMatch ? (
            <CaseDetailPage caseId={decodeURIComponent(caseMatch[1])} user={user} onNavigate={navigate} readOnly />
          ) : path === "/history/legacy" || path === "/cases" ? (
            <CaseQueuePage user={user} onNavigate={navigate} readOnly />
          ) : path === "/reconcile" ? (
            <ReconciliationPage readOnly />
          ) : versionMatch ? (
            <ReviewDocumentPage versionId={decodeURIComponent(versionMatch[1])} onNavigate={navigate} readOnly />
          ) : path === "/upload" ? (
            <ReviewQueuePage onNavigate={navigate} readOnly />
          ) : (
            <WorkspacePage onNavigate={navigate} />
          )
        ) : path === "/upload" ? (
          <UploadPage onNavigate={navigate} />
        ) : path === "/reconcile" ? (
          <ReconciliationPage />
        ) : caseMatch ? (
          <CaseDetailPage caseId={decodeURIComponent(caseMatch[1])} user={user} onNavigate={navigate} />
        ) : path === "/cases" ? (
          <CaseQueuePage user={user} onNavigate={navigate} />
        ) : versionMatch ? (
          <ReviewDocumentPage versionId={decodeURIComponent(versionMatch[1])} onNavigate={navigate} />
        ) : (
          <ReviewQueuePage onNavigate={navigate} />
        )}
      </main>
    </div>
  );
}
