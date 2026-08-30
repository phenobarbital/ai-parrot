<script lang="ts">
	import { onMount, onDestroy } from "svelte";
	import { browser } from "$app/environment";
	import Icon from "@iconify/svelte";
	import "leaflet/dist/leaflet.css";
	import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
	import markerIcon from "leaflet/dist/images/marker-icon.png";
	import markerShadow from "leaflet/dist/images/marker-shadow.png";

	/** Predefined marker color options using Leaflet DivIcon with inline SVG. */
	const MARKER_COLORS: Record<string, { fill: string; stroke: string; label: string }> = {
		blue:    { fill: "#3b82f6", stroke: "#1e40af", label: "Blue" },
		red:     { fill: "#ef4444", stroke: "#991b1b", label: "Red" },
		green:   { fill: "#22c55e", stroke: "#166534", label: "Green" },
		orange:  { fill: "#f97316", stroke: "#9a3412", label: "Orange" },
		purple:  { fill: "#a855f7", stroke: "#6b21a8", label: "Purple" },
		pink:    { fill: "#ec4899", stroke: "#9d174d", label: "Pink" },
		cyan:    { fill: "#06b6d4", stroke: "#155e75", label: "Cyan" },
		yellow:  { fill: "#eab308", stroke: "#854d0e", label: "Yellow" },
		default: { fill: "#3b82f6", stroke: "#1e40af", label: "Default (Blue)" },
	};

	function makeSvgIcon(color: { fill: string; stroke: string }, L: any) {
		const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 36" width="14" height="21">
			<path d="M12 0C5.4 0 0 5.4 0 12c0 9 12 24 12 24s12-15 12-24C24 5.4 18.6 0 12 0z"
				fill="${color.fill}" stroke="${color.stroke}" stroke-width="1.5"/>
			<circle cx="12" cy="11" r="4.5" fill="white" opacity="0.9"/>
		</svg>`;
		return L.divIcon({
			html: svg,
			className: "",
			iconSize: [14, 21],
			iconAnchor: [7, 21],
			popupAnchor: [0, -21],
		});
	}

	interface Props {
		data: Record<string, any>[];
		config: {
			type: string;
			mapLatColumn?: string;
			mapLngColumn?: string;
			/** Multi-column tooltip (preferred) */
			mapLabelColumns?: string[];
			/** Single column fallback (legacy) */
			mapLabelColumn?: string;
			mapMarkerColor?: string;
			title?: string;
		};
		onClose?: () => void;
		onCopyToChartCanvas?: (data: Record<string, any>[], config: Props['config']) => void;
	}

	let { data, config, onClose, onCopyToChartCanvas }: Props = $props();

	let mapContainer = $state<HTMLDivElement | null>(null);
	let mapInstance: any = null;
	let markersLayer: any = null;
	let L: any = null;

	const TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
	const ATTRIBUTION =
		'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

	/** Escape HTML entities for safe popup content. */
	function esc(val: unknown): string {
		return String(val ?? "")
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;");
	}

	/** Build HTML popup content from selected label columns. */
	function buildPopupHtml(row: Record<string, any>, labelCols: string[]): string {
		if (labelCols.length === 0) return "";
		if (labelCols.length === 1) {
			const val = row[labelCols[0]];
			return val !== undefined && val !== null ? `<b>${esc(val)}</b>` : "";
		}
		// First column bold as title, rest as key: value rows
		const lines: string[] = [];
		const [titleCol, ...restCols] = labelCols;
		const titleVal = row[titleCol];
		if (titleVal !== undefined && titleVal !== null) {
			lines.push(`<b style="font-size:13px">${esc(titleVal)}</b>`);
		}
		for (const col of restCols) {
			const val = row[col];
			if (val !== undefined && val !== null && val !== "") {
				const label = col.replace(/_/g, " ");
				lines.push(`<span style="color:#64748b;font-size:11px">${esc(label)}:</span> <span style="font-size:12px">${esc(val)}</span>`);
			}
		}
		return lines.join("<br/>");
	}

	function buildMarkers() {
		const latCol = config.mapLatColumn || "latitude";
		const lngCol = config.mapLngColumn || "longitude";
		// Resolve label columns: prefer array, fall back to single legacy prop
		const labelCols: string[] = config.mapLabelColumns && config.mapLabelColumns.length > 0
			? config.mapLabelColumns
			: config.mapLabelColumn
				? [config.mapLabelColumn]
				: [];

		return data
			.map((row) => {
				const lat = Number(row[latCol]);
				const lng = Number(row[lngCol]);
				if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
				const popup = buildPopupHtml(row, labelCols);
				return { lat, lng, popup };
			})
			.filter((m): m is NonNullable<typeof m> => m != null);
	}

	async function initMap() {
		if (!browser || !mapContainer) return;

		if (!L) {
			const leafletModule = await import("leaflet");
			L = leafletModule.default;

			// Fix default marker icons with static imports
			L.Icon.Default.mergeOptions({
				iconRetinaUrl: markerIcon2x,
				iconUrl: markerIcon,
				shadowUrl: markerShadow,
			});
		}

		const markers = buildMarkers();
		const colorKey = config.mapMarkerColor || "default";
		const colorDef = MARKER_COLORS[colorKey] || MARKER_COLORS["default"];
		const customIcon = makeSvgIcon(colorDef, L);

		// Compute center from data
		let centerLat = 0;
		let centerLng = 0;
		if (markers.length > 0) {
			centerLat = markers.reduce((sum, m) => sum + m.lat, 0) / markers.length;
			centerLng = markers.reduce((sum, m) => sum + m.lng, 0) / markers.length;
		}

		mapInstance = L.map(mapContainer).setView([centerLat, centerLng], 10);

		L.tileLayer(TILE_URL, { attribution: ATTRIBUTION }).addTo(mapInstance);

		markersLayer = L.layerGroup().addTo(mapInstance);

		// Add markers with custom icon
		markers.forEach((m) => {
			const marker = L.marker([m.lat, m.lng], { icon: customIcon });
			if (m.popup) {
				marker.bindPopup(m.popup, { maxWidth: 300 });
			}
			marker.addTo(markersLayer);
		});

		// Fit bounds if we have markers
		if (markers.length > 1) {
			const bounds = L.latLngBounds(markers.map((m) => [m.lat, m.lng]));
			mapInstance.fitBounds(bounds, { padding: [30, 30] });
		} else if (markers.length === 1) {
			mapInstance.setView([markers[0].lat, markers[0].lng], 13);
		}
	}

	onMount(() => {
		initMap();
	});

	onDestroy(() => {
		if (mapInstance) {
			mapInstance.remove();
			mapInstance = null;
		}
	});
</script>

<div
	class="group relative w-full border border-slate-200 rounded-lg p-4 bg-white mb-4 shadow-sm"
>
	<!-- Hover-reveal action buttons -->
	<div
		class="absolute top-2 right-2 z-[1000] flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity duration-200"
	>
		{#if onCopyToChartCanvas}
			<button
				class="btn btn-sm btn-circle btn-ghost text-slate-400 hover:text-amber-600 hover:bg-amber-50"
				onclick={() => onCopyToChartCanvas && onCopyToChartCanvas(data, config)}
				title="Copy to Chart Canvas"
			>
				<Icon icon="mdi:chart-box-plus-outline" class="w-4 h-4" />
			</button>
		{/if}
		{#if onClose}
			<button
				class="btn btn-sm btn-circle btn-ghost text-slate-400 hover:text-slate-600"
				onclick={onClose}
				title="Close Map"
			>
				<Icon icon="mdi:close" class="w-5 h-5" />
			</button>
		{/if}
	</div>

	<h4
		class="text-sm font-semibold text-center mb-2 text-slate-700 capitalize"
	>
		{config.title || "Map"}
	</h4>

	<div class="h-[400px] w-full rounded-lg overflow-hidden">
		<div bind:this={mapContainer} class="h-full w-full"></div>
	</div>

	<p class="mt-2 text-xs text-center text-slate-400">
		{buildMarkers().length} marker{buildMarkers().length !== 1 ? "s" : ""} plotted
	</p>
</div>
