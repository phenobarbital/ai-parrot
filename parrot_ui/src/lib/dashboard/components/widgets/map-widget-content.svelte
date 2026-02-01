<script lang="ts">
    import { onDestroy, onMount } from "svelte";
    import "leaflet/dist/leaflet.css";
    import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
    import markerIcon from "leaflet/dist/images/marker-icon.png";
    import markerShadow from "leaflet/dist/images/marker-shadow.png";
    import { browser } from "$app/environment";
    import type { MapWidget } from "../../domain/map-widget.svelte.js";
    import DataInspectorFooter from "./data-inspector-footer.svelte";

    let { widget } = $props<{ widget: MapWidget }>();

    let mapContainer = $state<HTMLDivElement | null>(null);
    let mapInstance: L.Map | null = null;
    let tileLayer: L.TileLayer | null = null;
    let markersLayer: L.LayerGroup | null = null;
    let L: any; // Leaflet instance loaded dynamically

    function buildMarkers() {
        const data = widget.mapData as Record<string, unknown>[];
        return data
            .map((row) => {
                const lat = Number(row[widget.markerLatField]);
                const lng = Number(row[widget.markerLngField]);
                if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
                const labelValue = row[widget.markerLabelField];
                return {
                    lat,
                    lng,
                    label:
                        labelValue !== undefined ? String(labelValue) : undefined,
                };
            })
            .filter((marker): marker is { lat: number; lng: number; label?: string } =>
                Boolean(marker),
            );
    }

    async function ensureMap() {
        if (!mapContainer || mapInstance || !browser) return;

        if (!L) {
            const leafletModule = await import("leaflet");
            L = leafletModule.default;
        }

        mapInstance = L.map(mapContainer).setView(
            [widget.centerLat, widget.centerLng],
            widget.zoom,
        );

        tileLayer = L.tileLayer(widget.tileUrl, {
            attribution: widget.attribution,
        });
        tileLayer.addTo(mapInstance);

        markersLayer = L.layerGroup().addTo(mapInstance);
        
        // Initial update
        updateMarkers();
    }

    function updateTileLayer() {
        if (!mapInstance || !L) return;
        if (tileLayer) {
            mapInstance.removeLayer(tileLayer);
        }
        tileLayer = L.tileLayer(widget.tileUrl, {
            attribution: widget.attribution,
        });
        tileLayer.addTo(mapInstance);
    }

    function updateMarkers() {
        if (!markersLayer || !L) return;
        markersLayer.clearLayers();
        const markers = buildMarkers();
        markers.forEach((marker) => {
            const item = L.marker([marker.lat, marker.lng]);
            if (marker.label) {
                item.bindPopup(marker.label);
            }
            item.addTo(markersLayer!);
        });
    }

    onMount(async () => {
        if (browser) {
            const leafletModule = await import("leaflet");
            L = leafletModule.default;
            
            L.Icon.Default.mergeOptions({
                iconRetinaUrl: markerIcon2x,
                iconUrl: markerIcon,
                shadowUrl: markerShadow,
            });
            ensureMap();
        }
    });

    onDestroy(() => {
        if (mapInstance) {
            mapInstance.remove();
            mapInstance = null;
        }
    });

    $effect(() => {
        if (!mapInstance) return;
        mapInstance.setView(
            [widget.centerLat, widget.centerLng],
            widget.zoom,
        );
    });

    $effect(() => {
        if (!mapInstance) return;
        updateTileLayer();
    });

    $effect(() => {
        if (!mapInstance) return;
        updateMarkers();
    });
</script>

<div class="map-widget">
    <div class="map-container" bind:this={mapContainer}></div>
    <DataInspectorFooter data={widget.mapData} />
</div>

<style>
    .map-widget {
        display: flex;
        flex-direction: column;
        height: 100%;
    }

    .map-container {
        flex: 1;
        min-height: 0;
    }

    :global(.leaflet-container) {
        font: inherit;
        height: 100%;
        width: 100%;
    }
</style>
