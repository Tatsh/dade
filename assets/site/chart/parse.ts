// Reading an RBFF chart in the browser. A port of `parse_chart` and its readers in
// `dade/rbplus/chart.py`, so that a chart file can be dropped on the page and drawn without going
// back through the command.
//
// Only a deciphered chart is read. What a tune package holds is enciphered, and nothing here
// deciphers: the key belongs to the game and the page has no business carrying it.
import { SLIDE_LANE_REMAP } from './constants';
import type { Chart, Note, Slide, TempoEvent } from './types';

/** The four bytes a chart opens with. */
const MAGIC = 'RBFF';
/** The format versions this parser reads. */
const MODERN_VERSIONS = [10, 11, 12, 13, 14];
/** The format versions the game reads with an older parser, which is not ported. */
const LEGACY_VERSIONS = [6, 7];

const FILE_HEADER_SIZE = 16;
const VERSION_OFFSET = 4;
const NOTES_OFFSET = 0x1c;
const TEMPO_EVENT_SIZE = 36;
const NOTE_TRAILER_SIZE = 8;
const LONG_HEAD_FLAG = 0x08;

/** The three lane values that are markers rather than lanes. */
const SLIDE_LANE_SENTINELS: Record<number, number> = {
  0xfffc: -3,
  0xfffd: -4,
  0xfffe: -2,
  0xffff: -2,
};

/** Raised when a file is not a chart this reads. */
export class ChartError extends Error {}

/** A cursor over the bytes, which reads little-endian and keeps its own place. */
class Reader {
  at: number;
  private readonly view: DataView;

  constructor(
    private readonly bytes: Uint8Array,
    at = 0,
  ) {
    this.view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    this.at = at;
  }

  /** Whether there are `count` bytes still to read from `at`. */
  private room(count: number, what: string) {
    if (this.at + count > this.bytes.length) {
      throw new ChartError(`Chart ends inside ${what} at offset ${this.at}.`);
    }
  }

  i8(what: string) {
    this.room(1, what);
    return this.view.getInt8(this.at++);
  }

  i16(what: string) {
    this.room(2, what);
    const value = this.view.getInt16(this.at, true);
    this.at += 2;
    return value;
  }

  u16(what: string) {
    this.room(2, what);
    const value = this.view.getUint16(this.at, true);
    this.at += 2;
    return value;
  }

  i32(what: string) {
    this.room(4, what);
    const value = this.view.getInt32(this.at, true);
    this.at += 4;
    return value;
  }

  u32(what: string) {
    this.room(4, what);
    const value = this.view.getUint32(this.at, true);
    this.at += 4;
    return value;
  }

  skip(count: number, what: string) {
    this.room(count, what);
    this.at += count;
  }

  hex(count: number, what: string) {
    this.room(count, what);
    const slice = this.bytes.subarray(this.at, this.at + count);
    this.at += count;
    return [...slice].map((byte) => byte.toString(16).padStart(2, '0')).join('');
  }
}

const slideLane = (raw: number) => {
  const sentinel = SLIDE_LANE_SENTINELS[raw];
  if (sentinel !== undefined) return sentinel;
  if (raw >= 0 && raw < SLIDE_LANE_REMAP.length) return SLIDE_LANE_REMAP[raw];
  // The engine indexes its remap table unguarded; reporting the raw lane is safer than reading
  // past the table as it would.
  return raw;
};

/** One note. A note is variable length, so the cursor is carried on rather than computed. */
const readNote = (read: Reader): Note => {
  const spawn_time = read.i32('a note');
  const travel_time = read.i32('a note');
  const id = read.i16('a note');
  const start_time = read.i16('a note');
  const pointCount = read.i16('a note');
  const path_points: number[] = [];
  for (let point = 0; point < pointCount; point += 1) path_points.push(read.i16('a path point'));
  const kind = read.i8('a note');
  const side = read.i8('a note');
  const hold_kind = read.i8('a note');
  const type = read.i8('a note');
  const target: [number, number, number, number] = [
    read.i16('a note target'),
    read.i16('a note target'),
    read.i16('a note target'),
    read.i16('a note target'),
  ];
  const flags = read.u32('a note');
  // The engine reads these four fields into its staging record and never unpacks them again. They
  // are stepped over here rather than ignored, so that a chart ending inside them is caught.
  read.skip(NOTE_TRAILER_SIZE, "a note's trailer");
  let chain: [number, number, number, number] | null = null;
  if (flags & LONG_HEAD_FLAG) {
    chain = [read.i16('a chain'), read.i16('a chain'), read.i32('a chain'), read.i32('a chain')];
  }
  return {
    chain,
    flags,
    hit_time: spawn_time + travel_time,
    hold_kind,
    id,
    kind,
    path_points,
    side,
    spawn_time,
    start_time,
    target,
    travel_time,
    type,
  };
};

// Three fields are read out of the event and the whole of it is kept as hex besides, since most of
// its thirty-six bytes are undocumented and throwing them away would lose what has not been worked
// out yet.
const readTempoEvent = (read: Reader): TempoEvent => {
  const start = read.at;
  const kind = read.i16('a tempo event');
  read.at = start + 0x04;
  const time = read.i32('a tempo event');
  read.at = start + 0x10;
  const speed = read.i32('a tempo event');
  read.at = start;
  const raw = read.hex(TEMPO_EVENT_SIZE, 'a tempo event');
  return { kind, raw, speed, time };
};

const readSlide = (read: Reader): Slide => {
  const note_index = read.u16('a slide');
  const field2 = read.u16('a slide');
  const raw = read.u16('a slide');
  read.skip(2, 'a slide');
  const value_a = read.i32('a slide');
  const value_b = read.i32('a slide');
  return { field2, lane: slideLane(raw), note_index, value_a, value_b };
};

/**
 * Read a deciphered RBFF chart.
 *
 * @param bytes The chart, as it is stored once deciphered.
 * @throws ChartError If the magic is wrong, the version is one this does not read, or the stream
 *   ends inside a record.
 */
export const parseChart = (bytes: Uint8Array): Chart => {
  const magic = [...bytes.subarray(0, 4)].map((byte) => String.fromCharCode(byte)).join('');
  if (magic !== MAGIC) {
    throw new ChartError(`Not a chart: expected ${MAGIC}, got ${JSON.stringify(magic)}.`);
  }
  const head = new Reader(bytes, VERSION_OFFSET);
  const version = head.u32('the header');
  if (!MODERN_VERSIONS.includes(version)) {
    const known = LEGACY_VERSIONS.includes(version)
      ? 'the legacy layout, which is not read here'
      : 'no known layout';
    throw new ChartError(`Chart format version ${version} uses ${known}.`);
  }
  const read = new Reader(bytes, FILE_HEADER_SIZE);
  const initial_speed = read.i32('the header');
  const end_time = read.i32('the header');
  const seed = read.i32('the header');
  const note_count = read.i16('the header');
  const tempo_event_count = read.i16('the header');
  const free_note_count = read.i16('the header');
  read.at = FILE_HEADER_SIZE + 0x14;
  const slide_record_count = read.i32('the header');

  read.at = FILE_HEADER_SIZE + NOTES_OFFSET;
  const notes: Note[] = [];
  for (let note = 0; note < note_count; note += 1) notes.push(readNote(read));
  const tempo_events: TempoEvent[] = [];
  for (let event = 0; event < tempo_event_count; event += 1)
    tempo_events.push(readTempoEvent(read));
  const slides: Slide[] = [];
  for (let slide = 0; slide < Math.max(slide_record_count, 0); slide += 1) {
    slides.push(readSlide(read));
  }
  return {
    header: {
      end_time,
      free_note_count,
      initial_speed,
      note_count,
      seed,
      slide_record_count,
      tempo_event_count,
      version,
    },
    notes,
    slides,
    tempo_events,
  };
};
