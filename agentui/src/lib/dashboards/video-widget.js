// video-widget.ts - Abstract base class for video embedding widgets
import { UrlWidget } from "./url-widget.js";
/**
 * Abstract base class for video embedding widgets.
 * Subclasses: YouTubeWidget, VimeoWidget
 */
export class VideoWidget extends UrlWidget {
    _iframe;
    autoplay = false;
    controls = true;
    loop = false;
    muted = false;
    startTime = 0;
    constructor(opts) {
        super(opts);
        this.autoplay = opts.autoplay ?? false;
        this.controls = opts.controls ?? true;
        this.loop = opts.loop ?? false;
        this.muted = opts.muted ?? false;
        this.startTime = opts.startTime ?? 0;
        // Create element after constructor chain completes
        this.initializeVideoElement();
    }
    initializeVideoElement() {
        this._iframe = document.createElement("iframe");
        Object.assign(this._iframe.style, {
            width: "100%",
            height: "100%",
            border: "none",
            display: "block",
        });
        this._iframe.setAttribute("allowfullscreen", "");
        this._iframe.setAttribute("allow", "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture");
        this.setContent(this._iframe);
        // Update content if URL is already set
        if (this.url && this.url !== "undefined" && this.url !== "") {
            this.updateContent();
        }
    }
    onInit() {
        // Do nothing - element is created in constructor after super() returns
    }
    updateContent() {
        if (!this._iframe || !this.url)
            return;
        const videoId = this.parseVideoId(this.url);
        if (videoId) {
            const embedUrl = this.getEmbedUrl(videoId);
            console.log(`[${this.getProviderName()}Widget] Setting iframe.src to:`, embedUrl);
            this._iframe.src = embedUrl;
        }
        else {
            console.warn(`[${this.getProviderName()}Widget] Could not parse video ID from:`, this.url);
        }
    }
    /** Reload video from current URL */
    reload() {
        this.updateContent();
    }
    /** Override to add video config tab */
    getConfigTabs() {
        return [
            ...super.getConfigTabs(),
            this.createVideoConfigTab()
        ];
    }
    /** Apply video config on save */
    onConfigSave(config) {
        super.onConfigSave(config);
        if (typeof config.autoplay === "boolean")
            this.autoplay = config.autoplay;
        if (typeof config.controls === "boolean")
            this.controls = config.controls;
        if (typeof config.loop === "boolean")
            this.loop = config.loop;
        if (typeof config.muted === "boolean")
            this.muted = config.muted;
        if (typeof config.startTime === "number")
            this.startTime = config.startTime;
        // Reload to apply changes
        this.updateContent();
    }
    /** Create the video configuration tab */
    createVideoConfigTab() {
        let autoplayCheckbox;
        let controlsCheckbox;
        let loopCheckbox;
        let mutedCheckbox;
        let startTimeInput;
        return {
            id: "video",
            label: "Video",
            icon: "🎬",
            render: (container) => {
                container.innerHTML = "";
                const createCheckboxField = (label, checked) => {
                    const group = document.createElement("div");
                    Object.assign(group.style, {
                        marginBottom: "12px",
                        display: "flex",
                        alignItems: "center",
                        gap: "8px",
                    });
                    const checkbox = document.createElement("input");
                    checkbox.type = "checkbox";
                    checkbox.checked = checked;
                    const labelEl = document.createElement("label");
                    labelEl.textContent = label;
                    Object.assign(labelEl.style, {
                        fontSize: "13px",
                        color: "var(--text, #333)",
                    });
                    group.append(checkbox, labelEl);
                    return { group, checkbox };
                };
                const autoplayField = createCheckboxField("Autoplay", this.autoplay);
                autoplayCheckbox = autoplayField.checkbox;
                container.appendChild(autoplayField.group);
                const controlsField = createCheckboxField("Show controls", this.controls);
                controlsCheckbox = controlsField.checkbox;
                container.appendChild(controlsField.group);
                const loopField = createCheckboxField("Loop video", this.loop);
                loopCheckbox = loopField.checkbox;
                container.appendChild(loopField.group);
                const mutedField = createCheckboxField("Start muted", this.muted);
                mutedCheckbox = mutedField.checkbox;
                container.appendChild(mutedField.group);
                // Start time field
                const startTimeGroup = document.createElement("div");
                Object.assign(startTimeGroup.style, { marginBottom: "12px" });
                const startTimeLabel = document.createElement("label");
                startTimeLabel.textContent = "Start time (seconds)";
                Object.assign(startTimeLabel.style, {
                    display: "block",
                    marginBottom: "6px",
                    fontSize: "13px",
                    fontWeight: "500",
                    color: "var(--text, #333)",
                });
                startTimeInput = document.createElement("input");
                startTimeInput.type = "number";
                startTimeInput.min = "0";
                startTimeInput.value = String(this.startTime);
                Object.assign(startTimeInput.style, {
                    width: "100px",
                    padding: "8px 12px",
                    borderRadius: "6px",
                    border: "1px solid var(--border, #ddd)",
                    fontSize: "14px",
                });
                startTimeGroup.append(startTimeLabel, startTimeInput);
                container.appendChild(startTimeGroup);
            },
            save: () => ({
                autoplay: autoplayCheckbox?.checked ?? this.autoplay,
                controls: controlsCheckbox?.checked ?? this.controls,
                loop: loopCheckbox?.checked ?? this.loop,
                muted: mutedCheckbox?.checked ?? this.muted,
                startTime: parseInt(startTimeInput?.value, 10) || 0,
            }),
        };
    }
}
//# sourceMappingURL=video-widget.js.map