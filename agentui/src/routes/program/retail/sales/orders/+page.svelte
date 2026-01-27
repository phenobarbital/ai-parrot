<script lang="ts">
	import { createDashboardContainerStore } from '$lib/stores/dashboard/store.svelte';
	import DashboardContainer from '$lib/components/dashboard/DashboardContainer.svelte';
	import { AgentWidget } from '$lib/stores/dashboard/agent-widget.svelte';
	import { v4 as uuidv4 } from 'uuid';

	// Create the store instance for this page
	const store = createDashboardContainerStore();

	// === Dashboard 1: Sales Overview (Grid) ===
	const salesDash = store.addDashboard('Sales Overview', '💰');

	// 1. Welcome Widget
	salesDash.addWidget(
		new AgentWidget({
			id: uuidv4(),
			title: 'Welcome',
			type: 'agent-response',
			message: {
				content:
					'### Sales Command Center\nOverview of Q4 performance. **Drag**, **Resize**, or **Maximize** widgets to customize your view.',
				output_mode: 'markdown'
			},
			position: { x: 0, y: 0, w: 4, h: 4 }
		})
	);

	// 2. Revenue Chart (Line)
	salesDash.addWidget(
		new AgentWidget({
			id: uuidv4(),
			title: 'Revenue Trends',
			type: 'agent-response',
			message: {
				output_mode: 'echarts',
				data: {
					tooltip: { trigger: 'axis' },
					xAxis: { type: 'category', data: ['Oct', 'Nov', 'Dec', 'Jan'] },
					yAxis: { type: 'value' },
					series: [{ data: [820, 932, 901, 1200], type: 'line', smooth: true, areaStyle: {} }]
				}
			},
			position: { x: 4, y: 0, w: 8, h: 6 }
		})
	);

	// 3. Top Products (Bar)
	salesDash.addWidget(
		new AgentWidget({
			id: uuidv4(),
			title: 'Top Products',
			type: 'agent-response',
			message: {
				output_mode: 'echarts',
				data: {
					tooltip: { trigger: 'axis' },
					xAxis: { type: 'value' },
					yAxis: { type: 'category', data: ['Laptop', 'Phone', 'Watch', 'Headphones'] },
					series: [{ data: [320, 302, 201, 154], type: 'bar' }]
				}
			},
			position: { x: 0, y: 4, w: 6, h: 6 }
		})
	);

	// 4. Recent Orders (Table)
	salesDash.addWidget(
		new AgentWidget({
			id: uuidv4(),
			title: 'Recent Orders',
			type: 'agent-response',
			message: {
				content: 'Latest transactions from global stores.',
				output_mode: 'markdown',
				data: [
					{ id: '#1001', customer: 'Alice', total: '$120', status: 'Shipped' },
					{ id: '#1002', customer: 'Bob', total: '$85', status: 'Processing' },
					{ id: '#1003', customer: 'Charlie', total: '$340', status: 'Delivered' },
					{ id: '#1004', customer: 'Diana', total: '$50', status: 'Pending' }
				]
			},
			position: { x: 6, y: 6, w: 6, h: 6 }
		})
	);

	// === Dashboard 2: Inventory (Free Layout) ===
	const inventoryDash = store.addDashboard('Inventory Map', '📦');
	inventoryDash.layoutMode = 'free';

	// 1. Warehouse Map (Floating by default in free mode)
	inventoryDash.addWidget(
		new AgentWidget({
			id: uuidv4(),
			title: 'Main Warehouse',
			type: 'agent-response',
			message: {
				content:
					'![Warehouse](https://via.placeholder.com/600x400?text=Warehouse+Layout)\n*Zone A: Electronics*',
				output_mode: 'markdown'
			},
			// In free mode, x/y are pixels (handled by widget logic or we explicitly set big numbers?)
			// The widget store logic we added converts small numbers to *100 pixels.
			// So x:0, y:0 -> 20px, 20px. x:5 -> 500px.
			position: { x: 0.5, y: 0.5, w: 6, h: 5 }
		})
	);

	// === Dashboard 3: Operations (Code/Logs) ===
	const opsDash = store.addDashboard('Ops Logs', '🛠️');

	opsDash.addWidget(
		new AgentWidget({
			id: uuidv4(),
			title: 'Server Logs',
			type: 'agent-response',
			message: {
				content:
					'```bash\n[INFO] Starting export job...\n[INFO] Connecting to DB...\n[WARN] Retrying connection (1/3)...\n[INFO] Connected.\n[INFO] Export complete.\n```',
				output_mode: 'markdown'
			},
			position: { x: 0, y: 0, w: 12, h: 6 }
		})
	);
</script>

<div class="bg-base-100 flex h-screen w-full flex-col">
	<!-- Header -->
	<div class="border-base-300 bg-base-100 flex h-12 items-center justify-between border-b px-4">
		<div class="flex items-center gap-2">
			<span class="text-lg font-bold tracking-tight">Retail Command</span>
			<span class="opacity-30">/</span>
			<span class="font-medium opacity-70">Sales & Orders</span>
		</div>
		<div class="flex gap-2">
			<button class="btn btn-sm btn-ghost">Settings</button>
			<div class="avatar placeholder">
				<div class="bg-neutral text-neutral-content w-8 rounded-full">
					<span class="text-xs">USR</span>
				</div>
			</div>
		</div>
	</div>

	<!-- Dashboard Container -->
	<div class="min-h-0 flex-1">
		<DashboardContainer {store} />
	</div>
</div>
