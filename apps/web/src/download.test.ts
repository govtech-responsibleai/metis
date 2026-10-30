import assert from "node:assert/strict";
import test from "node:test";
import { downloadArchive } from "./download.ts";

test("offers the ZIP with its server filename", () => {
  const downloads: string[] = [];
  const revoked: string[] = [];
  const document = {
    createElement: () => ({
      href: "",
      download: "",
      click() {
        downloads.push(this.download);
      },
      remove() {},
    }),
  } as unknown as Document;
  const urlApi = {
    createObjectURL: () => "blob:metis",
    revokeObjectURL: (url: string) => revoked.push(url),
  } as Pick<typeof URL, "createObjectURL" | "revokeObjectURL">;

  downloadArchive(
    {
      blob: new Blob(["zip bytes"], { type: "application/zip" }),
      filename: "20261016-223045-interview.zip",
    },
    document,
    urlApi,
  );

  assert.deepEqual(downloads, ["20261016-223045-interview.zip"]);
  assert.deepEqual(revoked, ["blob:metis"]);
});
