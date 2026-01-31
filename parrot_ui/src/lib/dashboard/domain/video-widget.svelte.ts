import { UrlManagedWidget, type UrlManagedConfig } from "./url-managed-widget.svelte.js";
import type { ConfigTab } from "./types.js";

export interface VideoWidgetConfig extends UrlManagedConfig {
    autoplay?: boolean;
    loop?: boolean;
    muted?: boolean;
    controls?: boolean;
}

export class VideoWidget extends UrlManagedWidget {
    autoplay = $state(false);
    loop = $state(false);
    muted = $state(false);
    controls = $state(true);

    constructor(config: VideoWidgetConfig) {
        super({
            ...config,
            title: config.title || "Video Player",
            icon: config.icon ?? "🎥",
        });

        this.autoplay = config.autoplay ?? false;
        this.loop = config.loop ?? false;
        this.muted = config.muted ?? false;
        this.controls = config.controls ?? true;
    }

    override getConfigTabs(): ConfigTab[] {
        return [...super.getConfigTabs(), this.createVideoConfigTab()];
    }

    override onConfigSave(config: Record<string, unknown>): void {
        super.onConfigSave(config);
        if (typeof config.autoplay === "boolean") this.autoplay = config.autoplay;
        if (typeof config.loop === "boolean") this.loop = config.loop;
        if (typeof config.muted === "boolean") this.muted = config.muted;
        if (typeof config.controls === "boolean") this.controls = config.controls;
    }

    protected createVideoConfigTab(): ConfigTab {
        let autoplayInput: HTMLInputElement | undefined;
        let loopInput: HTMLInputElement | undefined;
        let mutedInput: HTMLInputElement | undefined;
        let controlsInput: HTMLInputElement | undefined;

        // Helper to create checkbox
        const createCheckbox = (label: string, checked: boolean) => {
            const labelEl = document.createElement("label");
            Object.assign(labelEl.style, {
                display: "flex",
                alignItems: "center",
                gap: "8px",
                marginBottom: "10px",
                cursor: "pointer",
                fontSize: "14px",
                color: "var(--text, #333)"
            });

            const input = document.createElement("input");
            input.type = "checkbox";
            input.checked = checked;

            labelEl.append(input, document.createTextNode(label));
            return { wrapper: labelEl, input };
        };

        return {
            id: "video-settings",
            label: "Playback",
            icon: "⏯",
            render: (container: HTMLElement) => {
                container.innerHTML = "";

                const autoplayComp = createCheckbox("Autoplay", this.autoplay);
                autoplayInput = autoplayComp.input;

                const loopComp = createCheckbox("Loop", this.loop);
                loopInput = loopComp.input;

                const mutedComp = createCheckbox("Muted", this.muted);
                mutedInput = mutedComp.input;

                const controlsComp = createCheckbox("Show Controls", this.controls);
                controlsInput = controlsComp.input;

                container.append(
                    autoplayComp.wrapper,
                    loopComp.wrapper,
                    mutedComp.wrapper,
                    controlsComp.wrapper
                );
            },
            save: () => ({
                autoplay: autoplayInput?.checked ?? this.autoplay,
                loop: loopInput?.checked ?? this.loop,
                muted: mutedInput?.checked ?? this.muted,
                controls: controlsInput?.checked ?? this.controls,
            })
        };
    }
}
