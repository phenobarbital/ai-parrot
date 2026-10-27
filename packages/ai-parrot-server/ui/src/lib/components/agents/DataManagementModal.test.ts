import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DataManagementModal from "./DataManagementModal.svelte";

const uploadAgentData = vi.fn();
const refreshAgentData = vi.fn();
const addAgentQuery = vi.fn();

// Spread the real module: the modal also mounts MCPServerTab, which eagerly
// calls getAgentMCPServers from this same module on render. Only the three
// functions this test drives are stubbed.
vi.mock("$lib/api/agent", async (importOriginal) => {
  const actual = await importOriginal<typeof import("$lib/api/agent")>();
  return {
    ...actual,
    getAgentMCPServers: vi.fn().mockResolvedValue([]),
    uploadAgentData: (...args: unknown[]) => uploadAgentData(...args),
    refreshAgentData: (...args: unknown[]) => refreshAgentData(...args),
    addAgentQuery: (...args: unknown[]) => addAgentQuery(...args),
  };
});

/** A FileList standing in for the one the picker binds; jsdom has no constructor for it. */
function fileListOf(file: File): FileList {
  return {
    0: file,
    length: 1,
    item: (i: number) => (i === 0 ? file : null),
    [Symbol.iterator]: function* () {
      yield file;
    },
  } as unknown as FileList;
}

/**
 * The dialog portals its content to document.body, so the upload controls are
 * never inside the render() container — query the document instead.
 */
function fileInput(): HTMLInputElement {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  expect(input).toBeTruthy();
  return input;
}

/** Render the modal, choose `file` in the picker and click Upload. */
async function chooseAndUpload(file: File): Promise<void> {
  render(DataManagementModal, { open: true, agentId: "my-agent" });
  const input = fileInput();

  // `bind:files` assigns back to input.files, so the stub must be writable.
  Object.defineProperty(input, "files", {
    value: fileListOf(file),
    configurable: true,
    writable: true,
  });
  await fireEvent.change(input);

  const button = screen.getByRole("button", { name: "Upload" });
  await waitFor(() => expect(button).not.toBeDisabled());
  await fireEvent.click(button);
}

describe("DataManagementModal upload", () => {
  beforeEach(() => {
    uploadAgentData.mockReset();
    refreshAgentData.mockReset();
    addAgentQuery.mockReset();
  });

  it("sends a .docx instead of blocking it", async () => {
    uploadAgentData.mockResolvedValue({
      files: [{ file_id: "f-1", filename: "report.docx" }],
      dataframes: [],
      errors: [],
      agent: "my-agent",
    });

    await chooseAndUpload(new File(["x"], "report.docx"));

    await waitFor(() => expect(uploadAgentData).toHaveBeenCalledTimes(1));
    expect(uploadAgentData.mock.calls[0][0]).toBe("my-agent");
    expect(
      screen.queryByText("Only Excel files (.xlsx, .xls) are allowed."),
    ).not.toBeInTheDocument();
  });

  it("does not restrict the picker to Excel", () => {
    render(DataManagementModal, { open: true, agentId: "my-agent" });

    expect(fileInput().getAttribute("accept")).toBeNull();
  });

  it("shows the server's report, not a fixed string", async () => {
    uploadAgentData.mockResolvedValue({
      files: [{ file_id: "f-1", filename: "sales.xlsx" }],
      dataframes: ["sales"],
      errors: [],
      agent: "my-agent",
    });

    await chooseAndUpload(new File(["x"], "sales.xlsx"));

    await waitFor(() =>
      expect(screen.getByText(/Stored 1 file/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/registered as dataset: sales/)).toBeInTheDocument();
    expect(screen.queryByText("Uploaded")).not.toBeInTheDocument();
  });

  it("shows the per-file reason behind a 400", async () => {
    uploadAgentData.mockRejectedValue({
      message: "HTTP 400",
      raw: {
        response: {
          status: 400,
          data: {
            files: [],
            dataframes: [],
            errors: [{ filename: "bad.docx", error: "invalid" }],
          },
        },
      },
    });

    await chooseAndUpload(new File(["x"], "bad.docx"));

    await waitFor(() =>
      expect(screen.getByText(/bad\.docx: invalid/)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/HTTP 400/)).not.toBeInTheDocument();
  });

  it("falls back to the error message when there is no body", async () => {
    uploadAgentData.mockRejectedValue({ message: "Network unavailable" });

    await chooseAndUpload(new File(["x"], "report.docx"));

    await waitFor(() =>
      expect(screen.getByText("Network unavailable")).toBeInTheDocument(),
    );
  });
});
