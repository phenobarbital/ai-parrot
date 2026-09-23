import { render, screen, fireEvent } from "@testing-library/svelte";
import SchemaForm from "./SchemaForm.svelte";

describe("SchemaForm", () => {
  const mockSchema = {
    type: "object",
    properties: {
      name: { type: "string", description: "The name of the dataset" },
      enabled: { type: "boolean", "x-user-overridable": true },
      maxRows: { type: "integer", minimum: 0, maximum: 1000 },
      apiKey: { type: "string", "x-secret": true },
      tags: { type: "array", items: { type: "string" } },
      config: { type: "object" },
    },
    required: ["name"],
  };

  const mockValue = {
    name: "my-dataset",
    enabled: true,
    maxRows: 100,
    apiKey: "secret123",
    tags: ["tag1", "tag2"],
    config: { foo: "bar" },
  };

  const mockOverridable = ["enabled"];

  const mockOnchange = vi.fn();

  test("secret renders as password", () => {
    render(SchemaForm, {
      schema: mockSchema,
      value: mockValue,
      overridable: mockOverridable,
      showOverridable: true,
      onchange: mockOnchange,
    });

    const passwordInput = screen.getByTestId("schema-form-password-apiKey");
    expect(passwordInput).toHaveAttribute("type", "password");
    expect(passwordInput).toHaveAttribute("placeholder", "••••••••");
  });

  test("boolean renders as switch", () => {
    render(SchemaForm, {
      schema: mockSchema,
      value: mockValue,
      overridable: mockOverridable,
      showOverridable: true,
      onchange: mockOnchange,
    });

    const switchInput = screen.getByTestId("schema-form-switch-enabled");
    expect(switchInput).toBeInTheDocument();
  });

  test("integer renders as slider", () => {
    render(SchemaForm, {
      schema: mockSchema,
      value: mockValue,
      overridable: mockOverridable,
      showOverridable: true,
      onchange: mockOnchange,
    });

    const sliderInput = screen.getByTestId("schema-form-slider-maxRows");
    expect(sliderInput).toBeInTheDocument();
  });

  test("string renders as text input", () => {
    render(SchemaForm, {
      schema: mockSchema,
      value: mockValue,
      overridable: mockOverridable,
      showOverridable: true,
      onchange: mockOnchange,
    });

    const textInput = screen.getByTestId("schema-form-text-name");
    expect(textInput).toBeInTheDocument();
  });

  test("array of strings renders as string list editor", () => {
    render(SchemaForm, {
      schema: mockSchema,
      value: mockValue,
      overridable: mockOverridable,
      showOverridable: true,
      onchange: mockOnchange,
    });

    const listEditor = screen.getByTestId("schema-form-string-list-tags");
    expect(listEditor).toBeInTheDocument();
  });

  test("object renders as json editor", () => {
    render(SchemaForm, {
      schema: mockSchema,
      value: mockValue,
      overridable: mockOverridable,
      showOverridable: true,
      onchange: mockOnchange,
    });

    const jsonEditor = screen.getByTestId("schema-form-json-config");
    expect(jsonEditor).toBeInTheDocument();
  });

  test("oneOf kind switch swaps branch fields", () => {
    const oneOfSchema = {
      type: "object",
      properties: {
        kind: {
          type: "string",
          enum: ["query_slug", "sql"],
          "x-ui-help": "Choose the datasource kind",
        },
        query_slug: {
          type: "object",
          properties: { slug: { type: "string" } },
        },
        sql: {
          type: "object",
          properties: { query: { type: "string" } },
        },
      },
      oneOf: [
        { const: "query_slug", title: "Query Slug" },
        { const: "sql", title: "SQL" },
      ],
    };

    const oneOfValue = { kind: "query_slug", slug: "my-slug" };

    render(SchemaForm, {
      schema: oneOfSchema,
      value: oneOfValue,
      onchange: mockOnchange,
    });

    const kindSelect = screen.getByTestId("schema-form-oneof-kind-kind");
    expect(kindSelect).toBeInTheDocument();
    expect(kindSelect).toHaveValue("query_slug");

    const slugInput = screen.getByTestId("schema-form-oneof-branch-kind-query_slug");
    expect(slugInput).toBeInTheDocument();
  });

  test("options loader rejection falls back to text input", async () => {
    const optionsSchema = {
      type: "object",
      properties: {
        programs: {
          type: "string",
          "x-options": true,
        },
      },
    };

    const optionsValue = { programs: "my-program" };

    const mockOptionsLoader = vi.fn().mockRejectedValue(new Error("Options failed"));

    render(SchemaForm, {
      schema: optionsSchema,
      value: optionsValue,
      optionsLoader: mockOptionsLoader,
      onchange: mockOnchange,
    });

    const textInput = screen.getByTestId("schema-form-multi-select-programs");
    expect(textInput).toBeInTheDocument();
  });

  test("server-managed is read-only", () => {
    const serverManagedSchema = {
      type: "object",
      properties: {
        url: {
          type: "string",
          "x-server-managed": true,
          "x-ui-help": "URL is managed by the server",
        },
      },
    };

    const serverManagedValue = { url: "https://example.com" };

    render(SchemaForm, {
      schema: serverManagedSchema,
      value: serverManagedValue,
      onchange: mockOnchange,
    });

    const readOnlyText = screen.getByText("Read-only (wired by the server)");
    expect(readOnlyText).toBeInTheDocument();
  });
});
