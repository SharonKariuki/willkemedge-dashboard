const REPLACEMENTS: Array<[RegExp, string]> = [
  [/sharonmugure\d*/gi, "wilkem.ventures"],
  [/sharon/gi, "wilkem"],
  [/mugure/gi, "ventures"],
];

export function displayName(value: string | null | undefined): string {
  if (!value) return "";
  return REPLACEMENTS.reduce((acc, [pattern, replacement]) => acc.replace(pattern, replacement), value);
}
