import { describe, expect, it } from "vitest";

import { formatUploadStatus, uploadPayloadFromError } from "./upload-status";

const CLEAN = {
  files: [{ file_id: "f-1", filename: "report.docx" }],
  dataframes: [],
  errors: [],
  agent: "a",
};
const PARTIAL = {
  files: [{ file_id: "f-1", filename: "ok.csv" }],
  dataframes: ["ok"],
  errors: [{ filename: "bad.docx", error: "invalid" }],
  agent: "a",
};
const NOTHING = {
  files: [],
  dataframes: [],
  errors: [{ filename: "bad.docx", error: "invalid" }],
  agent: "a",
};

describe("formatUploadStatus", () => {
  it("formats a clean success", () => {
    const status = formatUploadStatus(CLEAN);

    expect(status.type).toBe("success");
    expect(status.message).toContain("Stored 1 file");
    expect(status.message).not.toBe("Uploaded");
  });

  it("names registered dataframes", () => {
    const status = formatUploadStatus({ ...CLEAN, dataframes: ["sales", "costs"] });

    expect(status.type).toBe("success");
    expect(status.message).toContain("registered as datasets: sales, costs");
  });

  it("reports a partial result as a warning", () => {
    const status = formatUploadStatus(PARTIAL);

    expect(status.type).toBe("warning");
    expect(status.message).toContain("Stored 1 file");
    expect(status.message).toContain("registered as dataset: ok");
    expect(status.message).toContain("bad.docx: invalid");
  });

  it("reports nothing stored as an error", () => {
    const status = formatUploadStatus(NOTHING);

    expect(status.type).toBe("error");
    expect(status.message).toContain("bad.docx: invalid");
    expect(status.message).not.toContain("HTTP 400");
  });

  it("joins several rejected files", () => {
    const status = formatUploadStatus({
      files: [],
      dataframes: [],
      errors: [
        { filename: "a.bin", error: "too large" },
        { filename: "b.bin", error: "invalid" },
      ],
    });

    expect(status.type).toBe("error");
    expect(status.message).toBe("a.bin: too large; b.bin: invalid");
  });

  it("tolerates a half-filled error entry", () => {
    const status = formatUploadStatus({ files: [], dataframes: [], errors: [{}] });

    expect(status).toEqual({ type: "error", message: "file: rejected" });
  });

  it.each([
    [null],
    [undefined],
    ["nope"],
    [7],
    [{}],
    [{ files: "x", dataframes: [], errors: [] }],
    [{ files: [], dataframes: [], errors: [] }],
  ])("never throws for %p", (bad) => {
    expect(() => formatUploadStatus(bad)).not.toThrow();
    expect(formatUploadStatus(bad)).toEqual({ type: "error", message: "Upload failed." });
  });
});

describe("uploadPayloadFromError", () => {
  it("reads the preserved response body", () => {
    const error = { message: "HTTP 400", raw: { response: { status: 400, data: NOTHING } } };

    expect(uploadPayloadFromError(error)).toBe(NOTHING);
  });

  it.each([[null], [undefined], ["nope"], [{}], [{ raw: {} }], [{ raw: { response: {} } }]])(
    "returns undefined for %p",
    (bad) => {
      expect(() => uploadPayloadFromError(bad)).not.toThrow();
      expect(uploadPayloadFromError(bad)).toBeUndefined();
    },
  );
});
