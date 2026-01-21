import {
    DashboardContainer,
    LeafletWidget
} from '../src/index.js';

function initDemo() {
    const mount = document.getElementById('app') || document.body;
    const container = new DashboardContainer(mount);

    const dash = container.addDashboard(
        { id: 'leaflet', title: 'Leaflet Test', icon: '🗺️', closable: false },
        { layoutMode: 'grid', grid: { cols: 12, rows: 12 } }
    );

    const mapWidget = new LeafletWidget({
        id: 'map',
        title: 'Map',
        center: [51.505, -0.09],
        zoom: 13
    });
    dash.addWidget(mapWidget, { row: 0, col: 0, rowSpan: 6, colSpan: 6 });

    console.log('Leaflet Widget Test initialized');

    // expose for debug
    window.testWidget = mapWidget;
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDemo);
} else {
    initDemo();
}
