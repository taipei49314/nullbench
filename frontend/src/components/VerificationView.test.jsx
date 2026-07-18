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
      next_decision: {
        decision_hash: "decision-sha",
        adjudication: {
          judge: {
            feedback_provenance: {
              experiment_id: "settled-forward-feedback-v1",
              status: "verified",
              feedback_hash: "feedback-sha",
              settlement_count: 3,
              as_of_target: {
                date: "2026-07-16",
                period: 115000057,
              },
              source_postmortem_hashes: ["a", "b", "c"],
            },
          },
        },
      },
    };
    const manifest = {
      manifest_hash: "manifest-sha",
      experiment_id: "agent-loop-v2-qwen-final",
      forward_experiment: {
        evidence_status: "collecting_forward_data",
        verification: { chain_valid: true },
        methodology: { minimum_paired_draws_per_game: 52 },
        feedback_memory: {
          super: {
            settlement_count: 3,
            maximum_window: 13,
            as_of_target: {
              date: "2026-07-16",
              period: 115000057,
            },
            feedback_hash: "feedback-sha",
            aggregate: {
              mean_qwen_minus_rule_best_main_hits: -0.3333,
              latest_diagnostic_flags: [
                "qwen_below_rule_best",
                "qwen_repetition_without_hit",
              ],
            },
          },
        },
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
        operations: {
          methodology: { minimum_observations_per_game: 10 },
          deployment_gate: {
            status: "collecting_joint_evidence",
            recommendation: "keep_rule_as_control",
          },
          games: {
            super: {
              status: "collecting_operational_data",
              legacy_uninstrumented_registrations: 1,
              window_attempts: 3,
              fallback_rate: 0,
              latency_ms: { p95: 1234 },
              tokens: { mean_eval_count: 88 },
              selection: { mean_main_number_union_size: 24 },
              quality: {
                window_draws: 2,
                maximum_window_draws: 13,
                qwen_minus_rule_best_main_hits: 0.5,
                qwen_minus_random_best_main_hits: 0.25,
              },
            },
          },
        },
      },
      automation: {
        supervisor_online: true,
        watcher_state: "online",
        status: "done",
        phase: "ready",
        last_success_at: "2026-07-18T20:17:12+08:00",
        next_check_at: "2026-07-18T20:22:12+08:00",
        consecutive_failures: 0,
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
    expect(html).toContain("QWEN MODEL OBSERVATORY");
    expect(html).toContain("collecting_operational_data");
    expect(html).toContain("3<i> / 10</i>");
    expect(html).toContain("1234 ms");
    expect(html).toContain("2<i> / 13</i>");
    expect(html).toContain("0.5");
    expect(html).toContain("0.25");
    expect(html).toContain("keep_rule_as_control");
    expect(html).toContain("既有未儀器化登記：<b>1</b>筆");
    expect(html).toContain("SETTLED ERROR MEMORY");
    expect(html).toContain("CONSUMED BY QWEN");
    expect(html).toContain("3<i> / 13</i>");
    expect(html).toContain("2026-07-16 · 115000057");
    expect(html).toContain("qwen_repetition_without_hit");
    expect(html).toContain("feedback-sha");
    expect(html).toContain("桌機無人值守 LOOP");
    expect(html).toContain("AUTONOMOUS LOOP ONLINE");
    expect(html).toContain("done / ready");
    expect(html).toContain("2026-07-18 20:17:12");
    expect(html).toContain("2026-07-18 20:22:12");
  });
});
