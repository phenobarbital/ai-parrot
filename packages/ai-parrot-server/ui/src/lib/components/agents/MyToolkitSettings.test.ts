import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import MyToolkitSettings from "./MyToolkitSettings.svelte";

const getAgentToolkits = vi.fn();
const getMyToolkitOverride = vi.fn();
const getToolkitSchema = vi.fn();
const putMyToolkitOverride = vi.fn();
const deleteMyToolkitOverride = vi.fn();

vi.mock("$lib/api/studio", () => ({
  getAgentToolkits: (...args: unknown[]) => getAgentToolkits(...args),
  getMyToolkitOverride: (...args: unknown[]) => getMyToolkitOverride(...args),
  getToolkitSchema: (...args: unknown[]) => getToolkitSchema(...args),
  putMyToolkitOverride: (...args: unknown[]) => putMyToolkitOverride(...args),
  deleteMyToolkitOverride: (...args: unknown[]) => deleteMyToolkitOverride(...args),
}));

describe("MyToolkitSettings", () => {
  beforeEach(() => {
    getAgentToolkits.mockReset();
    getMyToolkitOverride.mockReset();
    getToolkitSchema.mockReset();
    putMyToolkitOverride.mockReset();
    deleteMyToolkitOverride.mockReset();
  });

  test("only toolkits with overridable params are listed", async () => {
    getAgentToolkits.mockResolvedValue({
      agent: "agent-1",
      editable: true,
      toolkits: [{ slug: "wiki" }, { slug: "dataset_manager" }],
    });
    getMyToolkitOverride.mockImplementation(async (_agentId: string, slug: string) => {
      if (slug === "wiki") {
        return { slug, overridable: [], params: {}, configured: false };
      }
      return { slug, overridable: ["max_rows"], params: { max_rows: 50 }, configured: true };
    });
    getToolkitSchema.mockResolvedValue({
      class_name: "DatasetManager",
      slug: "dataset_manager",
      source: "model",
      schema: {
        type: "object",
        properties: {
          max_rows: { type: "integer", minimum: 1, maximum: 1000 },
        },
      },
    });

    render(MyToolkitSettings, { agentId: "agent-1" });

    await waitFor(() => {
      expect(screen.getByText("dataset_manager")).toBeInTheDocument();
    });
    expect(screen.queryByText("wiki")).not.toBeInTheDocument();
    expect(
      screen.queryByText("No tool settings you can change for this agent"),
    ).not.toBeInTheDocument();
  });

  test("shows the empty state when no toolkit has overridable params", async () => {
    getAgentToolkits.mockResolvedValue({
      agent: "agent-1",
      editable: true,
      toolkits: [{ slug: "wiki" }],
    });
    getMyToolkitOverride.mockResolvedValue({
      slug: "wiki",
      overridable: [],
      params: {},
      configured: false,
    });

    render(MyToolkitSettings, { agentId: "agent-1" });

    await waitFor(() => {
      expect(
        screen.getByText("No tool settings you can change for this agent"),
      ).toBeInTheDocument();
    });
    expect(getToolkitSchema).not.toHaveBeenCalled();
  });

  test("save calls putMyToolkitOverride with the edited value", async () => {
    getAgentToolkits.mockResolvedValue({
      agent: "agent-1",
      editable: true,
      toolkits: [{ slug: "dataset_manager" }],
    });
    getMyToolkitOverride.mockResolvedValue({
      slug: "dataset_manager",
      overridable: ["note"],
      params: { note: "hello" },
      configured: true,
    });
    getToolkitSchema.mockResolvedValue({
      class_name: "DatasetManager",
      slug: "dataset_manager",
      source: "model",
      schema: {
        type: "object",
        properties: {
          note: { type: "string" },
        },
      },
    });
    putMyToolkitOverride.mockResolvedValue({ agent: "agent-1", slug: "dataset_manager", persisted: true });

    render(MyToolkitSettings, { agentId: "agent-1" });

    const noteInput = await screen.findByTestId("schema-form-text-note");
    await fireEvent.input(noteInput, { target: { value: "updated" } });

    const saveButton = await screen.findByRole("button", { name: /save/i });
    await fireEvent.click(saveButton);

    await waitFor(() => {
      expect(putMyToolkitOverride).toHaveBeenCalledWith("agent-1", "dataset_manager", {
        params: { note: "updated" },
      });
    });
  });

  test("reset calls deleteMyToolkitOverride for the toolkit", async () => {
    getAgentToolkits.mockResolvedValue({
      agent: "agent-1",
      editable: true,
      toolkits: [{ slug: "dataset_manager" }],
    });
    getMyToolkitOverride.mockResolvedValue({
      slug: "dataset_manager",
      overridable: ["note"],
      params: { note: "hello" },
      configured: true,
    });
    getToolkitSchema.mockResolvedValue({
      class_name: "DatasetManager",
      slug: "dataset_manager",
      source: "model",
      schema: {
        type: "object",
        properties: {
          note: { type: "string" },
        },
      },
    });
    deleteMyToolkitOverride.mockResolvedValue({ agent: "agent-1", slug: "dataset_manager", persisted: false });

    render(MyToolkitSettings, { agentId: "agent-1" });

    const resetButton = await screen.findByRole("button", { name: /reset/i });
    await fireEvent.click(resetButton);

    await waitFor(() => {
      expect(deleteMyToolkitOverride).toHaveBeenCalledWith("agent-1", "dataset_manager");
    });
  });
});
