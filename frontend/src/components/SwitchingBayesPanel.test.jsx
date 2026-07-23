import fs from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import SwitchingBayesPanel from "./SwitchingBayesPanel";

const study = JSON.parse(
  fs.readFileSync(
    new URL(
      "../../../research/results/switching_bayes.json",
      import.meta.url,
    ),
    "utf8",
  ),
);

describe("SwitchingBayesPanel", () => {
  it("shows an honest future-only status and all six experts", () => {
    const html = renderToStaticMarkup(
      <SwitchingBayesPanel activeGame="super" study={study} />,
    );

    expect(html).toContain("FUTURE SHADOW");
    expect(html).toContain("REGIME RECOVERY");
    expect(html).toContain("H1");
    expect(html).toContain("H2");
    expect(html).toContain("H3");
    expect(html).toContain("H4");
    expect(html).toContain("H0");
    expect(html).toContain("Σ");
    expect(html).not.toContain("BELIEF PROMOTED");
  });

  it("fails visibly when the research artifact is unavailable", () => {
    const html = renderToStaticMarkup(
      <SwitchingBayesPanel
        activeGame="super"
        study={{ error: "artifact missing" }}
      />,
    );

    expect(html).toContain("未知生成器證據層尚未就緒");
    expect(html).toContain("artifact missing");
  });
});
