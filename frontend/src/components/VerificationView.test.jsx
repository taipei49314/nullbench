import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import VerificationView from "./VerificationView";

describe("VerificationView forward experiment", () => {
  it("shows the preregistered Qwen/rule evidence state", () => {
    const gameData = {
      game: "super",
      ledger_sha256: "ledger-sha",
      last_event_hash: "event-sha",
      draws_replayed: 100,
      verification: { lines: 100 },
      next_decision: { decision_hash: "decision-sha" },
    };
    const manifest = {
      manifest_hash: "manifest-sha",
      experiment_id: "agent-loop-v2-qwen-final",
      forward_experiment: {
        evidence_status: "collecting_forward_data",
        verification: { chain_valid: true },
        methodology: { minimum_paired_draws_per_game: 52 },
        games: {
          super: {
            eligible_qwen_rule_pairs: 3,
            pending: [
              {
                target: { date: "2026-07-20", period: 115000058 },
              },
            ],
            qwen_vs_rule: {
              qwen_wins: 1,
              ties: 1,
              rule_wins: 1,
            },
          },
        },
      },
    };

    const html = renderToStaticMarkup(
      <VerificationView gameData={gameData} manifest={manifest} />,
    );

    expect(html).toContain("QWEN / RULE 前向 A/B");
    expect(html).toContain("CHAIN VERIFIED");
    expect(html).toContain("3<i> / 52</i>");
    expect(html).toContain("2026-07-20 · 115000058");
    expect(html).toContain("collecting_forward_data");
  });
});
