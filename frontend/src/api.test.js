import { afterEach, describe, expect, it, vi } from "vitest";

import { loadDashboard } from "./api";

const payloads = {
  "/api/manifest": { manifest_hash: "manifest-sha" },
  "/api/replay/super?limit=18": { events: ["super-event"] },
  "/api/replay/lotto649?limit=18": { events: ["lotto-event"] },
  "/api/research/council-quality": { experiment_id: "quality-v1" },
  "/api/research/switching-bayes": {
    experiment_id: "switching-v2",
  },
  "/api/goal": {
    status: "incomplete",
    audit_state: "waiting",
    games: {
      super: { initial_registration_present: true },
      lotto649: { initial_registration_present: true },
    },
  },
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("loadDashboard", () => {
  it("loads the read-only Goal audit with the other dashboard sources", async () => {
    const fetch = vi.fn(async (url) => ({
      ok: true,
      json: async () => payloads[url],
    }));
    vi.stubGlobal("fetch", fetch);

    const dashboard = await loadDashboard();

    expect(fetch).toHaveBeenCalledTimes(6);
    expect(fetch.mock.calls.map(([url]) => url)).toEqual(
      expect.arrayContaining(Object.keys(payloads)),
    );
    expect(dashboard.goalAudit.status).toBe("incomplete");
    expect(dashboard.goalAudit.audit_state).toBe("waiting");
    expect(dashboard.recent.super).toEqual(["super-event"]);
    expect(dashboard.recent.lotto649).toEqual(["lotto-event"]);
    expect(dashboard.research.switchingBayes.experiment_id).toBe(
      "switching-v2",
    );
  });

  it("keeps the dashboard usable when the optional Goal audit fails", async () => {
    const fetch = vi.fn(async (url) => {
      if (url === "/api/goal") {
        return {
          ok: false,
          status: 503,
          json: async () => ({ error: "goal audit failed" }),
        };
      }
      return {
        ok: true,
        json: async () => payloads[url],
      };
    });
    vi.stubGlobal("fetch", fetch);

    const dashboard = await loadDashboard();

    expect(dashboard.goalAudit).toMatchObject({
      status: "invalid",
      failures: ["goal_audit_unavailable"],
      error: "goal audit failed",
    });
    expect(dashboard.manifest).toEqual(payloads["/api/manifest"]);
  });
});
