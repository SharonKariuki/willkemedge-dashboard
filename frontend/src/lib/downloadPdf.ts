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

export type ExportFormat = "csv" | "xlsx" | "pdf";

function filenameFrom(disposition: unknown, fallback: string): string {
  const match = /filename="?([^";]+)"?/i.exec(String(disposition ?? ""));
  return match?.[1] ?? fallback;
}

/** Why a download failed, read out of the error body (which arrives as a Blob). */
async function downloadError(err: unknown): Promise<Error> {
  const data = (err as { response?: { data?: unknown } })?.response?.data;
  if (data instanceof Blob) {
    try {
      const body = JSON.parse(await data.text()) as Record<string, unknown>;
      const first = Object.values(body)[0];
      return new Error(String(Array.isArray(first) ? first[0] : first ?? "The download failed."));
    } catch {
      /* not JSON */
    }
  }
  return new Error("The download failed. Please try again.");
}

/**
 * Download a server-generated file — GET with query params, or POST with a
 * JSON body — saving it under the name the server gives it.
 */
export async function downloadFile(
  path: string,
  { params, body, fallback = "report" }: { params?: Record<string, unknown>; body?: unknown; fallback?: string } = {},
): Promise<void> {
  try {
    const response = body === undefined
      ? await api.get<Blob>(path, { params, responseType: "blob" })
      : await api.post<Blob>(path, body, { responseType: "blob" });
    triggerDownload(response.data, filenameFrom(response.headers["content-disposition"], fallback));
  } catch (err) {
    throw await downloadError(err);
  }
}
