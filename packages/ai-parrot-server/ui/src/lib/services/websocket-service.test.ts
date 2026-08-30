import { vi, it, expect } from "vitest";
import { wsService } from "./websocket-service";

it("never opens a socket", () => {
  const spy = vi.spyOn(globalThis, "WebSocket" as any);
  wsService.subscribe("c");
  wsService.send({ a: 1 });
  const off = wsService.onMessage("t", () => {});
  off();
  wsService.disconnect();
  expect(spy).not.toHaveBeenCalled();
});
