import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import ResearchView from "./ResearchView";

const agentRows = ["antipop_taoist", "balance_engineer"].map(
  (agent, index) => ({
    game: "super",
    split: "holdout",
    agent,
    agent_name: index ? "均衡工程師" : "反眾道人",
    proposal_mean_main_hits: 0.93 + index * 0.01,
    unique_candidate_numbers: 2.1,
    selected_ticket_share: 0.3,
    leaveout_delta_best_main_hits: 0,
    replacement_delta_best_main_hits: index ? -0.01 : 0.0766,
    replacement_delta_best_main_hits_ci_low: index ? -0.04 : 0.0089,
    replacement_delta_best_main_hits_ci_high: index ? 0.02 : 0.139,
    replacement_delta_union_main_hits: 0.36,
    replacement_delta_union_size: 2.38,
    replacement_selection_overlap: 0.43,
    action: index ? "inconclusive" : "replacement_supported",
  }),
);

const study = {
  experiment_id: "council-quality-shadow-v1",
  generated_at: "2026-07-17T23:59:59+08:00",
  conclusion: {
    status: "retain_current_council",
    recommendation: "keep_as_shadow_only",
  },
  selected_replacements: {
    super: {
      removed_agent: "antipop_taoist",
      removed_agent_name: "反眾道人",
      candidate_agent_name: "覆蓋稽核員",
      holdout: agentRows[0],
    },
  },
  agent_quality: agentRows,
  critic_quality: [
    {
      game: "super",
      split: "holdout",
      critic: "random_monk",
      critic_name: "亂數修士",
      score_std: 0,
      pearson_score_to_actual: null,
      top_quartile_actual_lift: 0,
    },
  ],
  critic_pair_redundancy: [
    {
      game: "super",
      split: "holdout",
      left_critic: "hot_hunter",
      right_critic: "cold_keeper",
      left_name: "熱手獵人",
      right_name: "冷灶守望者",
      score_correlation: 0.1,
      mean_absolute_score_gap: 0.2,
    },
  ],
  judge_sensitivity: [
    {
      game: "super",
      split: "holdout",
      variant: "diversity_off",
      variant_label: "五注重疊懲罰關閉",
      selection_overlap: 0.86,
      exact_selection_rate: 0.43,
      delta_best_main_hits: -0.0267,
      delta_union_main_hits: -0.1729,
    },
  ],
  recent_holdout_trace: {
    super: [
      {
        date: "2026-07-16",
        period: 115000057,
        baseline_best_main_hits: 2,
        replacement_best_main_hits: 3,
        baseline_union_main_hits: 4,
        replacement_union_main_hits: 5,
        selection_overlap: 0.4,
      },
    ],
  },
};

describe("ResearchView", () => {
  it("renders the frozen holdout result and interactive research controls", () => {
    const html = renderToStaticMarkup(
      <ResearchView
        activeGame="super"
        onGameChange={() => {}}
        study={study}
      />,
    );

    expect(html).toContain("影子策略實驗室");
    expect(html).toContain("SHADOW ONLY · NOT PROMOTED");
    expect(html).toContain("反眾道人");
    expect(html).toContain("覆蓋稽核員");
    expect(html).toContain("+0.0766");
    expect(html).toContain("115000057");
    expect(html).toContain("評論校準");
    expect(html).toContain("JUDGE SENSITIVITY");
    expect(html).toContain("五注重疊懲罰關閉");
    expect(html).toContain("正式五席維持不變");
  });
});
