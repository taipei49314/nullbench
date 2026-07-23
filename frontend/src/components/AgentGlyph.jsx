import {
  CircleDot,
  Dices,
  Flame,
  Network,
  Orbit,
  Scale,
  ShieldCheck,
  Snowflake,
  Waves,
  Waypoints,
} from "lucide-react";

const ICONS = {
  independent_null: CircleDot,
  temporal_dependency: Waves,
  regime_shift: Waypoints,
  structural_bias: Network,
  overfit_guard: ShieldCheck,
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
