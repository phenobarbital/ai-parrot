// test-pdf-widget.ts
import { PdfWidget } from "./pdf-widget.js";
// Mock minimal DOM environment if needed (or just test class logic if it doesn't crash on node)
// Since the widget uses document.createElement, we need a basic DOM mock or we can only test non-DOM parts
// But wait, the environment is node, so 'document' is not defined.
// The user environment info says OS is linux.
// I can only verify if the TS compiles or if I mock document.
const mockDocument = {
    createElement: (tag) => {
        return {
            style: {},
            setAttribute: () => { },
            tagName: tag.toUpperCase(),
        };
    }
};
globalThis.document = mockDocument;
try {
    const widget = new PdfWidget({
        title: "Test PDF",
        url: "https://example.com/test.pdf"
    });
    console.log("PdfWidget instantiated successfully");
    console.log("Title:", widget.getTitle());
    console.log("Icon:", widget.getIcon());
    console.log("URL:", widget.getUrl());
    if (widget.getTitle() === "Test PDF" && widget.getIcon() === "📄") {
        console.log("SUCCESS: Default properties are correct");
    }
    else {
        console.error("FAILURE: Default properties are incorrect");
        process.exit(1);
    }
}
catch (e) {
    console.error("FAILURE: Error instantiating PdfWidget", e);
    process.exit(1);
}
//# sourceMappingURL=test-pdf-widget.js.map