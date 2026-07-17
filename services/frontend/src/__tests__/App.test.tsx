import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import App from "../App";

describe("App", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ status: "ok", service: "gateway-go" }),
      })
    );
  });

  it("renders and reaches ok state after pinging gateway", async () => {
    render(<App />);
    expect(screen.getByText("DataPrepX v2")).toBeTruthy();

    await waitFor(() => {
      expect(screen.getByTestId("health-status").textContent).toBe("ok");
    });
  });
});