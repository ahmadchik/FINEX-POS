const THEME_KEY = "finup_theme";
const LEGACY_KEY = "finup_platform_theme";

function migrateTheme() {
  if (!localStorage.getItem(THEME_KEY) && localStorage.getItem(LEGACY_KEY)) {
    localStorage.setItem(THEME_KEY, localStorage.getItem(LEGACY_KEY));
  }
}

export function isDayTheme() {
  migrateTheme();
  return localStorage.getItem(THEME_KEY) === "day";
}

export function applyTheme() {
  document.documentElement.classList.toggle("theme-day", isDayTheme());
}

function icoSun() {
  return `<svg class="theme-ico" viewBox="0 0 24 24" aria-hidden="true">
    <circle cx="12" cy="12" r="3.6" fill="currentColor"/>
    <g fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
      <path d="M12 3v2.4M12 18.6V21M3 12h2.4M18.6 12H21M5.6 5.6l1.7 1.7M16.7 16.7l1.7 1.7M18.4 5.6l-1.7 1.7M7.3 16.7l-1.7 1.7"/>
    </g>
  </svg>`;
}

function icoMoonStar() {
  return `<svg class="theme-ico" viewBox="0 0 24 24" aria-hidden="true">
    <path fill="currentColor" d="M14.2 4.2a8.2 8.2 0 1 0 5.7 13.1 7.1 7.1 0 0 1-5.7-13.1z"/>
    <path fill="currentColor" d="M18.2 4.4l.55 1.2 1.3.18-1 .92.24 1.28-1.09-.62-1.09.62.24-1.28-1-.92 1.3-.18z"/>
  </svg>`;
}

export function themeToggleHtml() {
  const day = isDayTheme();
  const label = day ? "Tun" : "Kun";
  const ico = day ? icoMoonStar() : icoSun();
  const title = day ? "Tun (oy-yulduz)" : "Kun (quyosh)";
  return `<button type="button" class="btn btn-ghost btn-sm theme-btn" id="theme-toggle" title="${title}" aria-label="${title}">${ico}<span>${label}</span></button>`;
}

export function bindThemeToggle() {
  applyTheme();
  const btn = document.getElementById("theme-toggle");
  if (!btn) return;
  btn.onclick = () => {
    localStorage.setItem(THEME_KEY, isDayTheme() ? "night" : "day");
    applyTheme();
    const day = isDayTheme();
    btn.innerHTML = (day ? icoMoonStar() : icoSun()) + `<span>${day ? "Tun" : "Kun"}</span>`;
    btn.title = day ? "Tun (oy-yulduz)" : "Kun (quyosh)";
    btn.setAttribute("aria-label", btn.title);
  };
}

applyTheme();
