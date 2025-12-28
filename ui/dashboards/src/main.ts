import { DashboardTabs } from "./dashboard";
import { Widget } from "./widget";

function section(label: string): HTMLElement {
  const d = document.createElement("div");
  d.className = "demo-section";
  d.innerHTML = `<strong>${label}</strong>`;
  return d;
}

function lorem(n = 1): string {
  const s = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. ";
  return Array.from({ length: n }, () => s).join("");
}

export function boot(mount: HTMLElement): void {
  const tabs = new DashboardTabs(mount);

  const dash1 = tabs.addDashboard(
    { title: "Dashboard A", closable: true },
    { grid: { rows: 2, cols: 2 }, template: { header: section("Header A (no widgets here)"), footer: section("Footer A") } }
  );

  const dash2 = tabs.addDashboard(
    { title: "Dashboard B", closable: true },
    { grid: { rows: 2, cols: 2 }, template: { header: section("Header B"), footer: section("Footer B") } }
  );

  const mkWidget = (title: string, icon: string, colorHint: string) =>
    new Widget({
      title,
      icon,
      header: `<div class="hint">Header: ${colorHint}</div>`,
      content: `<div class="hint">${lorem(2)}</div><div class="mini-chart"></div>`,
      footer: `<div class="hint">Footer actions</div>`,
      onRefresh: async (w) => {
        // fake refresh
        await new Promise((r) => setTimeout(r, 350));
        const chart = w.el.querySelector(".mini-chart") as HTMLElement | null;
        if (chart) chart.textContent = `Refreshed at ${new Date().toLocaleTimeString()}`;
      },
    });

  // Place 4 widgets in each dashboard (2x2)
  const wA1 = mkWidget("Sales", "💶", "blue");
  const wA2 = mkWidget("Traffic", "📈", "green");
  const wA3 = mkWidget("Errors", "🧯", "red");
  const wA4 = mkWidget("Notes", "📝", "gray");

  dash1.layout.setWidget({ row: 0, col: 0 }, wA1);
  dash1.layout.setWidget({ row: 0, col: 1 }, wA2);
  dash1.layout.setWidget({ row: 1, col: 0 }, wA3);
  dash1.layout.setWidget({ row: 1, col: 1 }, wA4);

  const wB1 = mkWidget("Map", "🗺️", "indigo");
  const wB2 = mkWidget("Queue", "📬", "teal");
  const wB3 = mkWidget("Builds", "🧱", "orange");
  const wB4 = mkWidget("Alerts", "🚨", "yellow");

  dash2.layout.setWidget({ row: 0, col: 0 }, wB1);
  dash2.layout.setWidget({ row: 0, col: 1 }, wB2);
  dash2.layout.setWidget({ row: 1, col: 0 }, wB3);
  dash2.layout.setWidget({ row: 1, col: 1 }, wB4);

  // Start on dashboard A
  tabs.activate(dash1.id);
}
