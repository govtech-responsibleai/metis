import type { NamedFile } from "./transport/api.ts";

export function saveFile(
  file: NamedFile,
  ownerDocument: Pick<Document, "createElement"> = document,
  urlApi: Pick<typeof URL, "createObjectURL" | "revokeObjectURL"> = URL,
): void {
  const url = urlApi.createObjectURL(file.blob);
  const anchor = ownerDocument.createElement("a");
  anchor.href = url;
  anchor.download = file.filename;
  anchor.click();
  anchor.remove();
  urlApi.revokeObjectURL(url);
}
