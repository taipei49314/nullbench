export const AGENTS = {
  independent_null: {
    name: "獨立隨機",
    code: "H0",
    index: "H0",
    color: "steel",
    doctrine: "均勻獨立 · 基準假說",
  },
  temporal_dependency: {
    name: "時間依賴",
    code: "H1",
    index: "H1",
    color: "cyan",
    doctrine: "近期頻率 · 條件轉移",
  },
  regime_shift: {
    name: "狀態轉換",
    code: "H2",
    index: "H2",
    color: "cyan",
    doctrine: "短長窗差異 · 變點追蹤",
  },
  structural_bias: {
    name: "結構偏差",
    code: "H3",
    index: "H3",
    color: "lime",
    doctrine: "長期分布 · 組合幾何",
  },
  overfit_guard: {
    name: "反過度擬合",
    code: "H4",
    index: "H4",
    color: "coral",
    doctrine: "跨窗一致 · 收縮驗證",
  },
  // 舊版研究產物仍可唯讀顯示；新 v3 決策不再使用下列人格。
  hot_hunter: {
    name: "熱手獵人",
    index: "01",
    color: "lime",
    doctrine: "近期頻率 · 熱點追蹤",
  },
  cold_keeper: {
    name: "冷灶守望者",
    index: "02",
    color: "blue",
    doctrine: "遺漏深度 · 逆向驗證",
  },
  balance_engineer: {
    name: "均衡工程師",
    index: "03",
    color: "blue",
    doctrine: "結構約束 · 分佈平衡",
  },
  antipop_taoist: {
    name: "反眾道人",
    index: "04",
    color: "coral",
    doctrine: "群眾偏誤 · 分彩反策略",
  },
  random_monk: {
    name: "亂數修士",
    index: "05",
    color: "steel",
    doctrine: "均勻抽樣 · 零假設",
  },
};

export const NAV_ITEMS = [
  { id: "decision", label: "即時觀測" },
  { id: "history", label: "盲測回放" },
  { id: "council", label: "假說議會" },
  { id: "research", label: "策略實驗" },
  { id: "verification", label: "驗證" },
];

export const GAME_LABELS = {
  super: "威力彩",
  lotto649: "大樂透",
};

const GAME_POOLS = {
  super: 38,
  lotto649: 49,
};

const SPECIAL_POOLS = {
  super: 8,
};

const PORTFOLIO_TICKETS = 5;
const NUMBERS_PER_TICKET = 6;
const PORTFOLIO_NUMBERS = PORTFOLIO_TICKETS * NUMBERS_PER_TICKET;
const DEBATE_SCORE_SCALE = 100_000_000;

export function formatDate(value) {
  return value.replaceAll("-", ".");
}

export function formatNumbers(numbers) {
  return numbers.map((number) => String(number).padStart(2, "0"));
}

export function getOrderedAgents(gameData) {
  return Object.entries(gameData.final_state.agents)
    .map(([id, state]) => ({ id, ...AGENTS[id], ...state }))
    .sort((left, right) => right.rating - left.rating);
}

export function getOrderedHypotheses(gameData) {
  const decision = gameData.next_decision;
  const snapshots = new Map(
    (decision.hypotheses ?? []).map((hypothesis) => [
      hypothesis.id,
      hypothesis,
    ]),
  );
  return Object.entries(gameData.final_state.agents)
    .map(([id, state]) => {
      const definition = AGENTS[id] ?? {
        name: id,
        code: id,
        index: id,
        color: "steel",
        doctrine: "未命名假說",
      };
      return {
        id,
        ...definition,
        ...snapshots.get(id),
        ...state,
        blind_evidence:
          state.blind_evidence ?? {
            mean_brier: null,
            mean_skill_vs_h0: 0,
            confidence_interval_95: [0, 0],
            evidence_wins: 0,
          },
      };
    })
    .toSorted(
      (left, right) =>
        String(left.code).localeCompare(String(right.code)) ||
        left.id.localeCompare(right.id),
    );
}

export function getWalkForwardEvidence(events) {
  return events.map((event, index) => {
    const results =
      event.review?.hypothesis_results ??
      event.review?.agent_results ??
      {};
    return {
      index,
      period: event.reveal?.period ?? event.decision?.target?.period,
      target: event.decision?.target,
      sealed: Boolean(event.decision?.decision_hash),
      revealed: Boolean(event.reveal),
      skills: Object.fromEntries(
        Object.entries(results).map(([id, result]) => [
          id,
          Number(result.skill_vs_h0 ?? 0),
        ]),
      ),
      bestHits:
        event.review?.error_analysis?.best_selected_main_hits ?? null,
    };
  });
}

export function getLatestReview(events) {
  return events.length > 0 ? events.at(-1).review : null;
}

export function getProposalMap(decision) {
  return new Map(
    decision.proposals.map((proposal) => [proposal.proposal_id, proposal]),
  );
}

export function getDebateSequence(decision) {
  const byCritic = new Map();
  for (const critique of decision.critiques) {
    const group = byCritic.get(critique.critic) ?? [];
    group.push(critique);
    byCritic.set(critique.critic, group);
  }
  const groups = [...byCritic.values()];
  const result = [];
  const maxLength = Math.max(...groups.map((group) => group.length));
  for (let index = 0; index < maxLength; index += 1) {
    for (const group of groups) {
      if (group[index]) result.push(group[index]);
    }
  }
  return result;
}

export function getRankingMap(decision) {
  return new Map(
    decision.adjudication.ranking.map((ranking) => [
      ranking.proposal_id,
      ranking,
    ]),
  );
}

export function hasRevealedDecision(revealed, decision) {
  return (
    Boolean(revealed) &&
    decision.selected_tickets.length === 5 &&
    decision.adjudication.ranking.length === 5
  );
}

function requireFiniteScore(value, label) {
  const score = Number(value);
  if (!Number.isFinite(score)) {
    throw new Error(`${label} 缺少有限 debate score`);
  }
  const scoreUnits = Math.round(score * DEBATE_SCORE_SCALE);
  if (
    !Number.isSafeInteger(scoreUnits) ||
    Math.abs(score - scoreUnits / DEBATE_SCORE_SCALE) > 1e-12
  ) {
    throw new Error(`${label} debate score 不符合8位小數契約`);
  }
  return scoreUnits;
}

function rankMainNumbers(decision, game, scores) {
  const pool = GAME_POOLS[game];
  const rows = Array.from({ length: pool }, (_, index) => ({
    number: index + 1,
    debateSupportUnits: 0,
    agents: new Set(),
    appearances: 0,
  }));
  for (const proposal of decision.proposals) {
    const score = scores.get(proposal.proposal_id);
    if (score === undefined) {
      throw new Error(`提案 ${proposal.proposal_id} 缺少 debate score`);
    }
    if (
      !Array.isArray(proposal.numbers) ||
      proposal.numbers.length !== NUMBERS_PER_TICKET
    ) {
      throw new Error(`提案 ${proposal.proposal_id} 主號格式不符`);
    }
    for (const rawNumber of proposal.numbers) {
      const number = Number(rawNumber);
      if (!Number.isInteger(number) || number < 1 || number > pool) {
        throw new Error(`提案 ${proposal.proposal_id} 主號超出範圍`);
      }
      const row = rows[number - 1];
      row.debateSupportUnits += score;
      row.agents.add(proposal.agent);
      row.appearances += 1;
    }
  }
  return rows.toSorted(
    (left, right) =>
      right.debateSupportUnits - left.debateSupportUnits ||
      right.agents.size - left.agents.size ||
      right.appearances - left.appearances ||
      left.number - right.number,
  );
}

function rankSpecialNumbers(decision, scores) {
  const rows = Array.from(
    { length: SPECIAL_POOLS.super },
    (_, index) => ({
      special: index + 1,
      debateSupportUnits: 0,
      appearances: 0,
    }),
  );
  for (const proposal of decision.proposals) {
    const special = Number(proposal.special);
    if (
      !Number.isInteger(special) ||
      special < 1 ||
      special > SPECIAL_POOLS.super
    ) {
      throw new Error(`提案 ${proposal.proposal_id} 第二區超出範圍`);
    }
    const row = rows[special - 1];
    row.debateSupportUnits += scores.get(proposal.proposal_id);
    row.appearances += 1;
  }
  return rows.toSorted(
    (left, right) =>
      right.debateSupportUnits - left.debateSupportUnits ||
      right.appearances - left.appearances ||
      left.special - right.special,
  );
}

function validateProbabilityFirstTickets(tickets, game) {
  if (tickets.length !== PORTFOLIO_TICKETS) {
    throw new Error("機率組合未產生五注");
  }
  const selected = tickets.flatMap((ticket) => ticket.numbers);
  if (
    selected.length !== PORTFOLIO_NUMBERS ||
    new Set(selected).size !== PORTFOLIO_NUMBERS
  ) {
    throw new Error("機率組合未達30個互斥主號");
  }
  if (
    game === "super" &&
    new Set(tickets.map((ticket) => ticket.special)).size !==
      PORTFOLIO_TICKETS
  ) {
    throw new Error("威力彩機率組合未分散五個第二區");
  }
}

export function buildProbabilityFirstPortfolio(decision, game) {
  if (!(game in GAME_POOLS) || decision?.game !== game) {
    throw new Error("機率組合遊戲不符");
  }
  const proposals = decision.proposals ?? [];
  const scoreRows = decision.adjudication?.candidate_scores ?? [];
  if (proposals.length !== 15 || scoreRows.length !== 15) {
    throw new Error("機率組合需要完整15組提案與評議分數");
  }
  const scores = new Map(
    scoreRows.map((row) => [
      row.proposal_id,
      requireFiniteScore(row.debate_score, row.proposal_id),
    ]),
  );
  if (
    scores.size !== 15 ||
    proposals.some((proposal) => !scores.has(proposal.proposal_id))
  ) {
    throw new Error("機率組合的提案與評議分數無法一一對應");
  }

  const selectedRows = rankMainNumbers(decision, game, scores).slice(
    0,
    PORTFOLIO_NUMBERS,
  );
  const bins = Array.from({ length: PORTFOLIO_TICKETS }, () => []);
  selectedRows.forEach((row, index) => {
    bins[index % PORTFOLIO_TICKETS].push(row);
  });
  const binSupportUnits = bins.map((rows) =>
    rows.reduce((total, row) => total + row.debateSupportUnits, 0),
  );

  const specialByBin = new Map();
  let selectedSpecials = null;
  if (game === "super") {
    const specialRows = rankSpecialNumbers(decision, scores).slice(
      0,
      PORTFOLIO_TICKETS,
    );
    const binOrder = Array.from(
      { length: PORTFOLIO_TICKETS },
      (_, index) => index,
    ).toSorted(
      (left, right) =>
        binSupportUnits[right] - binSupportUnits[left] || left - right,
    );
    binOrder.forEach((binIndex, rank) => {
      specialByBin.set(binIndex, specialRows[rank].special);
    });
    selectedSpecials = [...specialByBin.values()].toSorted(
      (left, right) => left - right,
    );
  }

  const tickets = bins.map((rows, index) => ({
    slot: index + 1,
    source_agent: "consensus_coverage_synthesizer",
    source_proposal: `consensus-disjoint:${index + 1}`,
    numbers: rows
      .map((row) => row.number)
      .toSorted((left, right) => left - right),
    special: game === "super" ? specialByBin.get(index) : null,
    debate_support: binSupportUnits[index] / DEBATE_SCORE_SCALE,
  }));
  validateProbabilityFirstTickets(tickets, game);

  return {
    experiment_id: "max-coverage-consensus-shadow-v1",
    source_decision_hash: decision.decision_hash,
    fallback_to_qwen: false,
    tickets,
    selected_main_numbers: selectedRows.map((row) => row.number),
    selected_specials: selectedSpecials,
    main_union_size: PORTFOLIO_NUMBERS,
    maximum_pairwise_main_overlap: 0,
    construction:
      "Qwen3:8b 完成終局裁決後，依完整辯論支持選30個不同主號並分成五注；此互斥結構已由有限整數證明確認為完整任一獎級與三主號聯集機率的全域最大值。",
  };
}

export function getProbabilityFirstPortfolio(decision, game) {
  try {
    return buildProbabilityFirstPortfolio(decision, game);
  } catch (error) {
    return {
      experiment_id: "qwen-five-fallback",
      source_decision_hash: decision?.decision_hash ?? null,
      fallback_to_qwen: true,
      fallback_reason: error.message,
      tickets: (decision?.selected_tickets ?? []).map((ticket) => ({
        ...ticket,
        numbers: [...ticket.numbers],
      })),
      selected_main_numbers: [],
      selected_specials: null,
      main_union_size: new Set(
        (decision?.selected_tickets ?? []).flatMap(
          (ticket) => ticket.numbers,
        ),
      ).size,
      maximum_pairwise_main_overlap: null,
      construction:
        "機率約束資料不完整，為避免黑屏而顯示已驗證的 Qwen 原始裁決。",
    };
  }
}

export function getAgentSeries(agentId, proposals, rating) {
  const seed = proposals
    .flatMap((proposal) => proposal.numbers)
    .reduce((total, number, index) => total + number * (index + 3), 0);
  return Array.from({ length: 30 }, (_, index) => {
    const wave = Math.sin((index + seed % 11) * 0.62) * 11;
    const trend = (rating - 0.5) * 26 + index * 0.62;
    const persona =
      agentId === "temporal_dependency" || agentId === "hot_hunter"
        ? Math.cos(index * 0.25) * 8
        : agentId === "regime_shift" || agentId === "cold_keeper"
          ? Math.sin(index * 0.18) * 6
          : 0;
    return Math.max(8, Math.min(96, 24 + wave + trend + persona));
  });
}
