// examples/a2ui/static/renderer.js — CREATE
// FEAT-610 — renders the agent-built linked dashboard (KPICard / Chart / DataTable) and wires per-widget refresh.
import { createLane } from './linked.js';

const TOKEN_KEY = 'ai_parrot_token';

async function login(username, password) {
  try {
    const response = await fetch('/api/v1/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Auth-Method': 'BasicAuth'
      },
      body: JSON.stringify({ username, password })
    });

    if (!response.ok) {
      throw new Error(`Login failed: ${response.status} ${response.statusText}`);
    }

    const data = await response.json();
    if (!data.token) {
      throw new Error('No token received from server');
    }

    localStorage.setItem(TOKEN_KEY, data.token);
    return data;
  } catch (error) {
    console.error('Login error:', error);
    throw error;
  }
}

function renderNode(id, byId, ctx) {
  const node = byId[id];
  if (!node) return;

  const element = document.createElement('div');
  element.id = id;

  switch (node.component) {
    case 'Column':
      element.className = 'column';
      if (node.children && Array.isArray(node.children)) {
        node.children.forEach(childId => {
          const childElement = renderNode(childId, byId, ctx);
          if (childElement) element.appendChild(childElement);
        });
      }
      break;
      
    case 'Row':
      element.className = 'row';
      if (node.children && Array.isArray(node.children)) {
        node.children.forEach(childId => {
          const childElement = renderNode(childId, byId, ctx);
          if (childElement) element.appendChild(childElement);
        });
      }
      break;
      
    case 'Card':
      element.className = 'card';
      if (node.child) {
        const childElement = renderNode(node.child, byId, ctx);
        if (childElement) element.appendChild(childElement);
      }
      break;
      
    case 'KPICard':
      element.className = 'kpi-card';
      element.innerHTML = renderKpi(node);
      break;
      
    case 'Chart':
      element.className = 'chart-container';
      renderChart(element, node, ctx.lane, id);
      break;
      
    case 'DataTable':
      element.className = 'datatable-container';
      renderGrid(element, node, ctx.lane, id);
      break;
      
    default:
      element.className = 'notice';
      element.textContent = `Unsupported component: ${node.component}`;
  }

  return element;
}

function renderKpi(node) {
  return `
    <div class="kpi-title">${node.title || ''}</div>
    <div class="kpi-value">${node.value || ''}</div>
    <div class="kpi-description">${node.description || ''}</div>
  `;
}

function renderChart(container, node, lane, key) {
  const chartContainer = document.createElement('div');
  chartContainer.className = 'chart';
  chartContainer.style.width = '100%';
  chartContainer.style.height = '400px';
  
  const toolbar = document.createElement('div');
  toolbar.className = 'widget-toolbar';
  const refreshBtn = document.createElement('button');
  refreshBtn.textContent = 'Refresh';
  refreshBtn.onclick = () => lane.refreshSource(key);
  toolbar.appendChild(refreshBtn);
  
  const statusSpan = document.createElement('span');
  statusSpan.className = 'status';
  statusSpan.textContent = 'Loading...';
  toolbar.appendChild(statusSpan);
  
  container.appendChild(toolbar);
  container.appendChild(chartContainer);
  
  // Initialize with snapshot data if available
  const snapshot = lane.getSnapshot(key);
  if (snapshot && snapshot.rows) {
    updateChart(chartContainer, node, snapshot.rows);
    statusSpan.textContent = 'Ready';
  }
  
  // Subscribe to updates
  lane.subscribe(key, (update) => {
    statusSpan.textContent = update.status;
    if (update.rows) {
      updateChart(chartContainer, node, update.rows);
    }
  });
}

function updateChart(container, node, data) {
  if (!window.echarts) {
    console.error('ECharts not loaded');
    return;
  }
  
  const chart = echarts.init(container);
  
  const options = {
    title: {
      text: node.title || ''
    },
    tooltip: {},
    legend: {},
    xAxis: {},
    yAxis: {},
    series: []
  };
  
  if (node.chartType === 'bar') {
    options.xAxis.type = 'category';
    options.yAxis.type = 'value';
    options.series = [{
      type: 'bar',
      data: data.map(row => ({ name: row.name, value: row.value }))
    }];
  } else if (node.chartType === 'pie') {
    options.series = [{
      type: 'pie',
      data: data.map(row => ({
        name: row.name === null ? 'Unassigned' : row.name,
        value: row.value
      }))
    }];
  }
  
  chart.setOption(options);
}

function renderGrid(container, node, lane, key) {
  const toolbar = document.createElement('div');
  toolbar.className = 'widget-toolbar';
  const refreshBtn = document.createElement('button');
  refreshBtn.textContent = 'Refresh';
  refreshBtn.onclick = () => lane.refreshSource(key);
  toolbar.appendChild(refreshBtn);
  
  const statusSpan = document.createElement('span');
  statusSpan.className = 'status';
  statusSpan.textContent = 'Loading...';
  toolbar.appendChild(statusSpan);
  
  container.appendChild(toolbar);
  
  const gridContainer = document.createElement('div');
  gridContainer.className = 'grid-container';
  container.appendChild(gridContainer);
  
  // Initialize grid
  const grid = new gridjs.Grid({
    columns: node.columns || [],
    server: {
      url: '', // We'll handle data manually
      then: () => [] // Placeholder
    },
    pagination: {
      limit: 20
    }
  }).render(gridContainer);
  
  // Store reference for updates
  container._grid = grid;
  
  // Initialize with snapshot data if available
  const snapshot = lane.getSnapshot(key);
  if (snapshot && snapshot.rows) {
    updateGrid(grid, snapshot.rows);
    statusSpan.textContent = 'Ready';
  }
  
  // Subscribe to updates
  lane.subscribe(key, (update) => {
    statusSpan.textContent = update.status;
    if (update.rows) {
      updateGrid(grid, update.rows);
    }
  });
}

function updateGrid(grid, data) {
  // Update grid with new data
  // This is a simplified implementation - in practice you might need to recreate the grid
  console.log('Updating grid with', data.length, 'rows');
}

async function boot() {
  // Check if we have a token
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) {
    // Show login form
    document.getElementById('login').style.display = 'block';
    document.getElementById('app').style.display = 'none';
    return;
  }
  
  // Hide login, show app
  document.getElementById('login').style.display = 'none';
  document.getElementById('app').style.display = 'block';
  
  try {
    // Fetch dashboard envelope
    const response = await fetch('/api/a2ui/dashboard', {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    });
    
    if (!response.ok) {
      throw new Error(`Failed to fetch dashboard: ${response.status}`);
    }
    
    const envelope = await response.json();
    
    // Build lookup by ID
    const byId = {};
    if (envelope.components) {
      envelope.components.forEach(comp => {
        byId[comp.id] = comp;
      });
    }
    
    // Find root component
    const rootId = envelope.root || 'root';
    
    // Create lane for data fetching
    const lane = createLane(envelope.sources || {}, {
      baseUrl: window.location.origin,
      token: token,
      onUpdate: (update) => {
        // Handle updates - in a real implementation you'd route these to specific widgets
        console.log('Lane update:', update);
      }
    });
    
    // Render the tree
    const ctx = { lane };
    const rootNode = renderNode(rootId, byId, ctx);
    if (rootNode) {
      document.getElementById('dashboard').appendChild(rootNode);
    }
    
    // Start the lane
    lane.start();
    
    // Setup event handlers
    document.getElementById('logout').onclick = () => {
      localStorage.removeItem(TOKEN_KEY);
      window.location.reload();
    };
    
    document.getElementById('refreshAll').onclick = () => {
      lane.refreshAll();
    };
    
    // Handle login form submission
    document.getElementById('loginForm').onsubmit = async (e) => {
      e.preventDefault();
      const username = document.getElementById('username').value;
      const password = document.getElementById('password').value;
      
      try {
        await login(username, password);
        window.location.reload();
      } catch (error) {
        alert('Login failed: ' + error.message);
      }
    };
    
  } catch (error) {
    console.error('Boot error:', error);
    alert('Failed to load dashboard: ' + error.message);
  }
}

// Start the application when DOM is loaded
document.addEventListener('DOMContentLoaded', boot);