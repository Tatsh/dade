// Where a chart's columns, lanes, and times land. A port of `_Layout` in
// `dade/rbplus/render.py`.
//
// One thing is deliberately different. The renderer draws every column of both sides onto a single
// image, so its coordinates are absolute and a column has to be found by its side and its number.
// The site draws each column into an SVG of its own, so a column's origin is always zero and the
// band always starts at the top. Everything that decides *where in time* something falls is
// unchanged; only the frame it is measured against is smaller.
import {
  GUTTER,
  HOLD_NOTE_TYPE,
  LANE_COUNT,
  LANE_PX,
  MILLISECONDS,
  PIXELS_PER_SECOND,
} from './constants';
import type { Chart, Note } from './types';

/** How long a hold note is held, in milliseconds, or zero when it is not one. */
export const holdLength = (note: Note) => (note.type === HOLD_NOTE_TYPE ? note.target[0] : 0);

/**
 * The first and last millisecond the chart has to cover.
 *
 * The end comes from the notes rather than the chart's own end time, which can fall a little past
 * the last of them. A hold reaches past the note that starts it and is counted.
 */
export const columnSpan = (notes: Note[], endTime: number): [number, number] => {
  if (!notes.length) return [0, Math.max(endTime, 1)];
  const first = Math.min(...notes.map((note) => note.hit_time), 0);
  const last = Math.max(...notes.map((note) => note.hit_time + holdLength(note)));
  return [first, Math.max(last, first + 1)];
};

/** Where a chart's columns, lanes, and times land. */
export class Layout {
  /** The band's bottom edge, being the height of one column. */
  readonly bottom: number;
  /** How many columns the chart fills. */
  readonly columns: number;
  /** How tall one column is. */
  readonly columnHeight: number;
  /** How wide one column is, its gutter included. */
  readonly columnWidth: number;
  /** Whether time runs downward rather than upward. */
  readonly flip: boolean;
  /** How many lanes are drawn, used or not. */
  readonly lanes = LANE_COUNT;
  /** How far one second reaches. */
  readonly pixelsPerSecond: number;
  /** How many seconds one column holds. */
  readonly secondsPerColumn: number;
  /** How many milliseconds one column holds. */
  readonly spanMs: number;
  /** The first millisecond drawn. */
  readonly startMs: number;
  /** The band's top edge, which is always zero here. */
  readonly top = 0;

  private constructor(init: {
    columns: number;
    columnHeight: number;
    flip: boolean;
    pixelsPerSecond: number;
    secondsPerColumn: number;
    spanMs: number;
    startMs: number;
  }) {
    this.bottom = init.columnHeight;
    this.columns = init.columns;
    this.columnHeight = init.columnHeight;
    this.columnWidth = GUTTER + LANE_COUNT * LANE_PX;
    this.flip = init.flip;
    this.pixelsPerSecond = init.pixelsPerSecond;
    this.secondsPerColumn = init.secondsPerColumn;
    this.spanMs = init.spanMs;
    this.startMs = init.startMs;
  }

  /**
   * Lay a chart out.
   *
   * @param chart The parsed chart.
   * @param secondsPerColumn How many seconds one column holds.
   * @param speed The speed modifier, which spreads the notes further apart without changing how
   *   much time a column holds, exactly as it does in play.
   * @param flip Whether time runs downward.
   */
  static forChart(chart: Chart, secondsPerColumn: number, speed: number, flip: boolean) {
    const [startMs, endMs] = columnSpan(chart.notes, chart.header.end_time);
    const spanMs = secondsPerColumn * MILLISECONDS;
    const pixelsPerSecond = Math.round(PIXELS_PER_SECOND * speed);
    return new Layout({
      columns: Math.max(1, Math.ceil((endMs - startMs) / spanMs)),
      columnHeight: secondsPerColumn * pixelsPerSecond,
      flip,
      pixelsPerSecond,
      secondsPerColumn,
      spanMs,
      startMs,
    });
  }

  /** The middle of one lane, measured from the column's own left edge. */
  laneCenter(lane: number) {
    return GUTTER + lane * LANE_PX + Math.floor(LANE_PX / 2);
  }

  /**
   * The column and the row a time lands on, or null when it falls outside the chart.
   *
   * Time runs upward by default, so the earliest moment in a column sits at its bottom edge.
   */
  place(timeMs: number): { column: number; y: number } | null {
    const offset = timeMs - this.startMs;
    // Python floors towards negative infinity and JavaScript truncates towards zero, so a time
    // before the first note would land in column -0 rather than out of the chart.
    const column = Math.floor(offset / this.spanMs);
    if (column < 0 || column >= this.columns) return null;
    const within = Math.trunc(
      ((((offset % this.spanMs) + this.spanMs) % this.spanMs) / MILLISECONDS) *
        this.pixelsPerSecond,
    );
    return { column, y: this.flip ? this.top + within : this.bottom - within };
  }

  /** Where a moment `distance` further on lands, which is the way a hold runs from its note. */
  later(y: number, distance: number) {
    return this.flip ? y + distance : y - distance;
  }

  /** The band edge a hold is clipped to, being the one time runs towards. */
  limit() {
    return this.flip ? this.bottom : this.top;
  }
}

export type { Chart, Note };
