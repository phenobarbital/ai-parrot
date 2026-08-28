import { describe, expect, it } from "vitest";

import { config } from "./config";

// Regression test: config.ts used to default apiBaseUrl to the ABSOLUTE
// "http://localhost:5000", which got baked into the production bundle at
// `pnpm build` time (no PUBLIC_API_URL is set anywhere in the release
// pipeline) and pointed every API call at the wrong origin on any real
// deployment. The Admin UI is served same-origin (setup_admin_ui() mounts
// it on the same aiohttp app that serves /api/*), so the default MUST be
// relative/empty — see config.ts's DEFAULT_API comment for the full
// reasoning.
describe("config", () => {
  it("defaults apiBaseUrl to same-origin (empty), not an absolute localhost URL", () => {
    expect(config.apiBaseUrl).toBe("");
  });
});
