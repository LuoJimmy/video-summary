import { describe, expect, it } from "vitest";
import {
  CUSTOM_MODEL,
  SENSEVOICE_MODEL,
  isLocalTranscribeModel,
  transcribeChoice,
} from "./settings";

describe("settings model choices", () => {
  it("treats local whisper and sensevoice as local transcribe", () => {
    expect(isLocalTranscribeModel("small")).toBe(true);
    expect(isLocalTranscribeModel("large-v3")).toBe(true);
    expect(isLocalTranscribeModel("")).toBe(false);
    expect(isLocalTranscribeModel("whisper-1")).toBe(false);
    expect(isLocalTranscribeModel("sensevoice-small-q8")).toBe(true);
    expect(transcribeChoice("small")).toBe("small");
    expect(transcribeChoice("")).toBe(SENSEVOICE_MODEL);
    expect(transcribeChoice("sensevoice-small-q8")).toBe(SENSEVOICE_MODEL);
    expect(transcribeChoice("sensevoice")).toBe(SENSEVOICE_MODEL);
    expect(transcribeChoice("whisper-1")).toBe(CUSTOM_MODEL);
  });
});
