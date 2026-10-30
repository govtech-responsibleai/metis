import type { api } from "./transport/api";

export function downloadArchive(
  archive: Awaited<ReturnType<typeof api.package>>,
  ownerDocument: Pick<Document, "createElement"> = document,
  urlApi: Pick<typeof URL, "createObjectURL" | "revokeObjectURL"> = URL,
): void {
  const url = urlApi.createObjectURL(archive.blob);
  const anchor = ownerDocument.createElement("a");
  anchor.href = url;
  anchor.download = archive.filename;
  anchor.click();
  anchor.remove();
  urlApi.revokeObjectURL(url);
}
