import fs from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import MechanismObservatory from "./MechanismObservatory";

const manifest = JSON.parse(
  fs.readFileSync(
    new URL(
      "../../../simulation/results/manifest.json",
      import.meta.url,
    ),
    "utf8",
  ),
);
const gameData = manifest.games.super;
const commonProps = {
  activeGame: "super",
  gameData,
  onDecisionReveal: () => Promise.resolve(),
  onGameChange: () => {},
  onOpenHistory: () => {},
  recentEvents: [],
};

describe("MechanismObservatory reveal contract", () => {
  it("keeps all five ticket combinations sealed before debate", () => {
    const html = renderToStaticMarkup(
      <MechanismObservatory
        {...commonProps}
        decisionRevealed={false}
      />,
    );

    expect(html).toContain("UNKNOWN");
    expect(html).toContain("15 組提案已封存");
    expect(html).not.toContain("候選號碼組合");
    expect(html).not.toContain("observatory-ticket-list");
  });

  it("renders exactly five interactive combinations after reveal", () => {
    const html = renderToStaticMarkup(
      <MechanismObservatory
        {...commonProps}
        decisionRevealed
      />,
    );
    const ticketList = html
      .split('<div class="observatory-ticket-list">')[1]
      .split("</div>")[0];

    expect(html).toContain("候選號碼組合");
    expect(ticketList.match(/<button/g)).toHaveLength(5);
    expect(html).toContain("組合 01");
  });
});
