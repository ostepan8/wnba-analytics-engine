import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import ErrorBoundary from "./components/ErrorBoundary";
import GameDetail from "./pages/GameDetail";
import Games from "./pages/Games";
import Home from "./pages/Home";
import League from "./pages/League";
import Model from "./pages/Model";
import NotFound from "./pages/NotFound";
import PlayerDetail from "./pages/PlayerDetail";
import Players from "./pages/Players";
import Research from "./pages/Research";
import TeamDetail from "./pages/TeamDetail";
import Teams from "./pages/Teams";

const LINKS = [
  { to: "/", label: "Scoreboard", end: true },
  { to: "/league", label: "League" },
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
  useEffect(() => {
    // Block body, deliberately. As a concise arrow this returns whatever
    // scrollTo returns, and React treats an effect's return value as its
    // cleanup function -- then calls it on unmount. A non-function there throws
    // "destroy is not a function" during teardown, which unmounts the entire
    // tree and leaves a blank page.
    window.scrollTo(0, 0);
  }, [pathname]);
  return null;
}

/** The nav's link row overflows on narrow viewports (seven destinations plus
 *  the brand and theme toggle). A static right-edge fade signals "more to the
 *  right" on first load but goes on showing the same thing once the user has
 *  scrolled past it -- and says nothing about the content that's now cut off
 *  on the left. This tracks real scroll position so each edge fades only
 *  while there is actually more of the row hidden behind it. */
function useEdgeFade() {
  const ref = useRef<HTMLDivElement>(null);
  const [fade, setFade] = useState({ start: false, end: false });

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;

    function update() {
      // 1px of slack: fractional scroll widths (from browser zoom or subpixel
      // layout) can leave scrollLeft + clientWidth a hair short of
      // scrollWidth even when fully scrolled, which would leave the end fade
      // stuck on at rest.
      const node = ref.current;
      if (!node) return;
      setFade({
        start: node.scrollLeft > 1,
        end: node.scrollLeft + node.clientWidth < node.scrollWidth - 1,
      });
    }

    update();
    el.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      el.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, []);

  return { ref, fade };
}

export default function App() {
  const [theme, setTheme] = useTheme();
  const { pathname } = useLocation();
  const next: Theme = theme === "dark" ? "light" : "dark";
  const { ref: navLinksRef, fade } = useEdgeFade();

  return (
    <div className="app">
      <ScrollToTop />
      <nav className="nav">
        <div className="container nav__inner">
          <NavLink to="/" className="nav__brand">
            WNBA Analytics
          </NavLink>
          <div
            className={`nav__links${fade.start ? " nav__links--fade-start" : ""}${fade.end ? " nav__links--fade-end" : ""}`}
            ref={navLinksRef}
          >
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
        <ErrorBoundary resetKey={pathname}>
          <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/league" element={<League />} />
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
        </ErrorBoundary>
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
