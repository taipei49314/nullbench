const HYPOTHESES = [
  "independent_null",
  "temporal_dependency",
  "regime_shift",
  "structural_bias",
  "overfit_guard",
];

function buildDecision(game, pool) {
  const proposals = Array.from({ length: 15 }, (_, index) => {
    const agent = HYPOTHESES[index % HYPOTHESES.length];
    return {
      proposal_id: `${agent}:${Math.floor(index / HYPOTHESES.length) + 1}`,
      agent,
      numbers: Array.from(
        { length: 6 },
        (_, offset) => ((index * 6 + offset) % pool) + 1,
      ),
      special: game === "super" ? (index % 8) + 1 : null,
    };
  });
  const candidateScores = proposals.map((proposal, index) => ({
    proposal_id: proposal.proposal_id,
    debate_score: Number((0.9 - index * 0.01).toFixed(8)),
  }));

  return {
    game,
    target: {
      period: "202600001",
      date: "2026-08-20",
    },
    decision_hash: "a".repeat(64),
    proposals,
    critiques: [],
    hypotheses: HYPOTHESES.map((id) => ({
      id,
      thesis: `${id} fixture thesis`,
      main_probabilities: Array.from({ length: pool }, () => 6 / pool),
    })),
    selected_tickets: proposals.slice(0, 5).map((proposal, index) => ({
      slot: index + 1,
      numbers: proposal.numbers,
      special: proposal.special,
    })),
    adjudication: {
      candidate_scores: candidateScores,
      ranking: candidateScores.slice(0, 5).map((row) => ({
        proposal_id: row.proposal_id,
        final_score: row.debate_score,
      })),
      judge: {
        model: "fixture",
        source: "committed-test-fixture",
        summary: "Deterministic test decision.",
      },
    },
  };
}

function buildGame(game, pool) {
  return {
    final_state: {
      agents: Object.fromEntries(
        HYPOTHESES.map((id, index) => [
          id,
          {
            rating: 1 - index * 0.05,
            blind_evidence: {
              mean_skill_vs_h0: 0,
              confidence_interval_95: [0, 0],
              evidence_wins: 0,
            },
          },
        ]),
      ),
    },
    next_decision: buildDecision(game, pool),
  };
}

export const manifestFixture = {
  games: {
    super: buildGame("super", 38),
    lotto649: buildGame("lotto649", 49),
  },
};
