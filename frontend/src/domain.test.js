import { describe, expect, it } from "vitest";

import {
  buildProbabilityFirstPortfolio,
  formatDate,
  formatNumbers,
  getAgentSeries,
  getDebateSequence,
  getProbabilityFirstPortfolio,
  hasRevealedDecision,
  getOrderedAgents,
  getProposalMap,
  getRankingMap,
} from "./domain";
import { manifestFixture } from "./test-fixtures/manifest";

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

describe("probability-first portfolio", () => {
  const manifest = manifestFixture;

  it.each(["super", "lotto649"])(
    "keeps the rolling coverage contract deterministic for %s",
    (game) => {
    const portfolio = buildProbabilityFirstPortfolio(
      manifest.games[game].next_decision,
      game,
    );
    const replayed = buildProbabilityFirstPortfolio(
      manifest.games[game].next_decision,
      game,
    );

    expect(portfolio).toEqual(replayed);
    expect(portfolio.tickets).toHaveLength(5);
    expect(
      portfolio.tickets.every(
        (ticket) =>
          ticket.numbers.length === 6 &&
          ticket.numbers.every(
            (number) =>
              Number.isInteger(number) &&
              number >= 1 &&
              number <= (game === "super" ? 38 : 49),
          ),
      ),
    ).toBe(true);
    expect(portfolio.main_union_size).toBe(30);
    expect(portfolio.maximum_pairwise_main_overlap).toBe(0);
    expect(new Set(portfolio.tickets.flatMap((ticket) => ticket.numbers)).size)
      .toBe(30);
    if (game === "super") {
      expect(new Set(portfolio.selected_specials).size).toBe(5);
    }
    },
  );

  it("fails closed to the redacted Qwen payload before debate reveal", () => {
    const publicDecision = {
      ...manifest.games.super.next_decision,
      selected_tickets: [],
      adjudication: {
        ...manifest.games.super.next_decision.adjudication,
        candidate_scores: [],
      },
    };

    const portfolio = getProbabilityFirstPortfolio(publicDecision, "super");

    expect(portfolio.fallback_to_qwen).toBe(true);
    expect(portfolio.tickets).toEqual([]);
    expect(portfolio.fallback_reason).toContain("完整15組提案");
  });

  it("rejects scores outside the backend eight-decimal reproducibility contract", () => {
    const decision = structuredClone(
      manifest.games.super.next_decision,
    );
    decision.adjudication.candidate_scores[0].debate_score += 0.000000001;

    expect(() =>
      buildProbabilityFirstPortfolio(decision, "super"),
    ).toThrow("8位小數契約");
  });
});
