// The shapes `dade rbplus site` writes, which mirror `dade/rbplus/typing.py`. The keys are the
// Python ones so that what is emitted and what is read here can be compared without a translation
// step in between.

/** One note as it is stored in an RBFF chart. */
export interface Note {
  /** The chain block a long-note head carries, or null. */
  chain: [number, number, number, number] | null;
  /** The note flag bits. */
  flags: number;
  /** When the note must be hit, in milliseconds: `spawn_time` plus `travel_time`. */
  hit_time: number;
  /** 1 marks a hold's head, the engine's `kHoldKindHead`. */
  hold_kind: number;
  /** The note identifier, which another note's chain fields refer to. */
  id: number;
  /** The note's place in its chain, counting from zero. */
  kind: number;
  /** The note's path-point coordinates, empty when it carries no path. */
  path_points: number[];
  /** The play side, 0 or 1. The two sides are separate sets of notes. */
  side: number;
  /** When the note appears, in milliseconds. Often negative: a chart starts before its audio. */
  spawn_time: number;
  /** The chain the note belongs to, or -1 when the note is free. */
  start_time: number;
  /** The four target coordinates. The first is a hold's length; the second selects a target. */
  target: [number, number, number, number];
  /** How long the note takes to reach the player, in milliseconds. */
  travel_time: number;
  /** The note type. 1 is a hold, 2 a slide. */
  type: number;
}

/** One tempo or speed-change event. */
export interface TempoEvent {
  /** The event kind. Kind 3 is a speed change. */
  kind: number;
  /** The whole thirty-six byte event as hexadecimal. */
  raw: string;
  /** The scroll speed the event installs, meaningful for kind 3. */
  speed: number;
  /** The event's time, in milliseconds. */
  time: number;
}

/** One slide record, being one waypoint of one sliding note. */
export interface Slide {
  /** The record's second short, whose meaning is not established. It orders the waypoints. */
  field2: number;
  /** The remapped target lane, or a negative marker for the three sentinel values. */
  lane: number;
  /** The index of the note the slide belongs to. */
  note_index: number;
  /** The record's first trailing integer. With `value_b`, the moment the finger is to be there. */
  value_a: number;
  /** The record's second trailing integer. */
  value_b: number;
}

/** An RBFF chart's header. */
export interface ChartHeader {
  /** The chart's end time, in milliseconds. */
  end_time: number;
  /** How many of the notes are free notes. */
  free_note_count: number;
  /** The scroll speed the chart starts at. */
  initial_speed: number;
  /** How many notes the chart holds. */
  note_count: number;
  /** The chart's own seed value, which is not the lane seed. */
  seed: number;
  /** How many slide records follow the tempo events. */
  slide_record_count: number;
  /** How many tempo events follow the notes. */
  tempo_event_count: number;
  /** The chart format version, which decides how a note's route selector is read. */
  version: number;
}

/** A whole parsed RBFF chart. */
export interface Chart {
  /** The chart header. */
  header: ChartHeader;
  /** Every note, in stream order. */
  notes: Note[];
  /** Every slide record, in stream order. */
  slides: Slide[];
  /** Every tempo event, in stream order. */
  tempo_events: TempoEvent[];
}
