import { useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import GameDetail from "./pages/GameDetail";
import Games from "./pages/Games";
import League from "./pages/League";
import Model from "./pages/Model";
import NotFound from "./pages/NotFound";
import PlayerDetail from "./pages/PlayerDetail";
import Players from "./pages/Players";
import Research from "./pages/Research";
import TeamDetail from "./pages/TeamDetail";
import Teams from "./pages/Teams";

const LINKS = [
  { to: "/", label: "League", end: true },
  { to: "/teams", label: "Teams" },
  { to: "/players", label: "Players" },
  { to: "/games", label: "Games" },
  { to: "/research", label: "Research" },
  { to: "/model", label: "Model" },
];

type Theme = "light" | "dark" | "system";

function useTheme() {
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem("theme") as Theme) ?? "system",
  );

  useEffect(() => {
    const root = document.documentElement;
    // "system" removes the stamp entirely so prefers-color-scheme decides;
    // an explicit choice must win over the OS in both directions.
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);

  return [theme, setTheme] as const;
}

/** Client-side routing keeps the scroll position; a new page should start at
    the top the way a real navigation does. */
function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => window.scrollTo(0, 0), [pathname]);
  return null;
}

export default function App() {
  const [theme, setTheme] = useTheme();
  const next: Theme = theme === "dark" ? "light" : "dark";

  return (
    <div className="app">
      <ScrollToTop />
      <nav className="nav">
        <div className="container nav__inner">
          <NavLink to="/" className="nav__brand">
            WNBA Analytics
          </NavLink>
          <div className="nav__links">
            {LINKS.map((link) => (
              <NavLink key={link.to} to={link.to} end={link.end} className="nav__link">
                {link.label}
              </NavLink>
            ))}
          </div>
          <div className="nav__spacer" />
          <button
            className="control"
            onClick={() => setTheme(next)}
            aria-label={`Switch to ${next} theme`}
            title={`Switch to ${next} theme`}
          >
            ◐
          </button>
        </div>
      </nav>

      <main className="container page">
        <Routes>
          <Route path="/" element={<League />} />
          <Route path="/teams" element={<Teams />} />
          <Route path="/teams/:teamId" element={<TeamDetail />} />
          <Route path="/players" element={<Players />} />
          <Route path="/players/:playerId" element={<PlayerDetail />} />
          <Route path="/games" element={<Games />} />
          <Route path="/games/:gameId" element={<GameDetail />} />
          <Route path="/research" element={<Research />} />
          <Route path="/model" element={<Model />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>

      <footer className="footer">
        <div className="container">
          Self-hosted · read-only · price ingestion only, never order placement ·{" "}
          <a href="/docs" style={{ color: "var(--accent)" }}>
            API
          </a>
        </div>
      </footer>
    </div>
  );
}
