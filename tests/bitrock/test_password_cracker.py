from __future__ import annotations

from importlib.util import find_spec
from typing import TYPE_CHECKING
import importlib
import itertools
import signal

import pytest

from dade.bitrock.commands.crack import crack_main
from dade.bitrock.exceptions import BitrockError, NotEncryptedError
from dade.bitrock.password_cracker import Mask, combine, crack, iter_wordlist, mangle

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from click.testing import CliRunner
    from pytest_mock import MockerFixture

_HAS_CUPY = find_spec('cupy') is not None
_HAS_PYOPENCL = find_spec('pyopencl') is not None


@pytest.fixture
def encrypted_installer(tmp_path: Path, build_encrypted_cookfs: Callable[..., bytes]) -> Path:
    path = tmp_path / 'secret.run'
    path.write_bytes(build_encrypted_cookfs({'dir/a.txt': b'alpha'}, b'ab'))
    return path


@pytest.fixture
def plain_installer(tmp_path: Path, build_cookfs: Callable[..., bytes]) -> Path:
    path = tmp_path / 'plain.run'
    path.write_bytes(build_cookfs({'a.txt': b'alpha'}))
    return path


@pytest.mark.parametrize(('mask', 'expected'), [
    (Mask(b'ab', 1, 2), 6),
    (Mask(b'abc', 2, 2), 9),
    (Mask(b'a', 1, 3), 3),
])
def test_mask_count(mask: Mask, expected: int) -> None:
    assert mask.count() == expected
    assert len(list(mask)) == expected


def test_mask_count_handles_huge_keyspace() -> None:
    assert Mask(bytes(range(62)), 1, 16).count() > 2 ** 63


def test_mask_iter_shortest_first() -> None:
    assert list(Mask(b'ab', 1, 2))[:2] == [b'a', b'b']


def test_iter_wordlist(tmp_path: Path) -> None:
    path = tmp_path / 'words.txt'
    path.write_bytes(b'one\r\ntwo\nthree\n')
    assert list(iter_wordlist(path)) == [b'one', b'two', b'three']


def test_crack_cpu_finds_password(encrypted_installer: Path) -> None:
    assert crack(encrypted_installer, Mask(b'ab', 1, 2), backend='cpu') == b'ab'


def test_crack_cpu_wordlist(encrypted_installer: Path) -> None:
    assert crack(encrypted_installer, [b'no', b'ab', b'zz'], backend='cpu') == b'ab'


def test_crack_cpu_str_candidates(encrypted_installer: Path) -> None:
    assert crack(encrypted_installer, ['ab'], backend='cpu') == b'ab'


def test_crack_exhausted_returns_none(encrypted_installer: Path) -> None:
    assert crack(encrypted_installer, [b'no', b'zz'], backend='cpu') is None


def test_crack_not_encrypted(plain_installer: Path) -> None:
    with pytest.raises(NotEncryptedError):
        crack(plain_installer, [b'x'], backend='cpu')


@pytest.mark.skipif(_HAS_CUPY, reason='cupy is installed, so the cuda backend loads')
def test_crack_cuda_unavailable(encrypted_installer: Path) -> None:
    with pytest.raises(BitrockError, match='cupy'):
        crack(encrypted_installer, [b'ab'], backend='cuda')


@pytest.mark.skipif(_HAS_PYOPENCL, reason='pyopencl is installed, so the opencl backend loads')
def test_crack_opencl_unavailable(encrypted_installer: Path) -> None:
    with pytest.raises(BitrockError, match='pyopencl'):
        crack(encrypted_installer, [b'ab'], backend='opencl')


def test_crack_main_found(runner: CliRunner, encrypted_installer: Path) -> None:
    result = runner.invoke(
        crack_main,
        [str(encrypted_installer), '--charset', 'ab', '--max-length', '2', '--backend', 'cpu'])
    assert result.exit_code == 0
    assert result.output.splitlines()[-1] == 'ab'


def test_crack_main_not_found(runner: CliRunner, encrypted_installer: Path) -> None:
    result = runner.invoke(
        crack_main,
        [str(encrypted_installer), '--charset', 'xy', '--max-length', '2', '--backend', 'cpu'])
    assert result.exit_code == 1
    assert 'not found' in result.output


def test_crack_main_wordlist(runner: CliRunner, encrypted_installer: Path, tmp_path: Path) -> None:
    words = tmp_path / 'words.txt'
    words.write_bytes(b'no\nab\n')
    result = runner.invoke(crack_main,
                           [str(encrypted_installer), '--wordlist',
                            str(words), '--backend', 'cpu'])
    assert result.exit_code == 0
    assert result.output.splitlines()[-1] == 'ab'


def test_crack_main_not_encrypted(runner: CliRunner, plain_installer: Path) -> None:
    result = runner.invoke(crack_main, [str(plain_installer), '--backend', 'cpu'])
    assert result.exit_code != 0
    assert 'not password-protected' in result.output


def test_mangle_default_rules() -> None:
    assert list(mangle(['abc'])) == [b'abc', b'Abc', b'ABC']


def test_mangle_dedups_per_word() -> None:
    assert list(mangle(['ABC'], ['upper', 'none'])) == [b'ABC']


def test_mangle_leet() -> None:
    assert list(mangle(['pass'], ['leet'])) == [b'p@55']


def test_mangle_append_digits() -> None:
    assert list(mangle(['a'], ['append_digits'])) == [f'a{n}'.encode() for n in range(10)]


def test_combine_two_words() -> None:
    assert list(combine([b'a', b'b'], 2)) == [b'aa', b'ab', b'ba', b'bb']


def test_combine_separator() -> None:
    assert list(combine([b'a', b'b'], 2, separator=b'-')) == [b'a-a', b'a-b', b'b-a', b'b-b']


def test_combine_with_rules() -> None:
    assert b'RandomGenerated' in set(combine(['random', 'generated'], 2, rules=['capitalize']))


def test_combine_rejects_zero_count() -> None:
    with pytest.raises(ValueError, match='at least 1'):
        list(combine([b'a'], 0))


def test_crack_main_combinator(runner: CliRunner, encrypted_installer: Path,
                               tmp_path: Path) -> None:
    words = tmp_path / 'words.txt'
    words.write_bytes(b'a\nb\n')
    result = runner.invoke(crack_main, [
        str(encrypted_installer), '--wordlist',
        str(words), '--combinator', '2', '--backend', 'cpu'
    ])
    assert result.exit_code == 0
    assert result.output.splitlines()[-1] == 'ab'


def test_crack_main_rule_without_wordlist(runner: CliRunner, encrypted_installer: Path) -> None:
    result = runner.invoke(crack_main, [str(encrypted_installer), '--rule', 'capitalize'])
    assert result.exit_code != 0
    assert 'require --wordlist' in result.output


def test_crack_main_limit_stops_early(runner: CliRunner, encrypted_installer: Path) -> None:
    # The password 'ab' is the last of 6 candidates; a limit of 3 must not reach it.
    result = runner.invoke(crack_main, [
        str(encrypted_installer), '--charset', 'ab', '--max-length', '2', '--limit', '3',
        '--backend', 'cpu'
    ])
    assert result.exit_code == 1
    assert 'Searching 3 candidates.' in result.output
    assert 'not found' in result.output


def test_crack_main_limit_caps_total(runner: CliRunner, encrypted_installer: Path) -> None:
    result = runner.invoke(crack_main, [
        str(encrypted_installer), '--charset', 'ab', '--max-length', '8', '--limit', '5',
        '--backend', 'cpu'
    ])
    assert 'Searching 5 candidates.' in result.output


def test_crack_main_list_devices_lists_names(runner: CliRunner, mocker: MockerFixture) -> None:
    mocker.patch('dade.bitrock.password_cracker.cuda.list_devices', return_value=['GeForce (CUDA)'])
    mocker.patch('dade.bitrock.password_cracker.opencl.list_devices',
                 return_value=['Radeon (rocm)', 'CPU (pocl)'])
    result = runner.invoke(crack_main, ['--list-devices'])
    assert result.exit_code == 0
    assert result.output == ('cuda 0: GeForce (CUDA)\n'
                             'opencl 0: Radeon (rocm)\nopencl 1: CPU (pocl)\n')


def test_crack_main_list_devices_reports_no_devices(runner: CliRunner,
                                                    mocker: MockerFixture) -> None:
    mocker.patch('dade.bitrock.password_cracker.cuda.list_devices', return_value=[])
    mocker.patch('dade.bitrock.password_cracker.opencl.list_devices', return_value=[])
    result = runner.invoke(crack_main, ['--list-devices'])
    assert result.exit_code == 0
    assert result.output == 'cuda: no devices\nopencl: no devices\n'


def test_crack_main_list_devices_reports_unavailable(runner: CliRunner,
                                                     mocker: MockerFixture) -> None:
    mocker.patch('dade.bitrock.password_cracker.cuda.list_devices',
                 side_effect=RuntimeError('no driver'))
    mocker.patch('dade.bitrock.password_cracker.opencl.list_devices',
                 side_effect=RuntimeError('no platform'))
    result = runner.invoke(crack_main, ['--list-devices'])
    assert result.exit_code == 0
    assert result.output == ('cuda: unavailable (no driver)\n'
                             'opencl: unavailable (no platform)\n')


def test_crack_main_rejects_negative_device(runner: CliRunner) -> None:
    result = runner.invoke(crack_main, ['--device', '-1'])
    assert result.exit_code == 2
    assert "Invalid value for '--device'" in result.output


def test_progress_callback_alias_importable() -> None:
    from dade.bitrock.password_cracker import typing as pc_typing
    assert pc_typing.__all__ == ('ProgressCallback',)
    assert vars(pc_typing)['ProgressCallback'] == 'Callable[[int, bytes], None]'


def test_mangle_append_years() -> None:
    result = list(mangle(['a'], ['append_years']))
    assert result[0] == b'a1940'
    assert result[-1] == b'a2030'
    assert len(result) == 2031 - 1940


def test_crack_auto_backend_falls_back_to_cpu(encrypted_installer: Path) -> None:
    assert crack(encrypted_installer, [b'ab'], backend='auto') == b'ab'


def test_crack_cpu_parallel_finds_password(encrypted_installer: Path) -> None:
    assert crack(encrypted_installer, Mask(b'ab', 1, 2), backend='cpu', jobs=2) == b'ab'


def test_crack_cpu_serial_periodic_progress(encrypted_installer: Path,
                                            mocker: MockerFixture) -> None:
    # The package re-exports the ``crack`` function, shadowing the submodule name, so resolve the
    # module object explicitly before patching its clock.
    crack_module = importlib.import_module('dade.bitrock.password_cracker.crack')
    # A clock that jumps 0.2s per read forces the periodic-report branch on every candidate.
    mocker.patch.object(crack_module.time, 'monotonic', side_effect=itertools.count(0.0, 0.2))
    calls: list[tuple[int, bytes]] = []
    result = crack(encrypted_installer, [b'no', b'ab'],
                   backend='cpu',
                   jobs=1,
                   on_progress=lambda tested, latest: calls.append((tested, latest)))
    assert result == b'ab'
    assert calls[-1] == (2, b'ab')


def test_crack_main_wordlist_with_rule(runner: CliRunner, encrypted_installer: Path,
                                       tmp_path: Path) -> None:
    words = tmp_path / 'words.txt'
    words.write_bytes(b'AB\n')
    result = runner.invoke(
        crack_main,
        [str(encrypted_installer), '--wordlist',
         str(words), '--rule', 'lower', '--backend', 'cpu'])
    assert result.exit_code == 0
    assert result.output.splitlines()[-1] == 'ab'


def test_crack_main_reports_large_duration(runner: CliRunner, encrypted_installer: Path,
                                           mocker: MockerFixture) -> None:
    mocker.patch('dade.bitrock.commands.crack.crack', return_value=b'ab')
    mocker.patch('dade.bitrock.commands.crack.time.monotonic', side_effect=[0.0, 0.0, 4e18])
    result = runner.invoke(
        crack_main,
        [str(encrypted_installer), '--charset', 'ab', '--max-length', '2', '--backend', 'cpu'])
    assert result.exit_code == 0
    assert 'Gy' in result.output
    assert 'millennia' in result.output


def test_crack_main_list_devices_via_import(runner: CliRunner, mocker: MockerFixture) -> None:
    module = mocker.MagicMock()
    module.list_devices.return_value = ['Device A', 'Device B']
    mocker.patch('dade.bitrock.commands.crack.import_module', return_value=module)
    result = runner.invoke(crack_main, ['--list-devices'])
    assert result.exit_code == 0
    assert 'cuda 0: Device A' in result.output
    assert 'opencl 1: Device B' in result.output


def test_crack_main_list_devices_no_devices_via_import(runner: CliRunner,
                                                       mocker: MockerFixture) -> None:
    module = mocker.MagicMock()
    module.list_devices.return_value = []
    mocker.patch('dade.bitrock.commands.crack.import_module', return_value=module)
    result = runner.invoke(crack_main, ['--list-devices'])
    assert result.exit_code == 0
    assert result.output == 'cuda: no devices\nopencl: no devices\n'


def test_crack_main_list_devices_unavailable_via_import(runner: CliRunner,
                                                        mocker: MockerFixture) -> None:
    mocker.patch('dade.bitrock.commands.crack.import_module', side_effect=RuntimeError('no driver'))
    result = runner.invoke(crack_main, ['--list-devices'])
    assert result.exit_code == 0
    assert result.output == ('cuda: unavailable (no driver)\n'
                             'opencl: unavailable (no driver)\n')


def test_crack_main_debug_and_quiet_conflict(runner: CliRunner, encrypted_installer: Path) -> None:
    result = runner.invoke(crack_main, [str(encrypted_installer), '--debug', '--quiet'])
    assert result.exit_code != 0
    assert 'mutually exclusive' in result.output


def test_crack_main_progress_updates_display(runner: CliRunner, encrypted_installer: Path,
                                             mocker: MockerFixture) -> None:
    def fake_crack(_installer: object, _source: object, *,
                   on_progress: Callable[[int, bytes], None], **_kwargs: object) -> bytes:
        on_progress(3, b'ab')
        return b'ab'

    mocker.patch('dade.bitrock.commands.crack.crack', side_effect=fake_crack)
    result = runner.invoke(
        crack_main,
        [str(encrypted_installer), '--charset', 'ab', '--max-length', '2', '--backend', 'cpu'])
    assert result.exit_code == 0
    assert '3 tried' in result.output


def test_crack_main_quiet_found_suppresses_output(runner: CliRunner, encrypted_installer: Path,
                                                  mocker: MockerFixture) -> None:
    def fake_crack(_installer: object, _source: object, *,
                   on_progress: Callable[[int, bytes], None], **_kwargs: object) -> bytes:
        on_progress(3, b'ab')
        return b'ab'

    mocker.patch('dade.bitrock.commands.crack.crack', side_effect=fake_crack)
    result = runner.invoke(crack_main, [
        str(encrypted_installer), '--charset', 'ab', '--max-length', '2', '--backend', 'cpu',
        '--quiet'
    ])
    assert result.exit_code == 0
    assert result.output == 'ab\n'


def test_crack_main_quiet_not_found(runner: CliRunner, encrypted_installer: Path,
                                    mocker: MockerFixture) -> None:
    mocker.patch('dade.bitrock.commands.crack.crack', return_value=None)
    result = runner.invoke(crack_main, [
        str(encrypted_installer), '--charset', 'ab', '--max-length', '2', '--backend', 'cpu',
        '--quiet'
    ])
    assert result.exit_code == 1
    assert not result.output


def test_crack_main_keyboard_interrupt_cpu(runner: CliRunner, encrypted_installer: Path,
                                           mocker: MockerFixture) -> None:
    mocker.patch('dade.bitrock.commands.crack.crack', side_effect=KeyboardInterrupt)
    result = runner.invoke(
        crack_main,
        [str(encrypted_installer), '--charset', 'ab', '--max-length', '2', '--backend', 'cpu'])
    assert result.exit_code == 128 + signal.SIGINT
    assert 'Interrupted.' in result.output


def test_crack_main_keyboard_interrupt_gpu(runner: CliRunner, encrypted_installer: Path,
                                           mocker: MockerFixture) -> None:
    mocker.patch('dade.bitrock.commands.crack.crack', side_effect=KeyboardInterrupt)
    exit_mock = mocker.patch('dade.bitrock.commands.crack.os._exit',
                             side_effect=SystemExit(128 + signal.SIGINT))
    result = runner.invoke(crack_main, [
        str(encrypted_installer), '--charset', 'ab', '--max-length', '2', '--backend', 'cuda',
        '--quiet'
    ])
    assert result.exit_code == 128 + signal.SIGINT
    exit_mock.assert_called_once_with(128 + signal.SIGINT)
