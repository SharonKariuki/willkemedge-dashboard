/**
 * Building photos are shrunk in the browser before upload: a phone camera's
 * 4–8 MB picture becomes a JPEG of a few hundred KB, which is all a card or a
 * page header needs and keeps the stored copy small (it lives in the database).
 */
export const PHOTO_ACCEPT = "image/jpeg,image/png,image/webp";

const MAX_EDGE = 1600;
const QUALITY = 0.82;

export async function shrinkPhoto(file: File): Promise<Blob> {
  if (!PHOTO_ACCEPT.split(",").includes(file.type)) {
    throw new Error("Choose a JPEG, PNG or WebP photo.");
  }
  const bitmap = await createImageBitmap(file).catch(() => {
    throw new Error("That file could not be read as a photo.");
  });
  const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")?.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", QUALITY));
  if (!blob) throw new Error("That photo could not be prepared for upload.");
  return blob;
}
