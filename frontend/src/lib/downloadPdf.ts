import { api } from "./api";

export async function downloadPdf(path: string, filename: string): Promise<void> {
  const { data } = await api.get<Blob>(path, { responseType: "blob" });
  const blob = new Blob([data], { type: "application/pdf" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
