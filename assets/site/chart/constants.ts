// The numbers a chart is drawn by. Every one of these is a port of the same name in
// `dade/rbplus/render.py`, which draws the PNG and the SVG. The two are separate implementations
// of one layout: change a number here and the same number has to change there, or a chart will
// look different depending on how it was asked for.

/**
 * The multiple the layout's units are of the finished size.
 *
 * The raster renderer draws large and reduces once at the end so that every edge is smoothed by the
 * reduction. Nothing here is reduced — an SVG in a browser has no such need — but the units are
 * kept the same so the two layouts are comparable number for number.
 */
export const SUPERSAMPLE = 3;

/** How many play sides a chart has. */
export const SIDE_COUNT = 2;
/** What the game shows each side as. */
export const SIDE_LABELS = ['Pink', 'Blue'] as const;
/** How many lanes the field has, the engine's `NoteLaneTracker::kLaneCount`. */
export const LANE_COUNT = 7;
/** How many seconds of chart one column holds by default. */
export const SECONDS_PER_COLUMN = 30;

/** The route selectors naming a target beyond the seven lanes, which the game draws green. */
export const ALTERNATE_TARGETS = [7, 8, 9];
/** The slot each alternative target is drawn in. */
export const ALTERNATE_TARGET_LANES = [5, 3, 1];
/** The note type that is held, the engine's `kNoteTypeHold`. */
export const HOLD_NOTE_TYPE = 1;
/** The note type that slides. */
export const SLIDE_NOTE_TYPE = 2;
/** The hold kind marking a hold's head, the engine's `kHoldKindHead`. */
export const HOLD_HEAD_KIND = 1;
/** The note flag marking a note that travels to the other side, to be swiped back. */
export const SIDE_OBJECT_FLAG = 0x20;
/** The event kind that installs a scroll speed. */
export const SPEED_CHANGE_KIND = 3;
/** How the engine remaps a slide's route selector to a lane, for charts newer than version 12. */
export const SLIDE_LANE_REMAP = [0, 1, 2, 3, 4, 5, 6];

/** The last chart version whose route selector is not remapped. */
export const REMAPPED_ROUTE_VERSION = 12;
/** The selector value meaning the note names no route at all. */
export const UNSET_ROUTE = -2;
/** Where a sixteen-bit route selector turns negative. */
export const SIGN_BIT = 0x8000;
/** The raw selector value that names no route. */
export const NO_ROUTE_SELECTOR = 0xfffe;
/** The group value that marks a free note, which belongs to no chain. */
export const FREE_NOTE_START_TIME = -1;
/** How many notes a run needs before it counts as a chain. */
export const CHAIN_MINIMUM = 2;

/** Colours, as the renderer gives them. */
export const COLORS = {
  alternateTarget: 'rgb(110 235 130)',
  background: 'rgb(24 24 32)',
  barLine: 'rgb(72 72 90)',
  beatLine: 'rgb(46 46 60)',
  grid: 'rgb(58 58 72)',
  laneLine: 'rgb(50 50 64)',
  note: ['rgb(255 120 180)', 'rgb(80 220 255)'],
  secondText: 'rgb(150 150 165)',
  sideObject: 'rgb(255 200 70)',
  slide: 'rgb(200 150 255)',
  tempo: 'rgb(255 90 210)',
  trackEdge: 'rgb(58 58 72)',
  trackFill: 'rgb(40 40 52)',
} as const;

/** Geometry, in the layout's own units. */
export const GUTTER = 52 * SUPERSAMPLE;
export const LANE_PX = 15 * SUPERSAMPLE;
export const PIXELS_PER_SECOND = 46 * SUPERSAMPLE;
export const NOTE_RADIUS = 5 * SUPERSAMPLE;
export const BAR_WIDTH = 3 * SUPERSAMPLE;
export const HOLD_WIDTH = 9 * SUPERSAMPLE;
export const SLIDE_WIDTH = 4 * SUPERSAMPLE;
export const SLIDE_DOT = 3 * SUPERSAMPLE;
export const RULE_WIDTH = SUPERSAMPLE;
export const TEMPO_WIDTH = 2 * SUPERSAMPLE;
export const SMALL_SIZE = 11 * SUPERSAMPLE;
export const VEE_STROKE = 2 * SUPERSAMPLE;
export const VEE_WIDTH = 0.55;
export const VEE_RISE = 0.4;

/** Time. */
export const MILLISECONDS = 1000;
export const SECONDS_PER_MINUTE = 60;
export const BEATS_PER_BAR = 4;
