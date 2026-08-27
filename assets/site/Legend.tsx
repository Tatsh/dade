// A drawn example of every mark, so the chart explains itself. A port of `_draw_legend` and its
// glyphs in `dade/rbplus/render.py`.
//
// Each mark is drawn from the same shapes the chart is, rather than described in words, so a change
// to how a note looks reaches the legend without anything else being edited.
import {
  BAR_WIDTH,
  COLORS,
  NOTE_RADIUS,
  SIDE_LABELS,
  SLIDE_DOT,
  SLIDE_WIDTH,
  SUPERSAMPLE,
  TEMPO_WIDTH,
  VEE_RISE,
  VEE_STROKE,
  VEE_WIDTH,
} from './chart/constants';
import { HOLD_WIDTH } from './chart/constants';

const BOX = 44;
const MIDDLE = BOX / 2;
const STEP = 9 * SUPERSAMPLE;
const HOLD_REACH = 12 * SUPERSAMPLE;

const disc = (x: number, y: number, color: string) => (
  <circle cx={x} cy={y} fill={color} r={NOTE_RADIUS} />
);

/** Every mark, against what it means. */
const MARKS: { draw: () => React.ReactNode; label: string }[] = [
  { draw: () => disc(MIDDLE, MIDDLE, COLORS.note[0]), label: `${SIDE_LABELS[0]} note` },
  { draw: () => disc(MIDDLE, MIDDLE, COLORS.note[1]), label: `${SIDE_LABELS[1]} note` },
  { draw: () => disc(MIDDLE, MIDDLE, COLORS.alternateTarget), label: 'Green' },
  {
    draw: () => (
      <>
        {disc(MIDDLE, MIDDLE, COLORS.note[1])}
        <path
          d={`M ${MIDDLE - NOTE_RADIUS} ${MIDDLE} A ${NOTE_RADIUS} ${NOTE_RADIUS} 0 0 0 ${
            MIDDLE + NOTE_RADIUS
          } ${MIDDLE} Z`}
          fill={COLORS.sideObject}
        />
      </>
    ),
    label: 'Swipe back',
  },
  {
    draw: () => (
      <>
        <rect
          fill={COLORS.note[1]}
          height={HOLD_REACH}
          width={HOLD_WIDTH}
          x={MIDDLE - HOLD_WIDTH / 2}
          y={MIDDLE - HOLD_REACH}
        />
        <line
          stroke={COLORS.note[1]}
          strokeWidth={2 * SUPERSAMPLE}
          x1={MIDDLE - HOLD_WIDTH}
          x2={MIDDLE + HOLD_WIDTH}
          y1={MIDDLE - HOLD_REACH}
          y2={MIDDLE - HOLD_REACH}
        />
        {disc(MIDDLE, MIDDLE, COLORS.note[1])}
      </>
    ),
    label: 'Hold',
  },
  {
    draw: () => (
      <>
        <polyline
          fill="none"
          points={`${MIDDLE - STEP} ${MIDDLE + STEP} ${MIDDLE} ${MIDDLE} ${MIDDLE + STEP} ${
            MIDDLE - STEP
          }`}
          stroke={COLORS.slide}
          strokeWidth={SLIDE_WIDTH}
        />
        <circle cx={MIDDLE} cy={MIDDLE} fill={COLORS.slide} r={SLIDE_DOT} />
        <circle cx={MIDDLE + STEP} cy={MIDDLE - STEP} fill={COLORS.slide} r={SLIDE_DOT} />
        {disc(MIDDLE - STEP, MIDDLE + STEP, COLORS.note[1])}
      </>
    ),
    label: 'Slide',
  },
  {
    draw: () => (
      <>
        {disc(MIDDLE, MIDDLE, COLORS.note[1])}
        <polyline
          fill="none"
          points={`${MIDDLE - Math.round(NOTE_RADIUS * VEE_WIDTH)} ${
            MIDDLE - Math.round(NOTE_RADIUS * VEE_RISE)
          } ${MIDDLE} ${MIDDLE + Math.round(NOTE_RADIUS * VEE_RISE)} ${
            MIDDLE + Math.round(NOTE_RADIUS * VEE_WIDTH)
          } ${MIDDLE - Math.round(NOTE_RADIUS * VEE_RISE)}`}
          stroke={COLORS.background}
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={VEE_STROKE}
        />
      </>
    ),
    label: 'Vertical',
  },
  {
    draw: () => (
      <>
        <line
          stroke={COLORS.note[1]}
          strokeWidth={BAR_WIDTH}
          x1={MIDDLE - STEP}
          x2={MIDDLE + STEP}
          y1={MIDDLE}
          y2={MIDDLE}
        />
        {[-STEP, 0, STEP].map((offset) => (
          <circle
            cx={MIDDLE + offset}
            cy={MIDDLE}
            fill={COLORS.note[1]}
            key={offset}
            r={NOTE_RADIUS}
          />
        ))}
      </>
    ),
    label: 'Chain',
  },
  {
    draw: () => (
      <line
        stroke={COLORS.tempo}
        strokeWidth={TEMPO_WIDTH}
        x1={MIDDLE - STEP}
        x2={MIDDLE + STEP}
        y1={MIDDLE}
        y2={MIDDLE}
      />
    ),
    label: 'Speed change',
  },
];

export const Legend = () => (
  <ul className="rb-legend list-unstyled small text-body-secondary mb-0">
    {MARKS.map((mark) => (
      <li key={mark.label}>
        <svg
          aria-hidden="true"
          className="rb-glyph"
          viewBox={`${MIDDLE - BOX / 2} ${MIDDLE - BOX / 2} ${BOX} ${BOX}`}
          xmlns="http://www.w3.org/2000/svg"
        >
          {mark.draw()}
        </svg>
        <span>{mark.label}</span>
      </li>
    ))}
  </ul>
);
