import { DashboardContainer } from "./dashboard.js";
import { Widget } from "./widget.js";

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
  const container = new DashboardContainer(mount);

  // ========================================
  // Dashboard 1: Sales (GRID MODE - snap-to-grid)
  // ========================================
  const salesDash = container.addDashboard(
    { id: "sales", title: "Sales (Grid)", icon: "💰", closable: false },
    { layoutMode: "grid", grid: { cols: 12, rows: 12 } }
  );

  const revenueWidget = new Widget({
    title: "Revenue",
    icon: "📈",
    content: `<div class="metric-card"><div class="metric-value">$1,234,567</div><div class="metric-label">Total Revenue</div><div class="metric-trend positive">↑ 12.5%</div></div>`,
    onRefresh: async (w) => {
      await new Promise((r) => setTimeout(r, 500));
      const val = Math.floor(Math.random() * 1000000 + 1000000);
      w.setContent(
        `<div class="metric-card"><div class="metric-value">$${val.toLocaleString()}</div><div class="metric-label">Total Revenue</div><div class="metric-trend positive">↑ ${(
          Math.random() * 20
        ).toFixed(1)}%</div></div>`
      );
    },
  });
  salesDash.addWidget(revenueWidget, {
    row: 0,
    col: 0,
    rowSpan: 4,
    colSpan: 6,
  });

  const usersWidget = new Widget({
    title: "Active Users",
    icon: "👥",
    content: `<div class="metric-card"><div class="metric-value">8,432</div><div class="metric-label">Online Now</div><div class="metric-trend positive">↑ 5.2%</div></div>`,
  });
  salesDash.addWidget(usersWidget, {
    row: 0,
    col: 6,
    rowSpan: 4,
    colSpan: 6,
  });

  const conversionWidget = new Widget({
    title: "Conversion Rate",
    icon: "🎯",
    content: `<div class="metric-card"><div class="metric-value">3.24%</div><div class="metric-label">Visitor to Customer</div><div class="progress-bar"><div class="progress-fill" style="width: 32.4%"></div></div></div>`,
  });
  salesDash.addWidget(conversionWidget, {
    row: 4,
    col: 0,
    rowSpan: 4,
    colSpan: 4,
  });

  const ordersWidget = new Widget({
    title: "Recent Orders",
    icon: "📋",
    content: `<ul class="order-list"><li><span class="order-id">#12847</span><span class="order-amount">$234.00</span><span class="order-status completed">Completed</span></li><li><span class="order-id">#12846</span><span class="order-amount">$89.50</span><span class="order-status pending">Pending</span></li><li><span class="order-id">#12845</span><span class="order-amount">$567.00</span><span class="order-status completed">Completed</span></li></ul>`,
    onRefresh: async (w) => {
      await new Promise((r) => setTimeout(r, 300));
      const statuses = ["completed", "pending", "processing"];
      const items = Array.from({ length: 3 }, () => {
        const id = 12847 + Math.floor(Math.random() * 100);
        const amt = (Math.random() * 500 + 50).toFixed(2);
        const st = statuses[Math.floor(Math.random() * statuses.length)];
        return `<li><span class="order-id">#${id}</span><span class="order-amount">$${amt}</span><span class="order-status ${st}">${st}</span></li>`;
      }).join("");
      w.setContent(`<ul class="order-list">${items}</ul>`);
    },
  });
  salesDash.addWidget(ordersWidget, {
    row: 4,
    col: 4,
    rowSpan: 8,
    colSpan: 8,
  });

  // ========================================
  // Dashboard 2: Analytics (FREE MODE - absolute positioning)
  // ========================================
  const freeDash = container.addDashboard(
    { id: "analytics", title: "Analytics (Free)", icon: "📊", closable: true },
    { layoutMode: "free", free: { snapToGrid: true, gridSize: 10 } }
  );

  const visitsWidget = new Widget({
    title: "Page Visits",
    icon: "👁️",
    content: `<div class="metric-card"><div class="metric-value">45,678</div><div class="metric-label">Today</div><div class="metric-trend positive">↑ 8.3%</div></div>`,
  });
  // Cast to any because addWidget signature intersection issues in TS
  freeDash.addWidget(visitsWidget, { x: 20, y: 20, width: 280, height: 180 } as any);

  const bounceWidget = new Widget({
    title: "Bounce Rate",
    icon: "📉",
    content: `<div class="metric-card"><div class="metric-value">32.1%</div><div class="metric-label">Average</div><div class="progress-bar"><div class="progress-fill warning" style="width: 32.1%"></div></div></div>`,
  });
  freeDash.addWidget(bounceWidget, { x: 320, y: 20, width: 280, height: 180 } as any);

  const sessionWidget = new Widget({
    title: "Session Duration",
    icon: "⏱️",
    content: `<div class="metric-card"><div class="metric-value">4m 32s</div><div class="metric-label">Average Time</div></div>`,
  });
  freeDash.addWidget(sessionWidget, { x: 20, y: 220, width: 400, height: 200 } as any);

  // ========================================
  // Dashboard 3: Monitoring (DOCK MODE - split zones)
  // ========================================
  const dockDash = container.addDashboard(
    { id: "monitor", title: "Monitoring (Dock)", icon: "🖥️", closable: true },
    { layoutMode: "dock" }
  );

  const cpuWidget = new Widget({
    title: "CPU Usage",
    icon: "⚙️",
    content: `<div class="metric-card"><div class="metric-value">42%</div><div class="metric-label">Average Load</div><div class="progress-bar"><div class="progress-fill cpu" style="width: 42%"></div></div></div>`,
    onRefresh: async (w) => {
      await new Promise((r) => setTimeout(r, 200));
      const val = Math.floor(Math.random() * 80 + 10);
      w.setContent(
        `<div class="metric-card"><div class="metric-value">${val}%</div><div class="metric-label">Average Load</div><div class="progress-bar"><div class="progress-fill cpu" style="width: ${val}%"></div></div></div>`
      );
    },
  });
  // Pass { dockPosition: 'center' } to satisfy AnyPlacement type structure we defined
  dockDash.addWidget(cpuWidget, { dockPosition: "center" } as any);

  const memWidget = new Widget({
    title: "Memory",
    icon: "💾",
    content: `<div class="metric-card"><div class="metric-value">6.2 GB</div><div class="metric-label">of 16 GB Used</div><div class="progress-bar"><div class="progress-fill memory" style="width: 38.75%"></div></div></div>`,
  });
  dockDash.addWidget(memWidget, { dockPosition: "right" } as any);

  const netWidget = new Widget({
    title: "Network",
    icon: "📡",
    content: `<div class="metric-card"><div class="metric-row"><span class="metric-label">↓ Download</span><span class="metric-value small">125 MB/s</span></div><div class="metric-row"><span class="metric-label">↑ Upload</span><span class="metric-value small">45 MB/s</span></div></div>`,
  });
  dockDash.addWidget(netWidget, { dockPosition: "bottom" } as any);

  const alertsWidget = new Widget({
    title: "Alerts",
    icon: "🔔",
    content: `<ul class="alert-list"><li class="alert warning">⚠️ High CPU on server-03</li><li class="alert info">ℹ️ Backup completed</li><li class="alert error">❌ Connection timeout: db-replica</li></ul>`,
  });
  dockDash.addWidget(alertsWidget, { dockPosition: "left" } as any);

  console.log("Dashboard Demo initialized!");
  console.log("- Sales: GRID mode (snap-to-grid cells)");
  console.log("- Analytics: FREE mode (drag anywhere)");
  console.log("- Monitoring: DOCK mode (split zones)");
}
