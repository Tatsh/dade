from __future__ import annotations

import pytest

from dade.itgps2.simfile import beat_at_music_start, resolve_conflicts, rewrite_simfile

_CONFLICTED = """#TITLE:A;
<<<<<<< A.sm
#BGCHANGES:-10000.000=_movie=1.000=0=0=1,
99999=-nosongbg-=1.000=0=0=0;
=======
#BGCHANGES:0.000=A-bg.png=1.000=0=0=1;
>>>>>>> 1.18
#NOTES:
0000
"""


def test_resolve_conflicts_retains_the_first_side() -> None:
    assert resolve_conflicts(_CONFLICTED) == """#TITLE:A;
#BGCHANGES:-10000.000=_movie=1.000=0=0=1,
99999=-nosongbg-=1.000=0=0=0;
#NOTES:
0000
"""


@pytest.mark.parametrize(('offset', 'bpms', 'stops', 'expected'), [
    (0.5, [(0.0, 120.0)], [], 1.0),
    (-0.5, [(0.0, 120.0)], [], -1.0),
    (2.0, [(0.0, 120.0), (2.0, 60.0)], [], 3.0),
    (1.5, [(0.0, 120.0)], [(2.0, 1.0)], 2.0),
    (2.0, [(0.0, 120.0)], [(2.0, 0.5)], 3.0),
    (0.5, [(-4.0, 60.0), (8.0, 240.0)], [], 0.5),
])
def test_beat_at_music_start(offset: float, bpms: list[tuple[float, float]],
                             stops: list[tuple[float, float]], expected: float) -> None:
    assert beat_at_music_start(offset, bpms, stops) == pytest.approx(expected)


def test_rewrite_simfile_points_at_the_written_files() -> None:
    text = rewrite_simfile('#MUSIC:A b.av;\n#OFFSET:0.500;\n#BPMS:0.000=120.000;\n#STOPS:;\n' +
                           _CONFLICTED)
    assert '#MUSIC:A b.wav;' in text
    assert '#BGCHANGES:1.000=A b.mpg=1.000=0=0=1,' in text
    assert '<<<<<<<' not in text


def test_rewrite_simfile_without_tempo_starts_the_movie_at_nought() -> None:
    assert '#BGCHANGES:0.000=A.mpg=' in rewrite_simfile('#MUSIC:A.AV;\n' + _CONFLICTED)


def test_rewrite_simfile_retains_other_music() -> None:
    text = '#MUSIC:A.ogg;\n#BGCHANGES:-10000.000=_movie=1.000=0=0=1;\n'
    assert rewrite_simfile(text) == text


def test_rewrite_simfile_plays_a_stream_of_the_same_stem() -> None:
    text = '#MUSIC:A b.ogg;\n#BGCHANGES:0.000=songbackground=1.000=0=0=1;\n'
    assert rewrite_simfile(
        text, {'a b': False}) == ('#MUSIC:A b.wav;\n#BGCHANGES:0.000=songbackground=1.000=0=0=1;\n')


def test_rewrite_simfile_plays_the_movie_of_a_stream_with_video() -> None:
    text = ('#MUSIC:A b.ogg;\n#OFFSET:0.500;\n#BPMS:0.000=120.000;\n'
            '#BGCHANGES:-10000.000=songbackground=1.000=0=0=1,\n16.000=EV01447N.mpg=1.000=0=0=1;\n'
            '#BGCHANGES2:16.000=white flash=1.000=0=0=1;\n')
    assert rewrite_simfile(
        text,
        {'a b': True}) == ('#MUSIC:A b.wav;\n#OFFSET:0.500;\n#BPMS:0.000=120.000;\n'
                           '#BGCHANGES:1.000=A b.mpg=1.000=0=0=1,\n99999=-nosongbg-=1.000=0=0=0;\n'
                           '#BGCHANGES2:16.000=white flash=1.000=0=0=1;\n')
