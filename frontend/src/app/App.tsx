import { label } from "../i18n";
import { useEffect, useState } from "react";
import { api, type User } from "../api/client";
import { LoginPage } from "../auth/LoginPage";
import { ReviewDocumentPage } from "../review/ReviewDocumentPage";
import { ReviewQueuePage } from "../review/ReviewQueuePage";
import { UploadPage } from "../upload/UploadPage";
import { ReconciliationPage } from "../reconcile/ReconciliationPage";
import { CaseDetailPage } from "../cases/CaseDetailPage";
import { CaseQueuePage } from "../cases/CaseQueuePage";
import { ExperimentLabPage } from "../experiments/ExperimentLabPage";

export function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [path, setPath] = useState(window.location.pathname);

  function navigate(nextPath: string, replace = false) {
    if (replace) window.history.replaceState({}, "", nextPath);
    else window.history.pushState({}, "", nextPath);
    setPath(nextPath);
  }

  useEffect(() => {
    api<User>("/api/auth/me").then(setUser).catch(() => setUser(null));
    const unauthorized = () => {
      setUser(null);
      navigate("/login");
    };
    window.addEventListener("ivida:unauthorized", unauthorized);
    const popstate = () => setPath(window.location.pathname);
    window.addEventListener("popstate", popstate);
    return () => {
      window.removeEventListener("ivida:unauthorized", unauthorized);
      window.removeEventListener("popstate", popstate);
    };
  }, []);

  if (user === undefined) {
    return <div className="loading">正在加载 IVIDA 审核工作台…</div>;
  }
  if (!user) {
    if (path !== "/login") {
      window.history.replaceState({}, "", "/login");
    }
    return <LoginPage onLogin={setUser} onNavigate={navigate} />;
  }

  const versionMatch = path.match(/^\/review\/([^/]+)$/);
  const caseMatch = path.match(/^\/cases\/([^/]+)$/);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <span className="eyebrow">IVIDA 运营管理</span>
          <h1>采购单据核对工作台</h1>
        </div>
        <nav className="primary-nav" aria-label="主导航">
          <button
            className={path === "/upload" ? "active" : ""}
            onClick={() => navigate("/upload")}
          >
            上传单据
          </button>
          <button
            className={path === "/" || versionMatch ? "active" : ""}
            onClick={() => navigate("/")}
          >
            单据审核
          </button>
          <button
            className={path === "/reconcile" ? "active" : ""}
            onClick={() => navigate("/reconcile")}
          >
            单据对账
          </button>
          <button
            className={path === "/cases" || caseMatch ? "active" : ""}
            onClick={() => navigate("/cases")}
          >
            差异处理
          </button>
          {user.role === "admin" ? (
            <button
              className={path === "/lab" ? "active" : ""}
              onClick={() => navigate("/lab")}
            >
              质量评测
            </button>
          ) : null}
        </nav>
        <div className="user-chip">
          <span>{user.username}</span>
          <small>{label(user.role)}</small>
          <button
            className="link-button"
            onClick={async () => {
              await api("/api/auth/logout", { method: "POST" });
              setUser(null);
            }}
          >
            退出登录
          </button>
        </div>
      </header>
      <main>
        {path === "/upload" ? (
          <UploadPage onNavigate={navigate} />
        ) : path === "/lab" ? (
          user.role === "admin" ? (
            <ExperimentLabPage />
          ) : (
            <div className="page"><p className="error-banner">需要管理员权限。</p></div>
          )
        ) : path === "/reconcile" ? (
          <ReconciliationPage />
        ) : caseMatch ? (
          <CaseDetailPage
            caseId={decodeURIComponent(caseMatch[1])}
            user={user}
            onNavigate={navigate}
          />
        ) : path === "/cases" ? (
          <CaseQueuePage user={user} onNavigate={navigate} />
        ) : versionMatch ? (
          <ReviewDocumentPage
            versionId={decodeURIComponent(versionMatch[1])}
            onNavigate={navigate}
          />
        ) : (
          <ReviewQueuePage onNavigate={navigate} />
        )}
      </main>
    </div>
  );
}
