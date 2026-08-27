// Finding a tune: search, the two ways of filing, and the list itself. What each of those means is
// `browse.ts`; this only shows it.
import { useMemo } from 'react';

import {
  DIFFICULTY_LABELS,
  difficulties,
  group,
  matches,
  type Filing,
  type Index,
  type Tune,
} from './browse';

interface SongListProps {
  filing: Filing;
  index: Index;
  onFiling: (filing: Filing) => void;
  onHeading: (heading: string | null) => void;
  /** Given a chart file the reader has picked, which is read here rather than sent anywhere. */
  onOpen: (file: File) => void;
  onQuery: (query: string) => void;
  onTune: (tune: Tune) => void;
  query: string;
  /** Which heading is shown on its own, or null for all of them. */
  heading: string | null;
}

export const SongList = ({
  filing,
  heading,
  index,
  onFiling,
  onHeading,
  onOpen,
  onQuery,
  onTune,
  query,
}: SongListProps) => {
  const headings = filing === 'letter' ? index.letters : index.rows;
  const groups = useMemo(
    () =>
      group(
        index.tunes.filter((tune) => matches(tune, query)),
        filing,
        headings,
      ),
    [filing, headings, index.tunes, query],
  );
  const shown = heading === null ? groups : groups.filter((one) => one.heading === heading);
  const found = shown.reduce((sum, one) => sum + one.tunes.length, 0);

  return (
    <section className="rb-list">
      <div className="d-flex flex-wrap gap-3 align-items-center mb-3">
        <label className="visually-hidden" htmlFor="rb-search">
          Search
        </label>
        <input
          className="form-control"
          id="rb-search"
          onChange={(event) => onQuery(event.target.value)}
          placeholder="Search by title or artist, in kana or in letters"
          style={{ maxInlineSize: '28rem' }}
          type="search"
          value={query}
        />
        {/* A chart from outside the collection. Only a deciphered one is read: what a tune package
            holds is enciphered, and the page carries no key. Nothing is uploaded — the file is read
            where it is. */}
        <label className="btn btn-sm btn-outline-secondary mb-0" htmlFor="rb-open">
          Open a chart file…
          <input
            accept=".bin,.dat,application/octet-stream"
            className="visually-hidden"
            id="rb-open"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = '';
              if (file) onOpen(file);
            }}
            type="file"
          />
        </label>
        <div aria-label="How to file" className="btn-group btn-group-sm" role="group">
          {(['letter', 'row'] as const).map((which) => (
            <button
              className={`btn btn-outline-secondary${filing === which ? ' active' : ''}`}
              key={which}
              onClick={() => {
                onFiling(which);
                onHeading(null);
              }}
              type="button"
            >
              {which === 'letter' ? 'A–Z' : '五十音'}
            </button>
          ))}
        </div>
      </div>
      <nav aria-label="Jump to a heading" className="rb-headings mb-3">
        <button
          className={`btn btn-sm btn-outline-secondary${heading === null ? ' active' : ''}`}
          onClick={() => onHeading(null)}
          type="button"
        >
          All
        </button>
        {headings.map((one) => (
          <button
            className={`btn btn-sm btn-outline-secondary${heading === one ? ' active' : ''}`}
            key={one}
            onClick={() => onHeading(one)}
            type="button"
          >
            {one}
          </button>
        ))}
      </nav>
      <p className="small text-body-secondary" id="rb-found">
        {found} of {index.tunes.length} tunes
      </p>
      {shown.map((one) => (
        <section key={one.heading}>
          <h2 className="h5 rb-heading">{one.heading}</h2>
          <ul className="list-unstyled rb-tunes">
            {one.tunes.map((tune) => (
              <li key={tune.id}>
                <button
                  className="btn btn-link text-start text-decoration-none w-100 p-2 rb-tune"
                  data-id={tune.id}
                  onClick={() => onTune(tune)}
                  type="button"
                >
                  <span className="d-block rb-tune-title">{tune.title}</span>
                  <span className="d-block small text-body-secondary">{tune.artist}</span>
                  <span className="small rb-levels">
                    {difficulties(tune).map((name) => (
                      <span className={`rb-level rb-level-${name}`} key={name}>
                        {DIFFICULTY_LABELS[name]} {tune.levels[name] ?? '?'}
                      </span>
                    ))}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
      {!found && <p className="text-body-secondary">Nothing matches.</p>}
    </section>
  );
};
