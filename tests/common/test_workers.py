from __future__ import annotations

from typing import TYPE_CHECKING

from destin.common.workers import default_jobs

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_default_jobs_is_positive() -> None:
    assert default_jobs() >= 1


def test_default_jobs_falls_back_to_one(mocker: MockerFixture) -> None:
    mocker.patch('destin.common.workers.os.cpu_count', return_value=None)
    assert default_jobs() == 1
