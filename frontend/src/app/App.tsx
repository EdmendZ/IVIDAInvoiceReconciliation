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
    return <div className="loading">Loading IVIDA Review Console…</div>;
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
          <span className="eyebrow">IVIDA OPERATIONS</span>
          <h1>Finance Document Control</h1>
        </div>
        <nav className="primary-nav" aria-label="Primary navigation">
          <button
            className={path === "/upload" ? "active" : ""}
            onClick={() => navigate("/upload")}
          >
            Upload
          </button>
          <button
            className={path === "/" || versionMatch ? "active" : ""}
            onClick={() => navigate("/")}
          >
            Review
          </button>
          <button
            className={path === "/reconcile" ? "active" : ""}
            onClick={() => navigate("/reconcile")}
          >
            Reconcile
          </button>
          <button
            className={path === "/cases" || caseMatch ? "active" : ""}
            onClick={() => navigate("/cases")}
          >
            Cases
          </button>
          {user.role === "admin" ? (
            <button
              className={path === "/lab" ? "active" : ""}
              onClick={() => navigate("/lab")}
            >
              Quality Lab
            </button>
          ) : null}
        </nav>
        <div className="user-chip">
          <span>{user.username}</span>
          <small>{user.role}</small>
          <button
            className="link-button"
            onClick={async () => {
              await api("/api/auth/logout", { method: "POST" });
              setUser(null);
            }}
          >
            Sign out
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
            <div className="page"><p className="error-banner">Admin access required.</p></div>
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
