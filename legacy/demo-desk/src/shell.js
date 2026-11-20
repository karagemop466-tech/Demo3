import { escapeHTML } from "./utils.js";

const NAV_GROUPS = [
  {
    label: "Markets",
    links: [
      { id: "home", label: "Market dashboard", href: "index.html", icon: "◈" },
      { id: "events", label: "All topic events", href: "pages/events.html", icon: "⌕" },
    ],
  },
  {
    label: "Topic trackers",
    links: [
      { id: "gas", label: "Gas prices", href: "pages/gas-prices.html", icon: "↗" },
      { id: "elections", label: "Elections", href: "pages/elections.html", icon: "◎" },
      { id: "culture", label: "Culture", href: "pages/culture.html", icon: "✳" },
      { id: "crypto", label: "Crypto", href: "pages/crypto.html", icon: "◇" },
      { id: "golf", label: "Golf", href: "pages/golf.html", icon: "⌁" },
    ],
  },
  {
    label: "Analyze",
    links: [
      { id: "resolution", label: "Resolution tracker", href: "pages/resolution.html", icon: "✓" },
      { id: "portfolio", label: "Portfolio", href: "pages/portfolio.html", icon: "▦" },
      { id: "strategy", label: "Strategy lab", href: "pages/strategy-lab.html", icon: "⌘" },
    ],
  },
  {
    label: "Review",
    links: [
      { id: "suggestions", label: "Suggestions", href: "pages/suggestions.html", icon: "✦" },
      { id: "questions", label: "Questions & answers", href: "pages/questions.html", icon: "?" },
      { id: "review", label: "Flagged for review", href: "pages/review.html", icon: "⚑" },
      { id: "sources", label: "Official sources", href: "pages/sources.html", icon: "↗" },
    ],
  },
];

const PAGE_LABELS = {
  home: "Market dashboard",
  events: "All topic events",
  gas: "Gas prices",
  elections: "Elections",
  culture: "Culture",
  crypto: "Crypto",
  golf: "Golf",
  resolution: "Resolution tracker",
  portfolio: "Demo portfolio",
  strategy: "Strategy lab",
  suggestions: "Suggestions",
  questions: "Questions & answers",
  review: "Flagged for Review",
  sources: "Official sources",
};

function navLinks(root, activePage) {
  return NAV_GROUPS.map((group) => `
    <div class="nav-group">
      <div class="nav-label">${escapeHTML(group.label)}</div>
      ${group.links.map((link) => `
        <a class="nav-item${activePage === link.id ? " nav-active" : ""}" href="${root}${link.href}"${activePage === link.id ? ' aria-current="page"' : ""} title="${escapeHTML(link.label)}">
          <span class="nav-icon" aria-hidden="true">${escapeHTML(link.icon)}</span>
          <span class="nav-text">${escapeHTML(link.label)}</span>
        </a>
      `).join("")}
    </div>
  `).join("");
}

export function mountShell() {
  const root = document.body.dataset.root ?? "";
  const activePage = document.body.dataset.page ?? "home";
  const sidebar = document.querySelector("#site-sidebar");
  const topbar = document.querySelector("#site-topbar");
  const footer = document.querySelector("#site-footer");
  const label = PAGE_LABELS[activePage] ?? "Dashboard";

  if (sidebar) {
    sidebar.innerHTML = `
      <a class="sidebar-brand" href="${root}index.html" aria-label="Kalshi Demo Desk home">
        <span class="brand-mark" aria-hidden="true">K</span>
        <span class="brand-copy"><span class="brand-title">Kalshi</span><span class="brand-caption">Demo Desk</span></span>
      </a>
      <nav class="desktop-nav" aria-label="Main navigation">${navLinks(root, activePage)}</nav>
      <div class="sidebar-bottom">
        <span class="demo-tag"><span class="demo-tag-text">DEMO · READ ONLY</span></span>
        <span class="sidebar-note">Public market data only.<br>No private account key is loaded.</span>
      </div>
    `;
  }

  if (topbar) {
    topbar.innerHTML = `
      <div class="topbar-left">
        <a class="mobile-brand" href="${root}index.html" aria-label="Kalshi Demo Desk home"><span class="brand-mark" aria-hidden="true">K</span><strong>DEMO DESK</strong></a>
        <div class="breadcrumbs"><a href="${root}index.html">Dashboard</a><span aria-hidden="true">/</span><span class="crumb-current">${escapeHTML(label)}</span></div>
      </div>
      <div class="topbar-right">
        <span class="readonly-tag">PUBLIC DEMO · READ-ONLY</span>
        <span id="global-feed-status" class="feed-status" role="status" aria-live="polite">Connecting to demo feed…</span>
        <button class="button button-quiet button-refresh" id="global-refresh" type="button" aria-label="Refresh data"><span aria-hidden="true">↻</span><span>Refresh</span></button>
        <details class="mobile-nav">
          <summary aria-label="Open navigation menu"><span></span><span></span><span></span></summary>
          <nav aria-label="Mobile navigation">${navLinks(root, activePage)}</nav>
        </details>
      </div>
    `;
    topbar.querySelector("#global-refresh")?.addEventListener("click", () => {
      window.dispatchEvent(new CustomEvent("kalshi:refresh"));
    });
  }

  if (footer) {
    footer.innerHTML = `
      <span>Kalshi demo market data · source-linked · no trade execution</span>
      <span><a href="${root}pages/sources.html">Official source register ↗</a> · Every displayed value must come from the official demo API.</span>
    `;
  }
}

export function setFeedStatus(message, status = "neutral") {
  const element = document.querySelector("#global-feed-status");
  if (!element) return;
  element.textContent = message;
  element.dataset.state = status;
}
