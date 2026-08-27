import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import apiClient from "$lib/api/http";
import { router } from "$lib/router.svelte";

import Login from "./Login.svelte";

describe("Login", () => {
  beforeEach(() => {
    localStorage.clear();
    window.history.pushState({}, "", "/admin/login");
    router.path = "/admin/login";
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("submits credentials and navigates to the ?next target on success", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: {} });
    const postSpy = vi
      .spyOn(apiClient, "post")
      .mockResolvedValue({ data: { token: "tok-1", username: "alice" } });

    window.history.pushState({}, "", "/admin/login?next=%2Fadmin%2Fdashboard");

    const { getByLabelText, getByRole } = render(Login);

    await fireEvent.input(getByLabelText("Username"), { target: { value: "alice" } });
    await fireEvent.input(getByLabelText("Password"), { target: { value: "secret" } });
    await fireEvent.click(getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(postSpy).toHaveBeenCalled());
    await waitFor(() => expect(router.path).toBe("/admin/dashboard"));
  });

  it("submits credentials and navigates to Home when there is no ?next", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: {} });
    vi.spyOn(apiClient, "post").mockResolvedValue({ data: { token: "tok-1" } });

    const { getByLabelText, getByRole } = render(Login);
    await fireEvent.input(getByLabelText("Username"), { target: { value: "alice" } });
    await fireEvent.input(getByLabelText("Password"), { target: { value: "secret" } });
    await fireEvent.click(getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(router.path).toBe("/admin/home"));
  });

  it("renders the server's JSON error message inline on failure", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: {} });
    vi.spyOn(apiClient, "post").mockRejectedValue({
      response: { data: { message: "Invalid credentials" } },
    });

    const { getByLabelText, getByRole, findByRole } = render(Login);
    await fireEvent.input(getByLabelText("Username"), { target: { value: "alice" } });
    await fireEvent.input(getByLabelText("Password"), { target: { value: "wrong" } });
    await fireEvent.click(getByRole("button", { name: /sign in/i }));

    const alert = await findByRole("alert");
    expect(alert.textContent).toBe("Invalid credentials");
  });

  it("renders discovered providers from GET /api/v1/auth/methods", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({
      data: {
        basic: {
          name: "BasicAuth",
          uri: "/api/v1/login",
          description: "Username/password",
          icon: "",
          external: false,
          headers: { "x-auth-method": "BasicAuth" },
        },
        google: {
          name: "GoogleAuth",
          uri: "/auth/google",
          description: "Sign in with Google",
          icon: "",
          external: true,
          headers: { "x-auth-method": "GoogleAuth" },
        },
      },
    });

    const { findByText, getByLabelText } = render(Login);

    expect(await findByText("Sign in with Google")).toBeTruthy();
    // BasicAuth form is always present regardless of discovery.
    expect(getByLabelText("Username")).toBeTruthy();
  });

  it("falls back to the BasicAuth form alone when discovery fails", async () => {
    vi.spyOn(apiClient, "get").mockRejectedValue(new Error("network down"));

    const { getByLabelText, queryByTestId } = render(Login);

    await waitFor(() => expect(getByLabelText("Username")).toBeTruthy());
    expect(queryByTestId("provider-buttons")).toBeNull();
  });
});
