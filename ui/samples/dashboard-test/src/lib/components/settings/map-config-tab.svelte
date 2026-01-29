<script lang="ts">
    import type { MapConfig, MapWidget } from "../../domain/map-widget.svelte.js";

    interface Props {
        widget: MapWidget;
        onConfigChange: (config: MapConfig) => void;
    }

    let { widget, onConfigChange }: Props = $props();

    let tileUrl = $state(widget.tileUrl);
    let attribution = $state(widget.attribution);
    let centerLat = $state(widget.centerLat.toString());
    let centerLng = $state(widget.centerLng.toString());
    let zoom = $state(widget.zoom.toString());
    let markerLatField = $state(widget.markerLatField);
    let markerLngField = $state(widget.markerLngField);
    let markerLabelField = $state(widget.markerLabelField);

    $effect(() => {
        onConfigChange({
            tileUrl,
            attribution,
            centerLat: Number(centerLat),
            centerLng: Number(centerLng),
            zoom: Number(zoom),
            markerLatField,
            markerLngField,
            markerLabelField,
        });
    });
</script>

<div class="tab-section">
    <div class="form-group">
        <label for="tile-url">Tile URL</label>
        <input id="tile-url" type="text" bind:value={tileUrl} />
    </div>

    <div class="form-group">
        <label for="attribution">Attribution</label>
        <input id="attribution" type="text" bind:value={attribution} />
    </div>

    <div class="form-row">
        <div class="form-group">
            <label for="center-lat">Center Latitude</label>
            <input id="center-lat" type="number" bind:value={centerLat} />
        </div>
        <div class="form-group">
            <label for="center-lng">Center Longitude</label>
            <input id="center-lng" type="number" bind:value={centerLng} />
        </div>
        <div class="form-group">
            <label for="zoom">Zoom</label>
            <input id="zoom" type="number" bind:value={zoom} />
        </div>
    </div>

    <div class="form-group">
        <label for="lat-field">Marker Latitude Field</label>
        <input id="lat-field" type="text" bind:value={markerLatField} />
    </div>

    <div class="form-group">
        <label for="lng-field">Marker Longitude Field</label>
        <input id="lng-field" type="text" bind:value={markerLngField} />
    </div>

    <div class="form-group">
        <label for="label-field">Marker Label Field</label>
        <input id="label-field" type="text" bind:value={markerLabelField} />
    </div>
</div>

<style>
    .tab-section {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }

    .form-row {
        display: flex;
        gap: 12px;
    }

    .form-group {
        flex: 1;
    }

    .form-group label {
        display: block;
        margin-bottom: 6px;
        font-size: 0.875rem;
        font-weight: 500;
    }

    input {
        width: 100%;
        padding: 8px 10px;
        border: 1px solid var(--border, #dadce0);
        border-radius: 6px;
        font-size: 0.9rem;
    }
</style>
