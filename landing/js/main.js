/** Handles navigation, theme, copy, and Mermaid interactions for the static landing page. */
document.addEventListener("DOMContentLoaded", () => {
  const root = document.documentElement;
  const navToggle = document.querySelector(".nav-toggle");
  const navLinks = document.querySelector(".nav-links");
  const themeToggle = document.querySelector(".theme-toggle");
  const applyTheme = (theme) => {
    root.dataset.theme = theme;
    themeToggle?.setAttribute("aria-label", `Use ${theme === "dark" ? "light" : "dark"} theme`);
    const icon = themeToggle?.querySelector("i");
    icon?.classList.replace(theme === "dark" ? "fa-moon" : "fa-sun", theme === "dark" ? "fa-sun" : "fa-moon");
  };
  const savedTheme = localStorage.getItem("ai-parrot-theme");
  if (savedTheme === "dark" || savedTheme === "light") applyTheme(savedTheme);
  themeToggle?.addEventListener("click", () => {
    const theme = root.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem("ai-parrot-theme", theme);
    applyTheme(theme);
  });
  navToggle?.addEventListener("click", () => {
    const isOpen = navLinks?.classList.toggle("is-open") ?? false;
    navToggle.setAttribute("aria-expanded", String(isOpen));
  });
  navLinks?.querySelectorAll("a").forEach((link) => link.addEventListener("click", () => {
    navLinks.classList.remove("is-open");
    navToggle?.setAttribute("aria-expanded", "false");
  }));
  document.querySelectorAll(".copy-button").forEach((button) => {
    button.addEventListener("click", async () => {
      const target = document.getElementById(button.dataset.copyTarget || "");
      if (!target) return;
      await navigator.clipboard.writeText(target.textContent || "");
      button.textContent = "Copied";
      window.setTimeout(() => { button.textContent = "Copy"; }, 1600);
    });
  });
  if (window.mermaid) window.mermaid.initialize({ startOnLoad: true, theme: root.dataset.theme === "dark" ? "dark" : "default" });
});
