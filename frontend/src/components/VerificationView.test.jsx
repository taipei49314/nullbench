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
      experiment_id: "agent-loop-v3-unknown-generator",
      forward_experiment: {
        evidence_status: "collecting_forward_data",
        verification: { chain_valid: true },
        methodology: {
          minimum_paired_draws_per_game: 52,
          monitoring_checkpoints: [52, 104, 208, 416, 832],
        },
        qwen_joint_sequential_monitor: {
          protocol_id: "forward-sequential-monitoring-v2",
          observed_pairs_by_game: { super: 3, lotto649: 0 },
          common_observed_pairs: 0,
          evaluated_pairs_per_game: 0,
          next_checkpoint: 52,
          status: "collecting_forward_data",
        },
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
              sequential_monitor: {
                observed_pairs: 3,
                evaluated_pairs: 0,
                next_checkpoint: 104,
                status: "collecting_before_first_checkpoint",
              },
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
    const goalAudit = {
      status: "incomplete",
      audit_state: "waiting",
      failures: [
        "super:settlement_missing",
        "super:next_registration_missing",
        "lotto649:settlement_missing",
        "lotto649:next_registration_missing",
      ],
      games: {
        super: {
          initial_target: {
            date: "2026-07-20",
            period: 115000058,
          },
          initial_registration_hash:
            "e3c4b0d067fa8208158025356d51496e4376ffcaf657a4a89905744234a493d1",
          initial_registration_present: true,
          settlement_present: false,
          next_pending_target: null,
          feedback_status: null,
          feedback_hash: null,
        },
        lotto649: {
          initial_target: {
            date: "2026-07-21",
            period: 115000072,
          },
          initial_registration_hash:
            "8991e28e95bb2e02c790049a4633c648c6f26bd0a3d620c792a3c8e3e3a1e4d9",
          initial_registration_present: true,
          settlement_present: false,
          next_pending_target: null,
          feedback_status: null,
          feedback_hash: null,
        },
      },
    };

    const html = renderToStaticMarkup(
      <VerificationView
        gameData={gameData}
        goalAudit={goalAudit}
        manifest={manifest}
      />,
    );

    expect(html).toContain("FIRST FORWARD LOOP");
    expect(html).toContain("WAITING FOR OFFICIAL DRAWS");
    expect(html).toContain("REGISTRATION LOCKED");
    expect(html).toContain("2026-07-20 · 115000058");
    expect(html).toContain("2026-07-21 · 115000072");
    expect(html).toContain("e3c4b0d067fa…34a493d1");
    expect(html).toContain("8991e28e95bb…e3a1e4d9");
    expect(html).toContain("QWEN / RULE 前向 A/B");
    expect(html).toContain("CHAIN VERIFIED");
    expect(html).toContain("30 個互不重疊主號");
    expect(html).toContain("威力彩 54.2963%、大樂透 15.2966%");
    expect(html).toContain("全域最大聯集覆蓋率");
    expect(html).toContain("不是單注或頭獎機率");
    expect(html).toContain("3<i> / 52</i>");
    expect(html).toContain("本遊戲有效／共同開封");
    expect(html).toContain("不會拼接兩款遊戲在不同 checkpoint");
    expect(html).toContain("預先固定的兩遊戲共同");
    expect(html).toContain("alpha spending");
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

    const closedGoalAudit = {
      ...goalAudit,
      status: "complete",
      failures: [],
      games: {
        super: {
          ...goalAudit.games.super,
          settlement_present: true,
          next_pending_target: {
            date: "2026-07-23",
            period: 115000059,
          },
          feedback_status: "verified",
          feedback_hash: "a".repeat(64),
        },
        lotto649: {
          ...goalAudit.games.lotto649,
          settlement_present: true,
          next_pending_target: {
            date: "2026-07-24",
            period: 115000073,
          },
          feedback_status: "verified",
          feedback_hash: "b".repeat(64),
        },
      },
    };
    const closedHtml = renderToStaticMarkup(
      <VerificationView
        gameData={gameData}
        goalAudit={closedGoalAudit}
        manifest={manifest}
      />,
    );

    expect(closedHtml).toContain("CLOSED LOOP VERIFIED");
    expect(closedHtml.match(/LOOP CLOSED/g)).toHaveLength(2);
    expect(closedHtml.match(/QUALIFIED/g)).toHaveLength(2);
    expect(closedHtml).toContain("2026-07-23 · 115000059");
    expect(closedHtml).toContain("2026-07-24 · 115000073");
    expect(closedHtml).not.toContain("WAITING FOR OFFICIAL DRAWS");

    const blockedHtml = renderToStaticMarkup(
      <VerificationView
        gameData={gameData}
        goalAudit={{
          ...goalAudit,
          audit_state: "blocked",
          failures: ["watcher_heartbeat_stale"],
        }}
        manifest={manifest}
      />,
    );

    expect(blockedHtml).toContain("AUDIT BLOCKED");
    expect(blockedHtml).not.toContain("WAITING FOR OFFICIAL DRAWS");
  });
});
