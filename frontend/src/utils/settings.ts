export const CUSTOM_MODEL = "__custom__";

export const LOCAL_WHISPER_MODELS = [
  "tiny",
  "base",
  "small",
  "medium",
  "large",
  "large-v2",
  "large-v3",
] as const;

export const SENSEVOICE_MODEL = "sensevoice-small-q8";

export const LOCAL_TRANSCRIBE_MODELS = [
  { value: SENSEVOICE_MODEL, label: "SenseVoice Small Q8（本地，推荐）" },
  { value: "small", label: "Whisper Small（本地）" },
  { value: "tiny", label: "Whisper Tiny（本地）" },
  { value: "base", label: "Whisper Base（本地）" },
  { value: "medium", label: "Whisper Medium（本地）" },
  { value: "large", label: "Whisper Large（本地）" },
  { value: "large-v2", label: "Whisper Large-v2（本地）" },
  { value: "large-v3", label: "Whisper Large-v3（本地）" },
] as const;

export function isSenseVoiceModel(name: string): boolean {
  const normalized = (name || "").trim().toLowerCase().replace(/_/g, "-");
  return (
    Boolean(normalized) &&
    (normalized.includes("sensevoice") || normalized === SENSEVOICE_MODEL)
  );
}

export function isLocalTranscribeModel(name: string): boolean {
  const normalized = (name || "").trim().toLowerCase().replace(/_/g, "-");
  if (!normalized || normalized === "whisper-1") return false;
  if (isSenseVoiceModel(normalized)) return true;
  return (
    LOCAL_TRANSCRIBE_MODELS.some((item) => item.value === normalized) ||
    LOCAL_WHISPER_MODELS.some((item) => item === normalized)
  );
}

export function transcribeChoice(name: string): string {
  const normalized = (name || "").trim().toLowerCase().replace(/_/g, "-");
  if (isSenseVoiceModel(normalized)) {
    return SENSEVOICE_MODEL;
  }
  if (!normalized || isLocalTranscribeModel(normalized)) {
    const listed = LOCAL_TRANSCRIBE_MODELS.find(
      (item) => item.value === normalized
    );
    if (listed) return listed.value;
    if (LOCAL_WHISPER_MODELS.some((item) => item === normalized))
      return normalized;
    return LOCAL_TRANSCRIBE_MODELS[0].value;
  }
  return CUSTOM_MODEL;
}
