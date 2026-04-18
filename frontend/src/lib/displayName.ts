const REPLACEMENTS: Array<[RegExp, string]> = [
  [/sharon/gi, "william"],
  [/mugure/gi, "osoro"],
];

export function displayName(value: string | null | undefined): string {
  if (!value) return "";
  return REPLACEMENTS.reduce((acc, [pattern, replacement]) => acc.replace(pattern, replacement), value);
}
