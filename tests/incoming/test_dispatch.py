from __future__ import annotations

from typing import TYPE_CHECKING
import pathlib

from anyio import Path
import pytest

from dade.incoming.dispatch import ConversionSummary, convert_file, run_conversions
from dade.incoming.sources import PreparedSource
from dade.incoming.test_utils import ctl_records, pvr_pack, pvrt_chunk

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_summary_add() -> None:
    assert ConversionSummary(1, 2, 3, 4, 5) + ConversionSummary(1, 1, 1, 1, 1) == ConversionSummary(
        2, 3, 4, 5, 6)


def test_summary_add_not_implemented() -> None:
    with pytest.raises(TypeError):
        _ = ConversionSummary(0, 0, 0, 0, 0) + 5


@pytest.mark.asyncio
async def test_convert_file_no_rule(tmp_path: pathlib.Path) -> None:
    source = tmp_path / 'a.mdl'
    source.write_text('text')
    dest = tmp_path / 'out'
    dest.mkdir()
    summary = await convert_file(Path(source), Path(dest), Path(tmp_path), set())
    assert summary == ConversionSummary(0, 0, 1, 0, 0)
    assert (dest / 'a.mdl').read_text() == 'text'


@pytest.mark.asyncio
async def test_convert_file_converted(tmp_path: pathlib.Path) -> None:
    source = tmp_path / 'p.ctl'
    source.write_bytes(ctl_records(2))
    dest = tmp_path / 'out'
    dest.mkdir()
    summary = await convert_file(Path(source), Path(dest), Path(tmp_path), set())
    assert (summary.converted, summary.produced) == (1, 1)
    assert (dest / 'p.json').is_file()


@pytest.mark.asyncio
async def test_convert_file_skipped_warns_once(tmp_path: pathlib.Path) -> None:
    source = tmp_path / 'x.bin'
    source.write_bytes(bytes(100))
    dest = tmp_path / 'out'
    dest.mkdir()
    warned: set[str] = set()
    first = await convert_file(Path(source), Path(dest), Path(tmp_path), warned)
    assert (first.copied, first.skipped) == (1, 1)
    assert 'terrain-bin' in warned
    assert (dest / 'x.bin').is_file()
    second = await convert_file(Path(source), Path(dest), Path(tmp_path), warned)
    assert second.skipped == 1


@pytest.mark.asyncio
async def test_convert_file_failed(tmp_path: pathlib.Path) -> None:
    source = tmp_path / 'b.ctl'
    source.write_bytes(bytes(20))
    dest = tmp_path / 'out'
    dest.mkdir()
    summary = await convert_file(Path(source), Path(dest), Path(tmp_path), set())
    assert (summary.failed, summary.copied) == (1, 1)


@pytest.mark.asyncio
async def test_convert_file_name_matched_pack(tmp_path: pathlib.Path,
                                              mocker: MockerFixture) -> None:
    source = tmp_path / 'AFRICA_T.PVR'  # matched by the _t.pvr name rule
    source.write_bytes(pvr_pack([pvrt_chunk(2, 2)]))
    mocker.patch('dade.incoming.converters.images.find_spvr2png', return_value=pathlib.Path('/spv'))

    def run(args: list[str], **_: object) -> object:
        raw_dir, dest = pathlib.Path(args[2]), pathlib.Path(args[4])
        for pvr in raw_dir.glob('*.pvr'):
            (dest / f'{pvr.stem}.png').write_bytes(b'PNG')
        return mocker.Mock()

    mocker.patch('dade.incoming.converters.images.sp.run', side_effect=run)
    out = tmp_path / 'out'
    out.mkdir()
    summary = await convert_file(Path(source), Path(out), Path(tmp_path), set())
    assert summary.converted == 1


@pytest.mark.asyncio
async def test_run_conversions(tmp_path: pathlib.Path) -> None:
    root = tmp_path / 'in'
    (root / 'sub').mkdir(parents=True)
    (root / 'a.ctl').write_bytes(ctl_records(2))
    (root / 'sub' / 'b.mdl').write_text('x')
    out = tmp_path / 'out'
    out.mkdir()
    prepared = PreparedSource(root=root, files=())
    summary = await run_conversions(prepared, Path(out), jobs=2)
    assert (out / 'a.json').is_file()
    assert (out / 'sub' / 'b.mdl').read_text() == 'x'
    assert (summary.converted, summary.copied) == (1, 1)


@pytest.mark.asyncio
async def test_run_conversions_loose_files(tmp_path: pathlib.Path) -> None:
    asset = tmp_path / 'p.ctl'
    asset.write_bytes(ctl_records(1))
    out = tmp_path / 'out'
    out.mkdir()
    prepared = PreparedSource(root=None, files=(asset,))
    summary = await run_conversions(prepared, Path(out), jobs=2)
    assert (out / 'p.json').is_file()
    assert summary.converted == 1
