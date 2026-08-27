// The whole app: fetch the index, follow the hash, and show either the list or one chart.
//
// Every path is relative — `./data/…`, never `/data/…` — because GitHub Pages serves a project
// site from a subdirectory, and an absolute path would look for the data at the domain's root.
import { useCallback, useEffect, useRef, useState } from 'react';

import { ChartView, defaultView, type View } from './ChartView';
import { SongList } from './SongList';
import { parseChart } from './chart/parse';
import { isOneOf, useSetting } from './settings';
import {
  DIFFICULTIES,
  DIFFICULTY_LABELS,
  OPENED,
  base,
  difficulties,
  readRoute,
  writeRoute,
  type Charts,
  type Difficulty,
  type Filing,
  type Index,
  type Tune,
} from './browse';

const DATA = './data';

/** Whether a kept view is one this version still understands. */
const isView = (value: unknown): value is View => {
  if (!value || typeof value !== 'object') return false;
  const kept = value as Record<string, unknown>;
  return (
    typeof kept.flip === 'boolean' &&
    typeof kept.seed === 'number' &&
    typeof kept.showLanes === 'boolean' &&
    typeof kept.showTimes === 'boolean' &&
    typeof kept.speed === 'number' &&
    Array.isArray(kept.sides) &&
    kept.sides.length === 2 &&
    kept.sides.every((side) => typeof side === 'boolean')
  );
};

/** What is being shown, and why it is not the chart. */
type Status =
  | { kind: 'chart'; charts: Charts; difficulty: Difficulty; tune: Tune }
  | { kind: 'failed'; why: string }
  | { kind: 'list' }
  | { kind: 'loading' };

/**
 * A chart the reader opened from their own machine.
 *
 * The file is read in the page and nothing leaves it: there is no server here to send it to, and a
 * chart is somebody's own file. Only a deciphered chart is read — what a tune package holds is
 * enciphered, and the key belongs to the game.
 */
const openChart = async (file: File): Promise<{ charts: Charts; tune: Tune }> => {
  const chart = parseChart(new Uint8Array(await file.arrayBuffer()));
  return {
    // A chart file says what the notes are and nothing about which difficulty it is, so it is put
    // under the first name there is and that name is not shown.
    charts: { basic: chart },
    tune: {
      artist: '',
      artistReading: '',
      artistRomaji: '',
      bpm: [null, null],
      id: OPENED,
      letter: '?',
      levels: { basic: null },
      row: '?',
      special: null,
      title: file.name,
      titleReading: '',
      titleRomaji: '',
    },
  };
};

export const App = () => {
  const [index, setIndex] = useState<Index | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>({ kind: 'list' });
  // Every difficulty of a tune is in the one file, so changing difficulty is a matter of picking a
  // different chart out of what is already here. Fetching again would take the chart off the screen
  // and put it back unchanged.
  const [loaded, setLoaded] = useState<{ charts: Charts; id: number } | null>(null);
  // A chart the reader opened from their own machine, which is nowhere else. Held in a reference
  // rather than in state because the route is followed in the same breath as it is set: state set
  // now is not readable until the next drawing, and following would find nothing there and fall
  // back to the list.
  const opened = useRef<{ charts: Charts; tune: Tune } | null>(null);
  const [filing, setFiling] = useSetting<Filing>('filing', 'letter', isOneOf('letter', 'row'));
  const [view, setView] = useSetting<View>('view', defaultView(), isView);
  const [lastDifficulty, setLastDifficulty] = useSetting<Difficulty | ''>(
    'difficulty',
    '',
    isOneOf('', ...DIFFICULTIES),
  );
  // Where the reader happens to be, as against what they have chosen. Not kept.
  const [heading, setHeading] = useState<string | null>(null);
  const [query, setQuery] = useState('');

  useEffect(() => {
    fetch(`${DATA}/index.json`)
      .then((answer) => {
        if (!answer.ok) throw new Error(`the index answered ${answer.status}`);
        return answer.json() as Promise<Index>;
      })
      .then(setIndex)
      .catch((error: unknown) => setFailed(String(error)));
  }, []);

  // Which difficulty to open a tune at when the link does not say: the one last looked at, if that
  // tune has it, and otherwise its easiest.
  const settle = useCallback(
    (tune: Tune, charts: Charts, asked: Difficulty | null) => {
      const wanted = [asked, lastDifficulty, ...difficulties(tune)].find(
        (name): name is Difficulty => name !== null && name !== '' && name in charts,
      );
      if (!wanted) {
        setStatus({ kind: 'failed', why: 'That tune holds no chart that can be drawn.' });
        return;
      }
      setLastDifficulty(wanted);
      setStatus({ charts, difficulty: wanted, kind: 'chart', tune });
    },
    [lastDifficulty, setLastDifficulty],
  );

  const follow = useCallback(() => {
    if (!index) return;
    const route = readRoute();
    if (route.id === null) {
      setStatus({ kind: 'list' });
      return;
    }
    // A chart opened from the reader's own machine lives only in this page. Its address is worth
    // having so that the back button works, but a reload has nothing to read it from, so it falls
    // back to the list rather than to an error about a tune that never existed.
    if (route.id === OPENED) {
      const it = opened.current;
      if (it) {
        setStatus({ ...it, difficulty: 'basic', kind: 'chart' });
        return;
      }
      // Nothing was opened in this page, so this address names nothing — someone has reloaded, or
      // followed a link to it. The list is shown and the address is put back to the list's, in
      // place rather than as somewhere new, so that going back does not land here again.
      history.replaceState(null, '', writeRoute({ difficulty: null, id: null }));
      setStatus({ kind: 'list' });
      return;
    }
    const tune = index.tunes.find((one) => one.id === route.id);
    if (!tune) {
      setStatus({ kind: 'failed', why: `No tune ${route.id} here.` });
      return;
    }
    if (loaded?.id === tune.id) {
      settle(tune, loaded.charts, route.difficulty);
      return;
    }
    setStatus({ kind: 'loading' });
    fetch(`${DATA}/${tune.id}.json`)
      .then((answer) => {
        if (!answer.ok) throw new Error(`tune ${tune.id} answered ${answer.status}`);
        return answer.json() as Promise<Charts>;
      })
      .then((charts) => {
        setLoaded({ charts, id: tune.id });
        settle(tune, charts, route.difficulty);
      })
      .catch((error: unknown) => setStatus({ kind: 'failed', why: String(error) }));
  }, [index, loaded, settle]);

  // Both are listened for: `popstate` is what real paths raise, `hashchange` what the hash does.
  // Only one of them ever fires, since only one way of addressing the site is in use.
  useEffect(() => {
    follow();
    addEventListener('hashchange', follow);
    addEventListener('popstate', follow);
    return () => {
      removeEventListener('hashchange', follow);
      removeEventListener('popstate', follow);
    };
  }, [follow]);

  if (failed) return <p className="alert alert-danger">Could not read the index: {failed}</p>;
  if (!index) return <p className="text-body-secondary">Reading the index…</p>;

  // The route is always followed here rather than left to the event, because there may not be one:
  // a chart opened from the reader's own machine does not change the location, so going back to the
  // list writes the location it already had and the browser, rightly, says nothing has happened.
  // Following twice is harmless — it is the same route either way, and the tune is already read.
  const go = (id: number | null, difficulty: Difficulty | null = null) => {
    const where = writeRoute({ difficulty, id });
    if (base() === null) location.hash = where;
    else history.pushState(null, '', where);
    follow();
  };

  if (status.kind === 'list') {
    return (
      <SongList
        filing={filing}
        heading={heading}
        index={index}
        onFiling={setFiling}
        onHeading={setHeading}
        onOpen={(file) => {
          openChart(file)
            .then((it) => {
              opened.current = it;
              go(OPENED);
            })
            .catch((error: unknown) =>
              setStatus({ kind: 'failed', why: `${file.name}: ${String(error)}` }),
            );
        }}
        onQuery={setQuery}
        onTune={(tune) => go(tune.id)}
        query={query}
      />
    );
  }
  if (status.kind === 'loading') return <p className="text-body-secondary">Reading the chart…</p>;
  if (status.kind === 'failed') {
    return (
      <>
        <p className="alert alert-warning">{status.why}</p>
        <button className="btn btn-secondary" onClick={() => go(null)} type="button">
          Back to the list
        </button>
      </>
    );
  }

  const { charts, difficulty, tune } = status;
  return (
    <>
      <ChartView
        chart={charts[difficulty]!}
        difficulty={difficulty}
        heading={<TuneHeading go={go} difficulty={difficulty} tune={tune} />}
        onView={setView}
        tune={tune}
        view={view}
      />
    </>
  );
};

/**
 * A search of RemyWiki, which is where a tune is written about.
 *
 * Only on a tune's own page. In the list every title would be a link, which would make the list
 * read as a page of links rather than of tunes, and would take the reader away from it by accident.
 */
const Remy = ({ linked, what }: { linked: boolean; what: string }) =>
  what && linked ? (
    <a
      className="rb-remy"
      href={`https://remywiki.com/index.php?search=${encodeURIComponent(
        what,
      )}&title=Special%3ASearch&go=Go`}
      rel="noopener noreferrer"
      target="_blank"
    >
      {what}
    </a>
  ) : (
    <>{what}</>
  );

/** What the tune is called and which difficulties it has. */
const TuneHeading = ({
  difficulty,
  go,
  tune,
}: {
  difficulty: Difficulty;
  go: (id: number | null, difficulty?: Difficulty | null) => void;
  tune: Tune;
}) => (
  <header className="rb-top d-flex flex-wrap align-items-center gap-3">
    <button className="btn btn-sm btn-secondary" onClick={() => go(null)} type="button">
      ←
    </button>
    <div>
      {/* A chart opened from the reader's own machine is titled by its file name, which there is
          nothing to look up. Only a tune from the collection is linked. */}
      <h1 className="h5 mb-0">
        <Remy linked={tune.id !== OPENED} what={tune.title} />
      </h1>
      <p className="small text-body-secondary mb-0">
        <Remy linked={tune.id !== OPENED} what={tune.artist} />
      </p>
    </div>
    {/* A chart file does not say which difficulty it is, so there is nothing to choose between and
        nothing true to call what is shown. */}
    <div
      aria-label="Difficulty"
      className="btn-group btn-group-sm"
      hidden={tune.id === OPENED}
      role="group"
    >
      {difficulties(tune).map((name) => (
        <button
          className={`btn btn-outline-secondary${name === difficulty ? ' active' : ''}`}
          data-difficulty={name}
          key={name}
          onClick={() => go(tune.id, name)}
          type="button"
        >
          {DIFFICULTY_LABELS[name]} {tune.levels[name] ?? '?'}
        </button>
      ))}
    </div>
  </header>
);
