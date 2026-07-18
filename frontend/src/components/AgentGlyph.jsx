import {
  Dices,
  Flame,
  Orbit,
  Scale,
  Snowflake,
} from "lucide-react";

const ICONS = {
  hot_hunter: Flame,
  cold_keeper: Snowflake,
  balance_engineer: Scale,
  antipop_taoist: Orbit,
  random_monk: Dices,
};

export default function AgentGlyph({ agentId, size = 22 }) {
  const Icon = ICONS[agentId] ?? Orbit;
  return <Icon aria-hidden="true" size={size} strokeWidth={1.6} />;
}
