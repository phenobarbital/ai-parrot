// url-widget.ts - Abstract base class for URL-based widgets
import { Widget } from "./widget.js";
/**
 * Abstract base class for widgets that display content from a URL.
 * Subclasses: IFrameWidget, ImageWidget
 */
export class UrlWidget extends Widget {
    url = "";
    constructor(opts) {
        // Set URL BEFORE calling super, because super calls onInit
        // We use Object.defineProperty trick to make it available early
        const url = opts.url ?? "";
        console.log("[UrlWidget] constructor opts.url:", opts.url, "-> url:", url);
        super(opts);
        this.url = url;
        console.log("[UrlWidget] after super, this.url:", this.url);
    }
    /** Set the URL and update content */
    setUrl(url) {
        this.url = url;
        this.updateContent();
    }
    /** Get current URL */
    getUrl() {
        return this.url;
    }
    /** Override to add URL config tab */
    getConfigTabs() {
        return [this.createUrlConfigTab()];
    }
    /** Apply URL config on save */
    onConfigSave(config) {
        super.onConfigSave(config);
        if (config.url && typeof config.url === "string") {
            this.setUrl(config.url);
        }
    }
    /** Create the URL configuration tab */
    createUrlConfigTab() {
        let urlInput;
        return {
            id: "url",
            label: "URL",
            icon: "🔗",
            render: (container) => {
                container.innerHTML = "";
                const urlGroup = document.createElement("div");
                Object.assign(urlGroup.style, { marginBottom: "16px" });
                const urlLabel = document.createElement("label");
                urlLabel.textContent = "URL";
                Object.assign(urlLabel.style, {
                    display: "block",
                    marginBottom: "6px",
                    fontSize: "13px",
                    fontWeight: "500",
                    color: "var(--text, #333)",
                });
                urlInput = document.createElement("input");
                urlInput.type = "text";
                urlInput.value = this.url;
                urlInput.placeholder = "https://example.com";
                Object.assign(urlInput.style, {
                    width: "100%",
                    padding: "10px 12px",
                    borderRadius: "6px",
                    border: "1px solid var(--border, #ddd)",
                    fontSize: "14px",
                    boxSizing: "border-box",
                });
                urlGroup.append(urlLabel, urlInput);
                container.appendChild(urlGroup);
            },
            save: () => ({
                url: urlInput?.value ?? this.url,
            }),
        };
    }
}
//# sourceMappingURL=url-widget.js.map