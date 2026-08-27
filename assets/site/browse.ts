// Finding a tune in the collection: what the index holds, how a search matches, and how the list
// is filed. None of it touches the page, so it can be checked on its own.
import { type Chart } from './chart/types';

/** How a tune's charts are named, easiest first. The last is harder than hard. */
export const DIFFICULTIES = ['basic', 'medium', 'hard', 'special'] as const;
export type Difficulty = (typeof DIFFICULTIES)[number];

/**
 * What each difficulty is shown as.
 *
 * Written out rather than left to `text-transform`, which capitalises by word and so depends on
 * where the spaces happen to fall.
 */
export const DIFFICULTY_LABELS: Record<Difficulty, string> = {
  basic: 'Basic',
  hard: 'Hard',
  medium: 'Medium',
  special: 'Special',
};

/** One tune as the index lists it. Mirrors what `dade rbplus site` writes. */
export interface Tune {
  /** The artist, as the game shows it. */
  artist: string;
  /** The artist's kana reading. */
  artistReading: string;
  /** The artist's reading in Latin letters. */
  artistRomaji: string;
  /** The lowest and highest tempo, either of which may be absent. */
  bpm: [number | null, number | null];
  /** The tune's identifier, which names its chart file. */
  id: number;
  /** Which letter it is filed under: A to Z, `#` for a digit, or `?` for neither. */
  letter: string;
  /** Each chart it holds, against the level the metadata gives it. */
  levels: Partial<Record<Difficulty, number | null>>;
  /** Which gojūon row it is filed under. */
  row: string;
  /** The identifier of the extend note holding its SPECIAL chart, or null. */
  special: number | null;
  /** The title, as the game shows it. */
  title: string;
  /** The title's kana reading. */
  titleReading: string;
  /** The title's reading in Latin letters. */
  titleRomaji: string;
}

/** The whole index. */
export interface Index {
  /** Every letter some tune is filed under, in order. */
  letters: string[];
  /** Every gojūon row some tune is filed under, in the gojūon's own order. */
  rows: string[];
  /** Every tune. */
  tunes: Tune[];
}

/** Every chart of one tune, against the difficulty it is. */
export type Charts = Partial<Record<Difficulty, Chart>>;

/** Which of the two ways of filing the list is showing. */
export type Filing = 'letter' | 'row';

/**
 * The six things a search is matched against.
 *
 * A tune can be looked for by what it is called, by how that is read, or by how the reading is
 * typed on a Latin keyboard, and the same three for its artist. The romaji is what makes a
 * Japanese title findable without a Japanese keyboard.
 */
export const searchable = (tune: Tune) => [
  tune.title,
  tune.titleReading,
  tune.titleRomaji,
  tune.artist,
  tune.artistReading,
  tune.artistRomaji,
];

/** Everything that is not a letter or a digit, which a search should not have to type. */
const NOISE = /[^\p{L}\p{N}]+/gu;

/**
 * The sounds that are written one way and typed another.
 *
 * The romanisation is Hepburn, which is how a reading is *written*: `し` is `shi` and the particle
 * `を` is `o`. It is not how a reading is *typed*: a Japanese keyboard takes `si` and `wo`. Neither
 * spelling is wrong, so both sides of a search are folded to one of them and either spelling finds
 * the tune. The longer sound comes first, so `shi` is folded before `sh`.
 */
const SPELLINGS: [RegExp, string][] = [
  [/shi/g, 'si'],
  [/sh/g, 'sy'],
  [/chi/g, 'ti'],
  [/ch/g, 'ty'],
  [/tsu/g, 'tu'],
  [/ji/g, 'zi'],
  [/j/g, 'zy'],
  [/fu/g, 'hu'],
  [/wo/g, 'o'],
];

const flatten = (text: string) => {
  let folded = text.normalize('NFKC').toLocaleLowerCase().replace(NOISE, '');
  for (const [written, typed] of SPELLINGS) folded = folded.replace(written, typed);
  return folded;
};

/**
 * Whether a tune answers to what was typed.
 *
 * Punctuation, case, and width are ignored on both sides, so `kors k` finds `KORS K` and `クシコス`
 * finds `クシコス☆ポスト`. So is the difference between how a reading is written and how it is
 * typed, so `愛を` answers to both `aio` and `aiwo`.
 *
 * A search of several words asks for all of them, each anywhere the tune can be searched, so a
 * title and an artist can be given together and the words need not be in the order the tune has
 * them. Each word still has to be found whole in one field: a word is not made up out of the end of
 * one field and the start of the next. An empty search matches everything.
 */
export const matches = (tune: Tune, query: string) => {
  const words = query.split(/\s+/).map(flatten).filter(Boolean);
  if (!words.length) return true;
  const fields = searchable(tune).map(flatten);
  return words.every((word) => fields.some((field) => field.includes(word)));
};

/** The tunes under one heading, in the order they are listed. */
export interface Group {
  /** What the heading is: a letter, or the kana that heads a gojūon row. */
  heading: string;
  tunes: Tune[];
}

/**
 * File the tunes under their headings, leaving out any heading nothing is filed under.
 *
 * @param tunes The tunes to file, already in the order they should be listed.
 * @param filing Which of the two ways to file them.
 * @param headings Every heading, in the order they should appear.
 */
export const group = (tunes: Tune[], filing: Filing, headings: string[]): Group[] => {
  const under = new Map<string, Tune[]>();
  for (const tune of tunes) {
    const heading = filing === 'letter' ? tune.letter : tune.row;
    const already = under.get(heading);
    if (already) already.push(tune);
    else under.set(heading, [tune]);
  }
  const known = headings.filter((heading) => under.has(heading));
  // A tune filed under a heading the index did not name is still shown, after the ones that were.
  const rest = [...under.keys()].filter((heading) => !headings.includes(heading)).sort();
  return [...known, ...rest].map((heading) => ({ heading, tunes: under.get(heading) ?? [] }));
};

/** Which charts a tune holds, easiest first. */
export const difficulties = (tune: Tune) => DIFFICULTIES.filter((name) => name in tune.levels);

/** What one route names. A route with no tune is the list. */
export interface Route {
  difficulty: Difficulty | null;
  id: number | null;
}

/**
 * Where the site is served from, or null when it does not know.
 *
 * `dade rbplus site --base` writes this into the page. Given one, the site uses real paths and the
 * page it was built for serves a `404.html` copy so a deep link boots the app. Without one it
 * cannot know where its own files are, so it falls back to the hash, which works from anywhere.
 */
export const base = (): string | null => {
  const kept = document.documentElement.dataset.base;
  return kept ? kept.replace(/\/*$/, '/') : null;
};

/**
 * The identifier a chart opened from the reader's own machine is given, being no tune's.
 *
 * It has an address of its own so that it is somewhere the browser has been: opening a file that
 * changed nothing in the location would leave the back button with nothing to go back to, and the
 * way out of the chart would be a button that wrote the address it already had.
 */
export const OPENED = -1;

const asRoute = (parts: string[]): Route => {
  const difficulty = (at: number) => DIFFICULTIES.find((name) => name === parts[at]) ?? null;
  if (parts[0] === 'opened') return { difficulty: difficulty(1), id: OPENED };
  if (parts[0] !== 'tune' || !parts[1]) return { difficulty: null, id: null };
  const id = Number(parts[1]);
  return { difficulty: difficulty(2), id: Number.isFinite(id) ? id : null };
};

/** Read a route out of the current location, however this site addresses itself. */
export const readRoute = (): Route => {
  const at = base();
  if (at === null) {
    return asRoute(location.hash.replace(/^#\/?/, '').split('/').filter(Boolean));
  }
  const path = location.pathname.startsWith(at) ? location.pathname.slice(at.length) : '';
  return asRoute(path.split('/').filter(Boolean));
};

/** Write a route as something that can be given to the browser. */
export const writeRoute = (route: Route) => {
  const tail =
    route.id === null
      ? ''
      : route.id === OPENED
        ? 'opened'
        : `tune/${route.id}${route.difficulty ? `/${route.difficulty}` : ''}`;
  const at = base();
  return at === null ? `#/${tail}` : `${at}${tail}`;
};
