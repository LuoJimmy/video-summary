import { describe, expect, it } from "vitest";
import {
  parseLexiconTerms,
  sanitizeLexiconFixes,
  serializeLexiconTerms,
} from "./lexicon";

describe("lexicon editors", () => {
  it("keeps unique terms in the order they were entered", () => {
    expect(parseLexiconTerms("打板\n\n 炸板 \n打板\n龙头")).toEqual([
      "打板",
      "炸板",
      "龙头",
    ]);
    expect(serializeLexiconTerms(["打板", "龙头"])).toBe("打板\n龙头");
  });

  it("drops empty or identical replacement rows", () => {
    expect(
      sanitizeLexiconFixes([
        { wrong: "打版", right: "打板" },
        { wrong: "  ", right: "龙头" },
        { wrong: "笼头", right: "笼头" },
        { wrong: "打版", right: "重复" },
        { wrong: "笼头", right: "龙头" },
      ])
    ).toEqual([
      { wrong: "打版", right: "打板" },
      { wrong: "笼头", right: "龙头" },
    ]);
  });
});
