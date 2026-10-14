const MARKDOWN_LINK = /^\s*\[[^\]]*\]\((https?:\/\/[^\s)]+)(?:\s+["'][^"']*["'])?\)\s*$/i;

export function normalizeMediaInput(value: string) {
  const trimmed = value.trim();
  const markdown = trimmed.match(MARKDOWN_LINK);
  if (markdown) return markdown[1];
  return trimmed.replace(/^<((?:https?:\/\/)[^>]+)>$/i, "$1");
}
