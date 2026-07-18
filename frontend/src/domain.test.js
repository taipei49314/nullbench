import { describe, expect, it } from "vitest";

import {
  formatDate,
  formatNumbers,
  getAgentSeries,
  getDebateSequence,
  hasRevealedDecision,
  getOrderedAgents,
  getProposalMap,
  getRankingMap,
} from "./domain";

const sampleGame = {
  final_state: {
    agents: {
      hot_hunter: {
        rating: 1.2,
        reviews: 10,
        cumulative_best_main_hits: 15,
        cumulative_special_hits: 2,
      },
      cold_keeper: {
        rating: 1.5,
        reviews: 10,
        cumulative_best_main_hits: 16,
        cumulative_special_hits: 3,
      },
    },
  },
};

const sampleDecision = {
  proposals: [
    {
      proposal_id: "hot_hunter:1",
      agent: "hot_hunter",
      numbers: [2, 5, 15, 33, 36, 38],
    },
  ],
  adjudication: {
    ranking: [
      {
        proposal_id: "hot_hunter:1",
        final_score: 0.63289005,
      },
    ],
  },
};

describe("domain formatters", () => {
  it("formats dates and lottery numbers consistently", () => {
    expect(formatDate("2026-07-20")).toBe("2026.07.20");
    expect(formatNumbers([1, 9, 12, 38])).toEqual(["01", "09", "12", "38"]);
  });
});

describe("domain indexing helpers", () => {
  it("orders agents by current rating", () => {
    expect(getOrderedAgents(sampleGame).map((agent) => agent.id)).toEqual([
      "cold_keeper",
      "hot_hunter",
    ]);
  });

  it("builds proposal and adjudication maps", () => {
    expect(getProposalMap(sampleDecision).get("hot_hunter:1").numbers).toEqual([
      2, 5, 15, 33, 36, 38,
    ]);
    expect(
      getRankingMap(sampleDecision).get("hot_hunter:1").final_score,
    ).toBe(0.63289005);
  });

  it("interleaves critics without revealing one critic in a block", () => {
    const decision = {
      critiques: [
        { critic: "hot_hunter", target: "a:1" },
        { critic: "hot_hunter", target: "a:2" },
        { critic: "cold_keeper", target: "b:1" },
        { critic: "cold_keeper", target: "b:2" },
      ],
    };
    expect(
      getDebateSequence(decision).map(
        (critique) => `${critique.critic}:${critique.target}`,
      ),
    ).toEqual([
      "hot_hunter:a:1",
      "cold_keeper:b:1",
      "hot_hunter:a:2",
      "cold_keeper:b:2",
    ]);
  });

  it("creates a bounded deterministic evidence trace", () => {
    const first = getAgentSeries(
      "hot_hunter",
      sampleDecision.proposals,
      1.2,
    );
    const second = getAgentSeries(
      "hot_hunter",
      sampleDecision.proposals,
      1.2,
    );
    expect(first).toEqual(second);
    expect(first).toHaveLength(30);
    expect(first.every((value) => value >= 8 && value <= 96)).toBe(true);
  });

  it("does not keep a stale revealed state after public data is reloaded", () => {
    const publicDecision = {
      selected_tickets: [],
      adjudication: { ranking: [] },
    };
    const fullDecision = {
      selected_tickets: Array.from({ length: 5 }, (_, slot) => ({ slot })),
      adjudication: {
        ranking: Array.from({ length: 5 }, (_, rank) => ({ rank })),
      },
    };

    expect(hasRevealedDecision(true, publicDecision)).toBe(false);
    expect(hasRevealedDecision(true, fullDecision)).toBe(true);
    expect(hasRevealedDecision(false, fullDecision)).toBe(false);
  });
});
