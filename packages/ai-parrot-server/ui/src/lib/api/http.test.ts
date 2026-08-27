import { describe, expect, it } from "vitest";

import { extractServerMessage } from "./http";

// Adapted verbatim from navigator-frontend-next's src/lib/api/http.test.ts
// (TASK-2527) — extractServerMessage's logic is unchanged from the source.
describe("extractServerMessage", () => {
  it("prefers data.error", () => {
    expect(extractServerMessage({ error: "boom" }, 500)).toBe("boom");
  });
  it("falls back to nested message.message", () => {
    expect(extractServerMessage({ message: { message: "nested" } }, 500)).toBe("nested");
  });
  it("accepts flat message string", () => {
    expect(extractServerMessage({ message: "flat" }, 500)).toBe("flat");
  });
  it("accepts detail (FastAPI/DRF)", () => {
    expect(extractServerMessage({ detail: "drf" }, 500)).toBe("drf");
  });
  it("falls back to HTTP status for null", () => {
    expect(extractServerMessage(null, 500)).toBe("HTTP 500");
  });
  it("falls back to HTTP status for empty object", () => {
    expect(extractServerMessage({}, 500)).toBe("HTTP 500");
  });
  it("handles FastAPI 422 detail array (first msg)", () => {
    expect(
      extractServerMessage(
        {
          detail: [
            { loc: ["body", "datasource"], msg: "field required", type: "value_error.missing" },
          ],
        },
        422,
      ),
    ).toBe("field required");
  });
  it("falls back for empty detail array", () => {
    expect(extractServerMessage({ detail: [] }, 422)).toBe("HTTP 422");
  });
});
