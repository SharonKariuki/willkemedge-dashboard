import { api } from "./api";

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function downloadPdf(path: string, filename: string): Promise<void> {
  const { data } = await api.get<Blob>(path, { responseType: "blob" });
  triggerDownload(new Blob([data], { type: "application/pdf" }), filename);
}

/** Download a server-generated CSV, forwarding the given query params so the
 *  export mirrors the currently-applied filters. */
export async function downloadCsv(
  path: string,
  filename: string,
  params?: Record<string, unknown>,
): Promise<void> {
  const { data } = await api.get<Blob>(path, { params, responseType: "blob" });
  triggerDownload(new Blob([data], { type: "text/csv" }), filename);
}
