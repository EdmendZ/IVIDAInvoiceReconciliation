import { useEffect, useState } from "react";
import { api, type User } from "../api/client";
import { LoginPage } from "../auth/LoginPage";
import { ReviewDocumentPage } from "../review/ReviewDocumentPage";
import { ReviewQueuePage } from "../review/ReviewQueuePage";

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

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <span className="eyebrow">IVIDA OPERATIONS</span>
          <h1>Document Review</h1>
        </div>
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
        {versionMatch ? (
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
