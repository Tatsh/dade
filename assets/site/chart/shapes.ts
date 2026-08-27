// What is drawn in one column of one side. A port of `_draw_grid`, `_draw_beats`,
// `_draw_tempo_events`, `_draw_slides`, `_draw_chains`, and `_draw_notes` in
// `dade/rbplus/render.py`.
//
// Nothing here is JSX. The renderer calls a surface and the shapes go straight out; this returns
// them instead, so what a column holds can be set beside what `render.py` draws for the same
// column, and so React only has to turn a shape into an element.
import {
  ALTERNATE_TARGETS,
  BAR_WIDTH,
  BEATS_PER_BAR,
  CHAIN_MINIMUM,
  COLORS,
  FREE_NOTE_START_TIME,
  GUTTER,
  HOLD_WIDTH,
  LANE_COUNT,
  LANE_PX,
  MILLISECONDS,
  NOTE_RADIUS,
  RULE_WIDTH,
  SECONDS_PER_MINUTE,
  SIDE_COUNT,
  SIDE_LABELS,
  SIDE_OBJECT_FLAG,
  SLIDE_DOT,
  SLIDE_WIDTH,
  SPEED_CHANGE_KIND,
  TEMPO_WIDTH,
  VEE_RISE,
  VEE_STROKE,
  VEE_WIDTH,
} from './constants';
import { groups, isAlternateTarget, isVertical, timingSelector } from './lanes';
import { holdLength, type Layout } from './layout';
import type { Chart, Note, Slide } from './types';

/** A straight run of segments. */
export interface LineShape {
  color: string;
  kind: 'line';
  /** Alternating x and y, at least two points. */
  points: number[];
  /** Whether the corners are rounded, which the vertical mark wants. */
  round?: boolean;
  width: number;
}

/** A filled rectangle, which is how a hold is drawn. */
export interface RectShape {
  color: string;
  height: number;
  kind: 'rect';
  width: number;
  x: number;
  y: number;
}

/** A filled circle: a note's disc, or a waypoint of a slide. */
export interface DiscShape {
  color: string;
  kind: 'disc';
  radius: number;
  x: number;
  y: number;
}

/** Half a disc, being the half a note that travels to the other side leaves by. */
export interface HalfShape {
  color: string;
  /** Whether the filled half is the lower one. */
  down: boolean;
  kind: 'half';
  radius: number;
  x: number;
  y: number;
}

export type Shape = DiscShape | HalfShape | LineShape | RectShape;

/** One note, with the shapes it is drawn from and what it says about itself. */
export interface DrawnNote {
  /** Which lane it was laid out in, or null when it was not drawn. */
  lane: number | null;
  /** The note's index in the chart. */
  index: number;
  /** What it says about itself when it is pointed at. */
  details: Record<string, string>;
  /** The shapes it is drawn from. The disc comes last, so it sits over its own hold. */
  shapes: Shape[];
  /** The middle of the disc, so the page can put a tip beside it. */
  x: number;
  y: number;
}

/** Everything one column of one side holds. */
export interface Column {
  /** Which column of the chart it is, counting from the start of the tune. */
  column: number;
  /** The lane divisions, which the page offers to leave out. */
  laneRules: Shape[];
  /** The chains, slides, and speed changes drawn under the notes. */
  under: Shape[];
  /** The notes. */
  notes: DrawnNote[];
  /** The seconds and beats across the column, which the page offers to leave out. */
  timeRules: Shape[];
  /** Each second's line, against what to call it. */
  seconds: { label: string; y: number }[];
  /** Which side it belongs to. */
  side: number;
}

const noteColor = (note: Note, version: number) => {
  if (isAlternateTarget(note, version)) return COLORS.alternateTarget;
  const side = note.side >= 0 && note.side < SIDE_COUNT ? note.side : 0;
  return COLORS.note[side];
};

/**
 * The names the engine gives the bits of a note's flag word, a port of `NOTE_FLAGS` in
 * `dade/rbplus/chart.py`. Only these five bits are named; anything else is left out.
 */
const NOTE_FLAGS: [number, string][] = [
  [0x01, 'same_lane'],
  [0x04, 'different_lane'],
  [0x08, 'long_head'],
  [0x10, 'free'],
  [0x20, 'has_path'],
];

const flagNames = (flags: number) =>
  NOTE_FLAGS.filter(([bit]) => flags & bit).map(([, name]) => name.toUpperCase());

/**
 * The lane a slide is in at each moment it is drawn through.
 *
 * A slide's records are its waypoints. Each carries the lane the finger is to be in and, in the
 * same shape a note's own timing takes, a spawn time and a travel time whose sum is the moment it
 * is to be there. The note itself is the first point, since that is where the finger goes down.
 */
export const slidePaths = (notes: Note[], slides: Slide[]) => {
  const grouped = new Map<number, Slide[]>();
  for (const slide of slides) {
    if (slide.note_index < 0 || slide.note_index >= notes.length) continue;
    const already = grouped.get(slide.note_index);
    if (already) already.push(slide);
    else grouped.set(slide.note_index, [slide]);
  }
  const paths = new Map<number, { lane: number; time: number }[]>();
  for (const [index, records] of grouped) {
    paths.set(index, [
      { lane: -1, time: notes[index].hit_time },
      ...[...records]
        .sort((a, b) => a.field2 - b.field2)
        .filter((record) => record.lane >= 0 && record.lane < LANE_COUNT)
        .map((record) => ({ lane: record.lane, time: record.value_a + record.value_b })),
    ]);
  }
  return paths;
};

/** What one note says about itself when it is pointed at. */
const noteDetails = (
  note: Note,
  index: number,
  lane: number | null,
  version: number,
  held: number,
  sliding: boolean,
  vertical: boolean,
) => {
  const kinds: string[] = [];
  if (held > 0) kinds.push('Hold');
  if (sliding) kinds.push('Slide');
  if (vertical) kinds.push('Vertical');
  if (note.flags & SIDE_OBJECT_FLAG) kinds.push('Swipe Back');
  if (isAlternateTarget(note, version)) kinds.push('Green');
  const names = flagNames(note.flags);
  const details: Record<string, string> = {
    Index: String(index),
    Side: note.side >= 0 && note.side < SIDE_COUNT ? SIDE_LABELS[note.side] : String(note.side),
    Kind: kinds.length ? kinds.join(', ') : 'Ordinary',
    'Hit Time': `${note.hit_time} ms`,
    'Spawn Time': `${note.spawn_time} ms`,
    'Travel Time': `${note.travel_time} ms`,
    Lane: lane === null ? 'Not laid out' : String(lane),
    'Route Selector': String(timingSelector(note, version)),
    Group: note.start_time === FREE_NOTE_START_TIME ? 'Free' : String(note.start_time),
    Flags: names.length ? names.join(' | ') : 'NONE',
    'Flag Integer': `0x${note.flags.toString(16).padStart(4, '0')}`,
  };
  if (held > 0) details['Held For'] = `${held} ms`;
  if (note.path_points.length) details['Path Points'] = note.path_points.join(', ');
  if (note.chain !== null) details.Chain = note.chain.join(', ');
  return details;
};

/** A note's disc: its colour, the gold half it leaves by, and the V cut into a vertical one. */
const discShapes = (
  x: number,
  y: number,
  color: string,
  flip: boolean,
  sideObject: boolean,
  vertical: boolean,
): Shape[] => {
  const shapes: Shape[] = [{ color, kind: 'disc', radius: NOTE_RADIUS, x, y }];
  if (sideObject) {
    // The gold half is the one the note leaves by, which is whichever way time runs.
    shapes.push({
      color: COLORS.sideObject,
      down: flip,
      kind: 'half',
      radius: NOTE_RADIUS,
      x,
      y,
    });
  }
  if (vertical) {
    const arm = Math.round(NOTE_RADIUS * VEE_WIDTH);
    const rise = Math.round(NOTE_RADIUS * VEE_RISE) * (flip ? -1 : 1);
    shapes.push({
      color: COLORS.background,
      kind: 'line',
      points: [x - arm, y - rise, x, y + rise, x + arm, y - rise],
      round: true,
      width: VEE_STROKE,
    });
  }
  return shapes;
};

/**
 * Lay out every column of a chart.
 *
 * @param chart The parsed chart.
 * @param layout Where its columns, lanes, and times land.
 * @param lanes Each note's index against the lane it is drawn in.
 * @param BPM The tune's tempo. Given one, a line is drawn on every quarter note and a brighter one
 *   on every bar. A tempo that is absent or not positive leaves the beat grid off.
 */
export const chartColumns = (
  chart: Chart,
  layout: Layout,
  lanes: Map<number, number>,
  BPM: number | null,
): Column[] => {
  const version = chart.header.version;
  const notes = chart.notes;
  const columns: Column[] = [];
  for (let side = 0; side < SIDE_COUNT; side += 1) {
    for (let column = 0; column < layout.columns; column += 1) {
      const laneRules: Shape[] = [];
      for (let lane = 1; lane < layout.lanes; lane += 1) {
        const x = layout.laneCenter(lane) - Math.floor(LANE_PX / 2);
        laneRules.push({
          color: COLORS.laneLine,
          kind: 'line',
          points: [x, layout.top, x, layout.bottom],
          width: RULE_WIDTH,
        });
      }
      const timeRules: Shape[] = [];
      const seconds: { label: string; y: number }[] = [];
      const edge = layout.flip ? layout.top : layout.bottom;
      for (let second = 0; second <= layout.secondsPerColumn; second += 1) {
        const y = layout.later(edge, second * layout.pixelsPerSecond);
        timeRules.push({
          color: COLORS.grid,
          kind: 'line',
          points: [GUTTER, y, layout.columnWidth, y],
          width: RULE_WIDTH,
        });
        const absolute = (layout.startMs + column * layout.spanMs) / MILLISECONDS + second;
        seconds.push({ label: `${Math.round(absolute)}s`, y });
      }
      columns.push({ column, laneRules, notes: [], seconds, side, timeRules, under: [] });
    }
  }
  const at = (side: number, column: number) => columns[side * layout.columns + column];

  // A line on every quarter note, with a brighter one every fourth. The grid is anchored at time
  // zero, which is where the tune's own clock starts; a chart may begin before it.
  if (BPM !== null && BPM > 0) {
    const beatMs = (SECONDS_PER_MINUTE * MILLISECONDS) / BPM;
    const lastBeat = Math.ceil((layout.startMs + layout.columns * layout.spanMs) / beatMs);
    for (let beat = Math.floor(layout.startMs / beatMs); beat <= lastBeat; beat += 1) {
      const spot = layout.place(Math.trunc(beat * beatMs));
      if (spot === null) continue;
      const color = beat % BEATS_PER_BAR === 0 ? COLORS.barLine : COLORS.beatLine;
      for (let side = 0; side < SIDE_COUNT; side += 1) {
        at(side, spot.column).timeRules.push({
          color,
          kind: 'line',
          points: [GUTTER, spot.y, layout.columnWidth, spot.y],
          width: RULE_WIDTH,
        });
      }
    }
  }

  // A speed change rules its column across in both panels.
  for (const event of chart.tempo_events) {
    if (event.kind !== SPEED_CHANGE_KIND) continue;
    const spot = layout.place(event.time);
    if (spot === null) continue;
    for (let side = 0; side < SIDE_COUNT; side += 1) {
      at(side, spot.column).under.push({
        color: COLORS.tempo,
        kind: 'line',
        points: [GUTTER, spot.y, layout.columnWidth, spot.y],
        width: TEMPO_WIDTH,
      });
    }
  }

  const spotOf = (index: number) => {
    const note = notes[index];
    const placed = layout.place(note.hit_time);
    if (placed === null) return null;
    const side = note.side >= 0 && note.side < SIDE_COUNT ? note.side : 0;
    return {
      column: placed.column,
      side,
      x: layout.laneCenter(lanes.get(index) ?? 0),
      y: placed.y,
    };
  };

  // The track a finger takes: down on the note, then across to each waypoint in turn. A leg whose
  // two ends fall in different columns is left out, there being nowhere to run it.
  for (const [index, path] of slidePaths(notes, chart.slides)) {
    const side = notes[index].side >= 0 && notes[index].side < SIDE_COUNT ? notes[index].side : 0;
    const points: { column: number; x: number; y: number }[] = [];
    for (const point of path) {
      const placed = layout.place(point.time);
      if (placed === null) continue;
      const lane = point.lane < 0 ? (lanes.get(index) ?? 0) : point.lane;
      points.push({ column: placed.column, x: layout.laneCenter(lane), y: placed.y });
    }
    for (let step = 1; step < points.length; step += 1) {
      const before = points[step - 1];
      const after = points[step];
      if (before.column !== after.column) continue;
      at(side, after.column).under.push(
        {
          color: COLORS.slide,
          kind: 'line',
          points: [before.x, before.y, after.x, after.y],
          width: SLIDE_WIDTH,
        },
        { color: COLORS.slide, kind: 'disc', radius: SLIDE_DOT, x: after.x, y: after.y },
      );
    }
  }

  // A line joins each note of a chain to the next, drawn under the notes themselves. A pair split
  // across two columns is left without a line, there being nowhere to run one.
  for (const members of groups(notes)) {
    if (members.length < CHAIN_MINIMUM) continue;
    const placed = members.map(spotOf);
    for (let step = 1; step < placed.length; step += 1) {
      const before = placed[step - 1];
      const after = placed[step];
      if (before === null || after === null || before.column !== after.column) continue;
      at(after.side, after.column).under.push({
        color: noteColor(notes[members[step]], version),
        kind: 'line',
        points: [before.x, before.y, after.x, after.y],
        width: BAR_WIDTH,
      });
    }
  }

  const sliding = new Set(chart.slides.map((slide) => slide.note_index));
  notes.forEach((note, index) => {
    const spot = spotOf(index);
    if (spot === null) return;
    const color = noteColor(note, version);
    const vertical = !sliding.has(index) && isVertical(note, version);
    const held = holdLength(note);
    const shapes: Shape[] = [];
    if (held > 0) {
      // A hold runs from the note up to the moment it is released, clipped to the column. It is
      // drawn wide, with a cap at the release, so that a hold sitting at the end of a chain cannot
      // be taken for the narrower line joining the chain.
      const reach = Math.trunc((held / MILLISECONDS) * layout.pixelsPerSecond);
      const run = layout.later(spot.y, reach);
      const end = layout.flip ? Math.min(run, layout.limit()) : Math.max(run, layout.limit());
      shapes.push(
        {
          color,
          height: Math.abs(end - spot.y),
          kind: 'rect',
          width: 2 * Math.floor(HOLD_WIDTH / 2),
          x: spot.x - Math.floor(HOLD_WIDTH / 2),
          y: Math.min(spot.y, end),
        },
        {
          color,
          kind: 'line',
          points: [spot.x - HOLD_WIDTH, end, spot.x + HOLD_WIDTH, end],
          width: 2 * RULE_WIDTH,
        },
      );
    }
    shapes.push(
      ...discShapes(
        spot.x,
        spot.y,
        color,
        layout.flip,
        Boolean(note.flags & SIDE_OBJECT_FLAG),
        vertical,
      ),
    );
    at(spot.side, spot.column).notes.push({
      details: noteDetails(
        note,
        index,
        lanes.get(index) ?? null,
        version,
        held,
        sliding.has(index),
        vertical,
      ),
      index,
      lane: lanes.get(index) ?? null,
      shapes,
      x: spot.x,
      y: spot.y,
    });
  });
  return columns;
};
