// Which lane each note is drawn in. A port of `_lanes`, `_lane_plan`, `_assign`, `_groups`, and
// `_Rng` in `dade/rbplus/render.py`.
//
// A chart does not record a lane for a note, and the game has no fixed one to record.
// `CMusicSheet2::AssignChartLanes` allocates each ordinary note's lane at run time through
// `NoteLaneTracker`, seeded from `rand()` when play starts. One chart therefore falls differently
// on every play. Three rules, in the order the engine applies them: a note aimed at one of the
// three alternative targets is pinned to the target's slot; a chain member takes the slot of the
// segment before it; every other note is allocated from the seed.
//
// The generator is mulberry32 rather than either language's. A seed therefore produces the same
// layout here as it does in `render.py`. Which layout a given seed produces is arbitrary in either
// language.
import {
  ALTERNATE_TARGETS,
  ALTERNATE_TARGET_LANES,
  CHAIN_MINIMUM,
  HOLD_HEAD_KIND,
  LANE_COUNT,
  NO_ROUTE_SELECTOR,
  REMAPPED_ROUTE_VERSION,
  SIDE_COUNT,
  SIGN_BIT,
  SLIDE_LANE_REMAP,
  UNSET_ROUTE,
} from './constants';
import { holdLength } from './layout';
import type { Note } from './types';

/** One run of notes competing for a lane, and what it needs to be given one. */
export interface Claim {
  /** The notes struck together, each group in the order they take neighbouring lanes. */
  atOnce: number[][];
  /** When the run gives its lane up. */
  end: number;
  /** Which side's lanes it draws from. */
  side: number;
  /** When it first takes a lane. */
  start: number;
  /** How many lanes it needs, being the most notes it strikes at once. */
  width: number;
}

/** Everything about the layout that the seed does not touch. */
export interface LanePlan {
  /** The runs competing for a lane, in the order they are dealt with. */
  claims: Claim[];
  /** The notes pinned to a slot, against the slot each is pinned to. */
  fixed: Map<number, number>;
}

/** A deterministic generator, seeded by a whole number. */
export const mulberry32 = (from: number) => {
  let state = from >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let word = state;
    word = Math.imul(word ^ (word >>> 15), 1 | word);
    word = (word + Math.imul(word ^ (word >>> 7), 61 | word)) ^ word;
    return ((word ^ (word >>> 14)) >>> 0) / 4294967296;
  };
};

/**
 * The engine's route selector, as `InstallParsedNotes` derives it from the second target
 * coordinate. A value inside 0 to 9 identifies a target outright; every other value lets the note
 * choose one.
 */
export const timingSelector = (note: Note, version: number) => {
  const unsigned = note.target[1] & 0xffff;
  const route = unsigned >= SIGN_BIT ? unsigned - 0x10000 : unsigned;
  if (note.hold_kind === HOLD_HEAD_KIND) return route + LANE_COUNT;
  if (version <= REMAPPED_ROUTE_VERSION || unsigned >= NO_ROUTE_SELECTOR) return UNSET_ROUTE;
  if (route === -3) return -4;
  if (route === -4) return -3;
  if (route >= 0 && route < SLIDE_LANE_REMAP.length) return SLIDE_LANE_REMAP[route];
  return UNSET_ROUTE;
};

/**
 * Whether a note comes straight down into a lane the chart specifies, rather than taking a path the
 * tracker positions. A slide specifies its lane the same way, and the caller therefore excludes
 * slides.
 */
export const isVertical = (note: Note, version: number) => {
  const selector = timingSelector(note, version);
  return selector >= 0 && selector < LANE_COUNT;
};

/** Whether a note is aimed at one of the three targets beyond the seven lanes and drawn green. */
export const isAlternateTarget = (note: Note, version: number) =>
  ALTERNATE_TARGETS.includes(timingSelector(note, version));

/** The slot a note is pinned to, or null when the game is free to choose one. */
export const fixedLane = (note: Note, version: number) => {
  const selector = timingSelector(note, version);
  const aimed = ALTERNATE_TARGETS.indexOf(selector);
  if (aimed >= 0) return ALTERNATE_TARGET_LANES[aimed];
  return selector >= 0 && selector < LANE_COUNT ? selector : null;
};

/** The last moment a note retains its lane against another. */
export const claimedUntil = (note: Note) => note.hit_time + holdLength(note);

/**
 * Every chain, as the indices of its notes in the order they are struck.
 *
 * A chain is a doubly linked run. A note's chain block identifies the note before it and the note
 * after it by identifier, with -1 at each end. Walking forward from every head recovers the runs. A
 * note without a chain block is a run of one.
 */
export const groups = (notes: Note[]) => {
  const byID = new Map(notes.map((note, index) => [note.id, index]));
  const runs: number[][] = [];
  const seen = new Set<number>();
  notes.forEach((note, index) => {
    if (seen.has(index)) return;
    // Start only from a head. A run is therefore walked once and in order.
    if (note.chain !== null && byID.has(note.chain[0])) return;
    const run: number[] = [];
    let step: number | undefined = index;
    while (step !== undefined && !seen.has(step)) {
      seen.add(step);
      run.push(step);
      const following: Note['chain'] = notes[step].chain;
      const after: number = following === null ? -1 : following[1];
      step = after === -1 ? undefined : byID.get(after);
    }
    runs.push(run);
  });
  // A run whose links form a ring has no head. It is picked up from wherever it is met.
  notes.forEach((_, index) => {
    if (!seen.has(index)) runs.push([index]);
  });
  return runs;
};

/**
 * Everything about the layout the seed does not touch: which notes are pinned to a target's slot,
 * and, for the rest, the runs competing for a lane in the order they are dealt with.
 */
export const lanePlan = (notes: Note[], version: number): LanePlan => {
  // A chain takes its lane from its first note to its last. The spans can therefore be compared.
  const spans: { end: number; members: number[]; side: number; start: number }[] = [];
  const singles = new Map<string, { members: number[]; side: number; start: number }>();
  for (const members of groups(notes)) {
    const first = notes[members[0]];
    const side = first.side >= 0 && first.side < SIDE_COUNT ? first.side : 0;
    if (members.length < CHAIN_MINIMUM) {
      // A note in no chain still cannot share a lane with one struck beside it. The notes a side
      // strikes together are therefore positioned as a group.
      const key = `${side}:${first.hit_time}`;
      const already = singles.get(key);
      if (already) already.members.push(members[0]);
      else singles.set(key, { members: [members[0]], side, start: first.hit_time });
      continue;
    }
    spans.push({
      end: Math.max(...members.map((index) => claimedUntil(notes[index]))),
      members,
      side,
      start: Math.min(...members.map((index) => notes[index].hit_time)),
    });
  }
  for (const { members, side, start } of singles.values()) {
    spans.push({
      end: Math.max(...members.map((index) => claimedUntil(notes[index]))),
      members,
      side,
      start,
    });
  }
  spans.sort((a, b) => a.start - b.start || a.end - b.end);
  const fixed = new Map<number, number>();
  const claims: Claim[] = [];
  for (const span of spans) {
    // A note aimed at an alternative target sits in the target's slot. It therefore neither needs
    // a lane nor takes one from the notes struck beside it.
    const rest: number[] = [];
    for (const index of span.members) {
      const slot = fixedLane(notes[index], version);
      if (slot === null) rest.push(index);
      else fixed.set(index, slot);
    }
    if (!rest.length) continue;
    const byTime = new Map<number, number[]>();
    for (const index of rest) {
      const at = notes[index].hit_time;
      const already = byTime.get(at);
      if (already) already.push(index);
      else byTime.set(at, [index]);
    }
    const atOnce = [...byTime.values()].map((group) => [...group].sort((a, b) => a - b));
    claims.push({
      atOnce,
      end: span.end,
      side: span.side,
      start: span.start,
      width: Math.max(...atOnce.map((group) => group.length)),
    });
  }
  return { claims, fixed };
};

/** Hand each run the first lane free when it starts, choosing among the free lanes from the seed. */
export const assignLanes = (plan: LanePlan, seed: number) => {
  const next = mulberry32(seed);
  const lanes = new Map(plan.fixed);
  // taken[side] stores, per lane, the time the lane is taken until.
  const taken = Array.from({ length: SIDE_COUNT }, () =>
    new Array<number>(LANE_COUNT).fill(-Infinity),
  );
  for (const claim of plan.claims) {
    const free: number[] = [];
    for (let lane = 0; lane < Math.max(LANE_COUNT - claim.width + 1, 1); lane += 1) {
      let room = true;
      for (let step = 0; step < claim.width; step += 1) {
        if (taken[claim.side][Math.min(lane + step, LANE_COUNT - 1)] >= claim.start) {
          room = false;
          break;
        }
      }
      if (room) free.push(lane);
    }
    // The engine shuffles its candidates and takes the first; so does this generator, from the
    // seed.
    const base = free.length
      ? free[Math.min(Math.floor(next() * free.length), free.length - 1)]
      : 0;
    for (const together of claim.atOnce) {
      together.forEach((index, step) => {
        lanes.set(index, Math.min(base + step, LANE_COUNT - 1));
      });
    }
    for (let step = 0; step < claim.width; step += 1) {
      taken[claim.side][Math.min(base + step, LANE_COUNT - 1)] = claim.end;
    }
  }
  return lanes;
};

/** Work out which lane each note is drawn in, under one seed. */
export const noteLanes = (notes: Note[], version: number, seed: number) =>
  assignLanes(lanePlan(notes, version), seed);
