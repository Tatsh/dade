// What the reader has chosen, kept between visits.
//
// Everything that is a *setting* is kept: the switches, the sliders, the seed, how the list is
// filed, and which difficulty was last looked at. What is not kept is where the reader happens to
// be — the search box and the chosen heading start empty, since coming back to a search you have
// forgotten typing is worse than typing it again.
import { useCallback, useState } from 'react';

const KEY = 'dade.rbplus.site';

const readAll = (): Record<string, unknown> => {
  try {
    const kept: unknown = JSON.parse(localStorage.getItem(KEY) ?? '{}');
    return kept && typeof kept === 'object' ? (kept as Record<string, unknown>) : {};
  } catch {
    return {};
  }
};

const writeAll = (all: Record<string, unknown>) => {
  try {
    localStorage.setItem(KEY, JSON.stringify(all));
  } catch {
    /* private browsing */
  }
};

/**
 * A piece of state that comes back the way it was left.
 *
 * @param name What to file it under.
 * @param fallback What it is before anything has been chosen.
 * @param sound Whether a kept value is still one this version understands. A setting that has
 *   changed shape since it was written falls back rather than being trusted.
 */
export const useSetting = <T>(
  name: string,
  fallback: T,
  sound: (value: unknown) => value is T,
): [T, (value: T) => void] => {
  const [value, setValue] = useState<T>(() => {
    const kept = readAll()[name];
    return sound(kept) ? kept : fallback;
  });
  const keep = useCallback(
    (next: T) => {
      setValue(next);
      writeAll({ ...readAll(), [name]: next });
    },
    [name],
  );
  return [value, keep];
};

/** Whether a kept value is one of a known set of strings. */
export const isOneOf =
  <T extends string>(...allowed: readonly T[]) =>
  (value: unknown): value is T =>
    typeof value === 'string' && (allowed as readonly string[]).includes(value);
