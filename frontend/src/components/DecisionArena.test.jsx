import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import DecisionArena from "./DecisionArena";

describe("DecisionArena reveal safety", () => {
  it("renders a recoverable error instead of crashing on an incomplete reveal", () => {
    const html = renderToStaticMarkup(
      <DecisionArena
        activeGame="super"
        activeSlot={1}
        currentCritique={null}
        debateStep={60}
        error="最終五注資料不完整，請重新執行辯論。"
        gameData={{
          next_decision: {
            target: { date: "2026-07-20", period: 115000058 },
            adjudication: {
              judge: { source: "pending" },
              ranking: [],
            },
          },
        }}
        isPlaying={false}
        onGameChange={() => {}}
        onPlayToggle={() => {}}
        onSelectTicket={() => {}}
        onStep={() => {}}
        phase="revealed"
        probabilityPortfolio={{
          fallback_to_qwen: true,
          tickets: [],
        }}
        selectedSlot={1}
        totalCritiques={60}
      />,
    );

    expect(html).toContain("裁決讀取失敗");
    expect(html).toContain("最終五注資料不完整");
    expect(html).not.toContain("ticket-readout");
  });
});
