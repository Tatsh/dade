// One column of one side, as SVG. Every shape `shapes.ts` produces has a case here and nothing
// else does any drawing, so what is on the screen is what that module decided.
import type { JSX } from 'react';

import { COLORS, GUTTER, LANE_PX, SMALL_SIZE } from './chart/constants';
import type { Column, DrawnNote, Shape } from './chart/shapes';
import type { Layout } from './chart/layout';

/** Half a disc, as the arc across it and back along its diameter. */
const halfPath = (x: number, y: number, radius: number, down: boolean) => {
  const sweep = down ? 1 : 0;
  return `M ${x - radius} ${y} A ${radius} ${radius} 0 0 ${sweep} ${x + radius} ${y} Z`;
};

const draw = (shape: Shape, key: number): JSX.Element => {
  switch (shape.kind) {
    case 'disc':
      return <circle cx={shape.x} cy={shape.y} fill={shape.color} key={key} r={shape.radius} />;
    case 'half':
      return (
        <path
          d={halfPath(shape.x, shape.y, shape.radius, shape.down)}
          fill={shape.color}
          key={key}
        />
      );
    case 'rect':
      return (
        <rect
          fill={shape.color}
          height={shape.height}
          key={key}
          width={shape.width}
          x={shape.x}
          y={shape.y}
        />
      );
    case 'line':
      return (
        <polyline
          fill="none"
          key={key}
          points={shape.points.join(' ')}
          stroke={shape.color}
          strokeLinecap={shape.round ? 'round' : 'butt'}
          strokeLinejoin={shape.round ? 'round' : 'miter'}
          strokeWidth={shape.width}
        />
      );
  }
};

/** What one column is asked to draw. */
export interface ChartColumnProps {
  column: Column;
  layout: Layout;
  /** Told which note the pointer is on, or null when it leaves. */
  onNote: (note: DrawnNote | null, at: { x: number; y: number } | null) => void;
  /** Whether the lane divisions are drawn. */
  showLanes: boolean;
  /** Whether the seconds and beats are drawn. */
  showTimes: boolean;
}

export const ChartColumn = ({ column, layout, onNote, showLanes, showTimes }: ChartColumnProps) => (
  <svg
    className="rb-column"
    preserveAspectRatio="none"
    viewBox={`0 ${layout.top} ${layout.columnWidth} ${layout.columnHeight}`}
    xmlns="http://www.w3.org/2000/svg"
  >
    {/* The track starts after the gutter, which is the room the seconds are named in. Drawing it
        across the whole column would put the chart under its own labels and take away the space
        that separates one column from the next. */}
    <rect
      fill={COLORS.trackFill}
      height={layout.columnHeight}
      stroke={COLORS.trackEdge}
      width={layout.lanes * LANE_PX}
      x={GUTTER}
      y={layout.top}
    />
    {showTimes && <g>{column.timeRules.map(draw)}</g>}
    {showLanes && <g>{column.laneRules.map(draw)}</g>}
    {/* The times are not ruling and stay whether the lines they name are drawn or not: they are
        what says where in the tune a column is. They sit in the gutter to the left of the track. */}
    <g>
      {column.seconds.map((second) => (
        <text
          dominantBaseline="middle"
          fill={COLORS.secondText}
          fontFamily="sans-serif"
          fontSize={SMALL_SIZE}
          key={second.label}
          x={0}
          y={second.y}
        >
          {second.label}
        </text>
      ))}
    </g>
    <g>{column.under.map(draw)}</g>
    {column.notes.map((note) => (
      <g
        className="rb-note"
        key={note.index}
        onBlur={() => onNote(null, null)}
        onFocus={(event) => {
          const box = event.currentTarget.getBoundingClientRect();
          onNote(note, { x: box.left + box.width / 2, y: box.bottom });
        }}
        onPointerEnter={(event) => onNote(note, { x: event.clientX, y: event.clientY })}
        onPointerLeave={() => onNote(null, null)}
        onPointerMove={(event) => onNote(note, { x: event.clientX, y: event.clientY })}
        tabIndex={0}
      >
        {note.shapes.map(draw)}
      </g>
    ))}
  </svg>
);
