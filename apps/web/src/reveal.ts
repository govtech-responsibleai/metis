// First fills keep spaces and line breaks byte-for-byte by taking exact prefixes from the source.
// Corrections use word chunks and restore the exact target string in their final frame.
export const REVEAL_INTERVAL_MS = 35;

type Word = { text: string };

type WordChunk =
  | { kind: "equal"; word: Word }
  | { kind: "change"; oldWords: Word[]; newWords: Word[] };

function words(value: string): Word[] {
  return [...value.matchAll(/\S+/g)].map(([text]) => ({ text }));
}

function wordChunks(oldValue: string, newValue: string): WordChunk[] {
  const oldWords = words(oldValue);
  const newWords = words(newValue);
  const lengths = oldWords.map(() =>
    new Array<number>(newWords.length + 1).fill(0),
  );

  for (let oldIndex = oldWords.length - 1; oldIndex >= 0; oldIndex -= 1) {
    for (let newIndex = newWords.length - 1; newIndex >= 0; newIndex -= 1) {
      lengths[oldIndex][newIndex] =
        oldWords[oldIndex].text === newWords[newIndex].text
          ? 1 + (lengths[oldIndex + 1]?.[newIndex + 1] ?? 0)
          : Math.max(
              lengths[oldIndex + 1]?.[newIndex] ?? 0,
              lengths[oldIndex][newIndex + 1],
            );
    }
  }

  const chunks: WordChunk[] = [];
  let oldIndex = 0;
  let newIndex = 0;
  let changedOld: Word[] = [];
  let changedNew: Word[] = [];

  const flushChange = () => {
    if (changedOld.length || changedNew.length) {
      chunks.push({
        kind: "change",
        oldWords: changedOld,
        newWords: changedNew,
      });
      changedOld = [];
      changedNew = [];
    }
  };

  while (oldIndex < oldWords.length || newIndex < newWords.length) {
    const oldWord = oldWords[oldIndex];
    const newWord = newWords[newIndex];
    if (oldWord && newWord && oldWord.text === newWord.text) {
      flushChange();
      chunks.push({ kind: "equal", word: newWord });
      oldIndex += 1;
      newIndex += 1;
      continue;
    }

    const keepOld = lengths[oldIndex + 1]?.[newIndex] ?? 0;
    const keepNew = lengths[oldIndex]?.[newIndex + 1] ?? 0;
    if (oldWord && (!newWord || keepOld >= keepNew)) {
      changedOld.push(oldWord);
      oldIndex += 1;
    } else if (newWord) {
      changedNew.push(newWord);
      newIndex += 1;
    }
  }
  flushChange();
  return chunks;
}

function renderChunks(
  chunks: WordChunk[],
  oldCounts: number[],
  newCounts: number[],
): string {
  const visibleWords: string[] = [];
  let changeIndex = 0;
  for (const chunk of chunks) {
    if (chunk.kind === "equal") {
      visibleWords.push(chunk.word.text);
      continue;
    }
    visibleWords.push(
      ...chunk.oldWords
        .slice(0, oldCounts[changeIndex])
        .map((word) => word.text),
      ...chunk.newWords
        .slice(0, newCounts[changeIndex])
        .map((word) => word.text),
    );
    changeIndex += 1;
  }
  return visibleWords.join(" ");
}

function diffFrames(displayed: string, next: string): string[] {
  const chunks = wordChunks(displayed, next);
  const changeCount = chunks.filter((chunk) => chunk.kind === "change").length;
  if (changeCount === 0) return [];

  const oldCounts = chunks
    .filter(
      (chunk): chunk is Extract<WordChunk, { kind: "change" }> =>
        chunk.kind === "change",
    )
    .map((chunk) => chunk.oldWords.length);
  const newCounts = oldCounts.map(() => 0);
  const frames: string[] = [];

  for (let changeIndex = 0; changeIndex < changeCount; changeIndex += 1) {
    const chunk = chunks.filter(
      (chunk): chunk is Extract<WordChunk, { kind: "change" }> =>
        chunk.kind === "change",
    )[changeIndex];
    for (let count = chunk.oldWords.length - 1; count >= 0; count -= 1) {
      oldCounts[changeIndex] = count;
      frames.push(renderChunks(chunks, oldCounts, newCounts));
    }
    for (let count = 1; count <= chunk.newWords.length; count += 1) {
      newCounts[changeIndex] = count;
      frames.push(renderChunks(chunks, oldCounts, newCounts));
    }
  }

  if (frames.at(-1) !== next) frames.push(next);
  return frames;
}

export function wordFrames(value: string): string[] {
  const words = [...value.matchAll(/\S+/g)];
  if (words.length === 0) return value ? [value] : [];

  return words.map((_, index) => {
    const nextWord = words[index + 1];
    return value.slice(0, nextWord?.index ?? value.length);
  });
}

export function transitionFrames({
  displayed,
  previous,
  next,
  reducedMotion,
}: {
  displayed: string;
  previous: string;
  next: string;
  reducedMotion: boolean;
}): string[] {
  if (reducedMotion) return displayed === next ? [] : [next];
  if (previous === next) return [];

  if (previous === "") return wordFrames(next);
  if (displayed === next) return [];

  // Diff what is actually on screen. If a newer value arrives during a reveal, unchanged words
  // that the user can already see remain in place while only the new correction moves.
  return diffFrames(displayed, next);
}
