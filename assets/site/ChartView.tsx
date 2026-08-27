// One chart, drawn. The controls decide the layout, the layout decides the shapes, and
// `ChartColumn` turns those into elements; nothing here draws anything itself.
import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import { ChartColumn } from './ChartColumn';
import { Legend } from './Legend';
import { SECONDS_PER_COLUMN, SIDE_LABELS } from './chart/constants';
import { Layout } from './chart/layout';
import { noteLanes } from './chart/lanes';
import { chartColumns, type DrawnNote } from './chart/shapes';
import type { Chart } from './chart/types';
import { DIFFICULTY_LABELS, type Difficulty, type Tune } from './browse';

/** What the reader can change about how a chart is shown. */
export interface View {
  /**
   * Whether the chart is made to fit the window, height and all.
   *
   * A column is cut down until it stands no taller than the window has room for, and the columns
   * are then set in one row that runs off the side and is read by scrolling across, rather than
   * wrapping and taking the page down with them. Nothing shrinks: a note is the size it always was
   * and there are simply more columns.
   *
   * A column is only ever cut at a whole second, so one second is the shortest it can be. A window
   * too short even for that gets one and scrolls, there being nothing smaller to cut to.
   */
  fit: boolean;
  /** Whether time runs downward rather than upward. */
  flip: boolean;
  /** The lane seed, which names one of the layouts the game would pick between. */
  seed: number;
  /** Whether the lane divisions are drawn. */
  showLanes: boolean;
  /** Whether the seconds and beats are drawn. */
  showTimes: boolean;
  /** Which sides are shown. */
  sides: [boolean, boolean];
  /** The speed modifier, 1.0 to 2.0. */
  speed: number;
}

/**
 * How a chart is shown before anything has been chosen.
 *
 * Fitted, both sides, both rulings, the chart's own spacing, and the first lane layout. A chart
 * that fills the window and no more is the one that can be read without scrolling for it.
 */
export const DEFAULT_VIEW: View = {
  fit: true,
  flip: false,
  seed: 0,
  showLanes: true,
  showTimes: true,
  sides: [true, true],
  speed: 1,
};

/** The room left under the last column, so it does not sit against the window's edge. */
const FOOT = 8;

/** What the chart has to share the window with, measured from the page rather than assumed. */
interface Room {
  /** The gap between one side and the next. */
  gap: number;
  /**
   * How tall the window is.
   *
   * Kept here rather than read where it is used. Nothing else in this changes when the window is
   * made shorter or taller — the chart begins where it began, and a heading is the height it was —
   * so without the height the measurement would compare equal to the last one, nothing would be
   * redrawn, and the chart would keep the shape it had until the page was loaded again.
   */
  height: number;
  /** What sits under the chart, being the legend. */
  under: number;
  /** What one side costs besides its columns: its heading, and the room the labels paint into. */
  overhead: number;
  /** Where the sides begin, from the top of the document. */
  top: number;
}

/**
 * How tall one second stands, read back from the stylesheet.
 *
 * The stylesheet is where that is settled, since it is what gives a column its height. Reading it
 * back is what stops the number being written down twice and drifting.
 */
const secondPx = () => {
  const kept = getComputedStyle(document.documentElement).getPropertyValue('--rb-second');
  return Number.parseFloat(kept) || 46;
};

/**
 * How many seconds a column holds so that the whole chart fits the window.
 *
 * The room is measured from where the chart actually begins rather than guessed at. What sits above
 * it changes with the window — the controls take one line or two, the title wraps or does not — so
 * a fixed allowance is either wrong or wasteful, and being wasteful shows as a band of nothing
 * under the chart.
 *
 * Both sides are stacked when both are shown, so the room is shared between them: a chart that
 * fitted only because half of it was off the bottom would not be fitted at all.
 *
 * A column is only ever cut at a whole second, so one second is the shortest it can be. A window
 * too short even for one gets one and scrolls.
 */
const secondsThatFit = (room: Room, secondPx: number, speed: number, sides: number) => {
  const left =
    room.height - room.top - room.under - FOOT - sides * room.overhead - (sides - 1) * room.gap;
  return Math.max(1, Math.floor(left / (sides * secondPx * speed)));
};

interface ChartViewProps {
  chart: Chart;
  difficulty: Difficulty;
  /**
   * What the tune is called and which difficulties it has, set beside the controls rather than
   * above them. On a wide enough screen the two sit on one line and the chart gets the height.
   */
  heading: ReactNode;
  onView: (view: View) => void;
  tune: Tune;
  view: View;
}

/**
 * Whether a value is set in a fixed width.
 *
 * A bare number and the flag word are, since a column of them is read against the one above it and
 * they line up only if every digit is the same width. A time is not: it is a sentence with a unit
 * on the end, read on its own, and setting it in a typewriter face only makes it harder to read.
 */
const fixed = (value: string) => !value.endsWith(' ms') && /[\d|]/.test(value);

const Tip = ({ note, at }: { at: { x: number; y: number }; note: DrawnNote }) => {
  const GAP = 14;
  return (
    <dl
      className="rb-tip card shadow p-2 d-grid mb-0 small"
      style={{ insetBlockStart: at.y + GAP, insetInlineStart: at.x + GAP }}
    >
      {Object.entries(note.details).map(([key, value]) => (
        <div className="rb-tip-row" key={key}>
          <dt className="fw-normal text-body-secondary">{key}</dt>
          <dd className={`mb-0${fixed(value) ? ' rb-mono' : ''}`}>{value}</dd>
        </div>
      ))}
    </dl>
  );
};

export const ChartView = ({ chart, difficulty, heading, onView, tune, view }: ChartViewProps) => {
  const [hovered, setHovered] = useState<{ at: { x: number; y: number }; note: DrawnNote } | null>(
    null,
  );
  // Fitting shortens a column rather than shrinking it, so the notes stay the size they were and
  // there are simply more columns. Where the chart begins is measured rather than assumed, and
  // measured again on a resize, since that is what decides how much room is left for it.
  const sides = useRef<HTMLDivElement>(null);
  const legend = useRef<HTMLDivElement>(null);
  const [room, setRoom] = useState<Room | null>(null);
  useLayoutEffect(() => {
    const measure = () => {
      const box = sides.current?.getBoundingClientRect();
      if (!box) return;
      const columns = sides.current?.querySelector('.rb-columns');
      const style = columns ? getComputedStyle(columns) : null;
      const under = legend.current?.getBoundingClientRect().height ?? 0;
      setRoom((was) => {
        const now = {
          gap: Number.parseFloat(getComputedStyle(sides.current!).rowGap) || 0,
          height: window.innerHeight,
          // What a side spends before its first column: its heading, and the room the second
          // labels paint into above and below the columns.
          overhead: columns
            ? Math.round(columns.getBoundingClientRect().top - box.top) +
              (Number.parseFloat(style?.paddingBottom ?? '0') || 0)
            : 0,
          top: Math.round(box.top + window.scrollY),
          under: Math.ceil(under),
        };
        // The measurement decides the column height, which decides where things are, so a new
        // object every time would measure and re-render for ever. Only a real change is kept.
        return was &&
          was.gap === now.gap &&
          was.height === now.height &&
          was.overhead === now.overhead &&
          was.top === now.top &&
          was.under === now.under
          ? was
          : now;
      });
    };
    measure();
    addEventListener('resize', measure);
    return () => removeEventListener('resize', measure);
  });

  const shownSides = Math.max(1, view.sides.filter(Boolean).length);
  // What the arithmetic above cannot know: every side rounds its own height up to a whole pixel,
  // and a border or a hairline gap can land either side of one. Rather than guess at that, the page
  // is measured once it is drawn and a second is given back if it still does not fit. It converges
  // in a pass or two and only ever shortens, so it cannot oscillate.
  const [giveBack, setGiveBack] = useState(0);
  // `room` is among these on purpose. Before it is measured there is nothing to fit against, so
  // that first drawing is a full-length column and overflows by a long way; correcting against it
  // would give back most of the column and leave every second a box of its own. Forgetting the
  // correction the moment the measurement arrives is what stops that.
  useLayoutEffect(() => setGiveBack(0), [view.fit, view.speed, shownSides, chart, room]);
  const seconds =
    view.fit && room
      ? Math.max(
          1,
          Math.min(SECONDS_PER_COLUMN, secondsThatFit(room, secondPx(), view.speed, shownSides)) -
            giveBack,
        )
      : SECONDS_PER_COLUMN;
  useLayoutEffect(() => {
    if (!view.fit || !room || seconds <= 1) return;
    const over = document.documentElement.scrollHeight - window.innerHeight;
    if (over > 0) {
      setGiveBack((was) => was + Math.max(1, Math.ceil(over / (secondPx() * view.speed))));
    }
  });

  const { columns, layout } = useMemo(() => {
    const made = Layout.forChart(chart, seconds, view.speed, view.flip);
    const lanes = noteLanes(chart.notes, chart.header.version, view.seed);
    return { columns: chartColumns(chart, made, lanes, tune.bpm[0] ?? null), layout: made };
  }, [chart, seconds, tune.bpm, view.flip, view.seed, view.speed]);

  const set = (change: Partial<View>) => onView({ ...view, ...change });

  return (
    <section className="rb-chart">
      {/* The tune and the controls share one row and wrap onto their own when the window is too
          narrow to hold both, so a wide screen spends its width rather than its height. */}
      <div className="rb-bar">
        {heading}
        <form
          className="rb-controls card card-body d-flex flex-row flex-wrap align-items-center"
          onSubmit={(event) => event.preventDefault()}
        >
          {/* The last side left on cannot be switched off: a chart with neither side is nothing to
            look at, and the way back from it is not obvious. */}
          {SIDE_LABELS.map((label, side) => {
            const only = view.sides[side] && view.sides.filter(Boolean).length === 1;
            return (
              <div className="form-check form-switch mb-0" key={label}>
                <input
                  checked={view.sides[side]}
                  className="form-check-input"
                  disabled={only}
                  id={`rb-side-${side}`}
                  onChange={(event) =>
                    set({
                      sides:
                        side === 0
                          ? [event.target.checked, view.sides[1]]
                          : [view.sides[0], event.target.checked],
                    })
                  }
                  role="switch"
                  type="checkbox"
                />
                <label
                  className="form-check-label small"
                  htmlFor={`rb-side-${side}`}
                  title={only ? 'The last side shown cannot be hidden.' : undefined}
                >
                  {label}
                </label>
              </div>
            );
          })}
          <div className="form-check form-switch mb-0">
            <input
              checked={view.flip}
              className="form-check-input"
              id="rb-flip"
              onChange={(event) => set({ flip: event.target.checked })}
              role="switch"
              type="checkbox"
            />
            <label
              className="form-check-label small"
              htmlFor="rb-flip"
              title="Read each column top to bottom, the way the notes fall."
            >
              Flip
            </label>
          </div>
          <div className="form-check form-switch mb-0">
            <input
              checked={view.fit}
              className="form-check-input"
              id="rb-fit"
              onChange={(event) => set({ fit: event.target.checked })}
              role="switch"
              type="checkbox"
            />
            <label className="form-check-label small" htmlFor="rb-fit">
              Fit to window
            </label>
          </div>
          <div className="form-check form-switch mb-0">
            <input
              checked={view.showTimes}
              className="form-check-input"
              id="rb-times"
              onChange={(event) => set({ showTimes: event.target.checked })}
              role="switch"
              type="checkbox"
            />
            <label className="form-check-label small" htmlFor="rb-times">
              Time lines
            </label>
          </div>
          <div className="form-check form-switch mb-0">
            <input
              checked={view.showLanes}
              className="form-check-input"
              id="rb-lanes"
              onChange={(event) => set({ showLanes: event.target.checked })}
              role="switch"
              type="checkbox"
            />
            <label className="form-check-label small" htmlFor="rb-lanes">
              Lane lines
            </label>
          </div>
          <label className="small mb-0 d-flex align-items-center gap-2" htmlFor="rb-speed">
            Speed {view.speed.toFixed(1)}
            <input
              className="form-range"
              id="rb-speed"
              max={2}
              min={1}
              onChange={(event) => set({ speed: Number(event.target.value) })}
              step={0.1}
              style={{ inlineSize: '8rem' }}
              type="range"
              value={view.speed}
            />
          </label>
          <label className="small mb-0 d-flex align-items-center gap-2" htmlFor="rb-seed">
            Lane seed
            <input
              className="form-control form-control-sm"
              id="rb-seed"
              onChange={(event) => set({ seed: Number(event.target.value) || 0 })}
              style={{ inlineSize: '7rem' }}
              type="number"
              value={view.seed}
            />
          </label>
        </form>
      </div>
      {/* The speed modifier reaches the drawing through the height a column is given: the layout
          makes the column taller and this lets it be taller on the screen. */}
      <div
        className={`rb-sides${view.fit ? ' rb-fitted' : ''}`}
        ref={sides}
        style={
          {
            '--rb-seconds-per-column': layout.secondsPerColumn,
            '--rb-speed': view.speed,
          } as React.CSSProperties
        }
      >
        {SIDE_LABELS.map((label, side) =>
          view.sides[side] ? (
            <section data-side={side} key={label}>
              <h2 className="h6" style={{ color: `var(--rb-side-${side})` }}>
                {label}
              </h2>
              <div className="rb-columns">
                {columns
                  .filter((column) => column.side === side)
                  .map((column) => (
                    <ChartColumn
                      column={column}
                      key={column.column}
                      layout={layout}
                      onNote={(note, at) => setHovered(note && at ? { at, note } : null)}
                      showLanes={view.showLanes}
                      showTimes={view.showTimes}
                    />
                  ))}
              </div>
            </section>
          ) : null,
        )}
      </div>
      {/* Under the chart rather than over it. It is read once and then known, so it should not be
          spending the height the chart wants every time the page is opened. Its height is measured
          and taken off the chart's budget, so fitting the window still fits. */}
      <div ref={legend}>
        <Legend />
      </div>
      {hovered && <Tip at={hovered.at} note={hovered.note} />}
    </section>
  );
};
