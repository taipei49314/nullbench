export const AGENTS = {
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
  { id: "decision", label: "即時裁決" },
  { id: "history", label: "歷史回放" },
  { id: "council", label: "Agent 議會" },
  { id: "research", label: "策略實驗" },
  { id: "verification", label: "驗證" },
];

export const GAME_LABELS = {
  super: "威力彩",
  lotto649: "大樂透",
};

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

export function getAgentSeries(agentId, proposals, rating) {
  const seed = proposals
    .flatMap((proposal) => proposal.numbers)
    .reduce((total, number, index) => total + number * (index + 3), 0);
  return Array.from({ length: 30 }, (_, index) => {
    const wave = Math.sin((index + seed % 11) * 0.62) * 11;
    const trend = (rating - 0.5) * 26 + index * 0.62;
    const persona =
      agentId === "hot_hunter"
        ? Math.cos(index * 0.25) * 8
        : agentId === "cold_keeper"
          ? Math.sin(index * 0.18) * 6
          : 0;
    return Math.max(8, Math.min(96, 24 + wave + trend + persona));
  });
}
