"""Tests for :py:mod:`destin.misc.sc_info`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import plistlib
import struct

from destin.misc.sc_info import (
    find_atom,
    iter_atoms,
    parse_atoms,
    parse_sinf,
    parse_supf,
    parse_supp,
    parse_supx,
    read_sc_info,
    render_text,
    sc_info_to_json,
)
import pytest

from .conftest import (
    SC_INFO_ACCOUNT_ID,
    SC_INFO_ACCOUNT_NAME,
    SC_INFO_IDENTIFIER,
    SC_INFO_IV,
    SC_INFO_PURCHASED,
    SUPP_RECORD_COUNT,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_parse_atoms_nests() -> None:
    inner = struct.pack('>I4s', 12, b'user') + b'\0\0\0\1'
    outer = struct.pack('>I4s', 8 + len(inner), b'schi') + inner
    atoms = parse_atoms(outer)
    assert [atom.kind for atom in atoms] == ['schi']
    assert [atom.kind for atom in atoms[0].children] == ['user']
    assert atoms[0].children[0].offset == 8


def test_parse_atoms_stops_at_rubbish() -> None:
    good = struct.pack('>I4s', 12, b'frma') + b'game'
    assert [atom.kind for atom in parse_atoms(good + b'\xff' * 16)] == ['frma']


def test_parse_atoms_stops_at_an_oversized_size() -> None:
    assert parse_atoms(struct.pack('>I4s', 9999, b'frma') + b'game') == ()


def test_parse_atoms_on_an_empty_buffer() -> None:
    assert parse_atoms(b'') == ()


def test_sinf_fields(sinf_bytes: bytes) -> None:
    sinf = parse_sinf(sinf_bytes)
    assert sinf.original_format == 'game'
    assert sinf.scheme == 'itun'
    assert sinf.account_id == SC_INFO_ACCOUNT_ID
    assert sinf.account_name == SC_INFO_ACCOUNT_NAME
    assert sinf.asset_type == 0
    assert sinf.key_index == 6
    assert sinf.initialisation_vector == SC_INFO_IV
    assert sinf.private is not None
    assert len(sinf.private) == 512
    assert sinf.signature is not None
    assert len(sinf.signature) == 128


def test_sinf_purchase_time_uses_the_quicktime_epoch(sinf_bytes: bytes) -> None:
    purchased = parse_sinf(sinf_bytes).purchased
    assert purchased is not None
    # Only the 1904 epoch puts this value in the plausible past.
    assert purchased.isoformat() == '2024-02-04T21:11:50+00:00'


def test_sinf_rights(sinf_bytes: bytes) -> None:
    rights = {right.tag: right for right in parse_sinf(sinf_bytes).rights}
    assert set(rights) == {'veID', 'plat', 'aver', 'tran', 'song', 'tool', 'mode'}
    assert rights['plat'].value == 5
    assert rights['aver'].rendered == '1.1.1.0'
    assert rights['tool'].rendered == "'P609'"
    assert rights['tran'].rendered == '2024-02-04T21:11:49+00:00'
    assert rights['song'].rendered == '472140433'
    assert rights['veID'].description is None
    assert rights['plat'].description == 'Platform'


def test_sinf_rights_trailer_is_reported_not_parsed(sinf_bytes: bytes) -> None:
    # The eight bytes are identical across real bundles, so they are surfaced rather than named.
    assert parse_sinf(sinf_bytes).rights_trailer.hex() == '8a34795bffffffee'


def test_sinf_rejects_a_file_with_no_atoms() -> None:
    with pytest.raises(ValueError, match='Not a sinf'):
        parse_sinf(b'\xff' * 32)


def test_find_atom_and_iter_atoms(sinf_bytes: bytes) -> None:
    atoms = parse_sinf(sinf_bytes).atoms
    assert find_atom(atoms, 'key ') is not None
    assert find_atom(atoms, 'nope') is None
    kinds = [atom.kind for atom in iter_atoms(atoms)]
    assert kinds[:4] == ['sinf', 'frma', 'schm', 'schi']
    assert 'priv' in kinds


def test_supf(supf_bytes: bytes, ec_certificate_der: bytes) -> None:
    supf = parse_supf(supf_bytes)
    assert supf.version == 3
    assert supf.tag == '507'
    assert supf.header_words == (1, 64, 0x0100000C, 0)
    assert supf.identifier == SC_INFO_IDENTIFIER
    assert supf.key_blob == bytes(range(32))
    assert supf.certificate_der == ec_certificate_der
    assert supf.certificate is not None
    assert 'CN=Example EC Leaf' in supf.certificate.subject
    assert supf.signature == bytes(range(128))
    assert supf.trailer == b''


def test_supf_rejects_a_body_length_past_the_end() -> None:
    with pytest.raises(ValueError, match='runs past the end of a supf'):
        parse_supf(b'\x03507' + struct.pack('>I', 9999) + bytes(72) + bytes(4))


def test_supf_rejects_a_short_file() -> None:
    with pytest.raises(ValueError, match='Too short for a supf'):
        parse_supf(b'\x03507')


def test_supp(supp_bytes: bytes, rsa_certificate_der: bytes) -> None:
    supp = parse_supp(supp_bytes)
    assert supp.version == 1
    assert supp.tag == '507'
    assert supp.identifier == SC_INFO_IDENTIFIER
    assert len(supp.records) == SUPP_RECORD_COUNT
    assert supp.records[1] == bytes([1]) * 32
    assert supp.certificate_der == rsa_certificate_der
    assert supp.certificate is not None
    # The .supp carries a different certificate from the .supf, as the real bundles do.
    assert 'CN=Example RSA Leaf' in supp.certificate.subject
    assert supp.signature == bytes(128)


def test_supp_rejects_a_record_count_past_the_end() -> None:
    with pytest.raises(ValueError, match='run past the end of a supp'):
        parse_supp(b'\x01507' + SC_INFO_IDENTIFIER + struct.pack('>I', 9999))


def test_supp_without_a_certificate() -> None:
    supp = parse_supp(b'\x01507' + SC_INFO_IDENTIFIER + struct.pack('>I', 0))
    assert supp.records == ()
    assert supp.certificate is None
    assert supp.signature == b''


def test_supp_rejects_a_short_file() -> None:
    with pytest.raises(ValueError, match='Too short for a supp'):
        parse_supp(b'\x01507')


def test_supx(supx_bytes: bytes) -> None:
    supx = parse_supx(supx_bytes)
    assert supx.version == 1
    assert [entry.tag for entry in supx.entries] == [1, 2]
    assert supx.entries[0].value == bytes(range(16))
    assert supx.trailer == b'\xcc' * 8


def test_supx_rejects_a_short_file() -> None:
    with pytest.raises(ValueError, match='Too short for a supx'):
        parse_supx(b'\x00\x00')


def test_read_sc_info_searches_for_the_directory(sc_info_dir: Path) -> None:
    # sc_info_dir is the Payload directory, so the bundle below it has to be found.
    info = read_sc_info(sc_info_dir)
    assert info.path.name == 'SC_Info'
    assert info.sinf is not None
    assert info.supf is not None
    assert info.supp is not None
    assert info.supx is not None
    assert [name for name, _, _ in info.files] == [
        'Example.sinf', 'Example.supf', 'Example.supp', 'Example.supx', 'Manifest.plist'
    ]
    assert info.manifest is not None
    assert info.manifest['SinfPaths'] == ['SC_Info/Example.sinf']


def test_read_sc_info_accepts_the_directory_itself(sc_info_dir: Path) -> None:
    direct = sc_info_dir / 'Example.app' / 'SC_Info'
    assert read_sc_info(direct).path == direct


def test_read_sc_info_accepts_the_bundle(sc_info_dir: Path) -> None:
    assert read_sc_info(sc_info_dir / 'Example.app').path.name == 'SC_Info'


def test_read_sc_info_on_an_empty_directory(tmp_path: Path) -> None:
    (tmp_path / 'SC_Info').mkdir()
    info = read_sc_info(tmp_path)
    assert info.files == ()
    assert info.sinf is None
    assert info.manifest is None


def test_read_sc_info_survives_an_unreadable_file(tmp_path: Path) -> None:
    directory = tmp_path / 'SC_Info'
    directory.mkdir()
    (directory / 'Broken.sinf').write_bytes(b'\xff' * 32)
    info = read_sc_info(tmp_path)
    assert info.sinf is None
    assert len(info.files) == 1


def test_read_sc_info_without_a_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='No SC_Info directory'):
        read_sc_info(tmp_path)


def test_render_text(sc_info_dir: Path) -> None:
    report = render_text(read_sc_info(sc_info_dir))
    assert 'Purchase record (.sinf)' in report
    assert SC_INFO_ACCOUNT_NAME in report
    assert '2024-02-04T21:11:50+00:00' in report
    assert "'P609'" in report
    assert 'CN=Example EC Leaf' in report
    assert report.endswith('\n')


def test_render_text_indents_nested_atoms(sc_info_dir: Path) -> None:
    report = render_text(read_sc_info(sc_info_dir))
    assert "      'schi' at 0x0028" in report
    assert "        'user' at 0x0030" in report


def test_sc_info_to_json(sc_info_dir: Path) -> None:
    rendered = sc_info_to_json(read_sc_info(sc_info_dir))
    assert rendered['sinf']['accountName'] == SC_INFO_ACCOUNT_NAME
    assert rendered['sinf']['purchased'] == '2024-02-04T21:11:50+00:00'
    assert rendered['sinf']['initialisationVector'] == SC_INFO_IV.hex()
    assert rendered['sinf']['rightsTrailer'] == '8a34795bffffffee'
    assert rendered['supf']['identifier'] == SC_INFO_IDENTIFIER.hex()
    assert rendered['supf']['headerWords'] == [1, 64, 0x0100000C, 0]
    assert len(rendered['supp']['records']) == SUPP_RECORD_COUNT
    assert rendered['supp']['records'][1] == (bytes([1]) * 32).hex()
    assert [entry['tag'] for entry in rendered['supx']['entries']] == [1, 2]
    assert rendered['sinf']['atoms'][0]['children'][2]['children'][0]['type'] == 'user'


def test_sc_info_to_json_keeps_blobs_in_full(sc_info_dir: Path) -> None:
    rendered = sc_info_to_json(read_sc_info(sc_info_dir))
    private = rendered['sinf']['private']
    assert private['length'] == 512
    assert private['blocks'] == 32
    assert len(private['ciphertext']) == 512 * 2
    assert len(rendered['sinf']['signature']) == 128 * 2


def test_purchase_time_covers_the_whole_uint32_range(sinf_bytes: bytes) -> None:
    # The largest value the field can hold is still a date datetime represents, so no timestamp
    # these records carry can overflow.
    latest = sinf_bytes.replace(struct.pack('>I', SC_INFO_PURCHASED), b'\xff\xff\xff\xff', 1)
    purchased = parse_sinf(latest).purchased
    assert purchased is not None
    assert purchased.year == 2040


def test_purchase_time_is_absent_without_the_atom(sinf_bytes: bytes) -> None:
    assert parse_sinf(sinf_bytes.replace(b'crdt', b'zzzz', 1)).purchased is None


def test_cross_references_hold_for_a_matched_pair(tmp_path: Path, sinf_bytes: bytes,
                                                  supf_bytes: bytes, supp_bytes: bytes) -> None:
    directory = tmp_path / 'SC_Info'
    directory.mkdir()
    # Rebuild the .supp so its last record is the .supf key blob, as a real pair has it.
    key_blob = parse_supf(supf_bytes).key_blob
    records = b''.join(bytes([index]) * 32 for index in range(2)) + key_blob
    certificate = parse_supp(supp_bytes).certificate_der
    assert certificate is not None
    paired = (b'\x01507' + parse_supf(supf_bytes).identifier + struct.pack('>I', 3) + records +
              struct.pack('>I', len(certificate)) + certificate + bytes(128))
    (directory / 'Example.sinf').write_bytes(sinf_bytes)
    (directory / 'Example.supf').write_bytes(supf_bytes)
    (directory / 'Example.supp').write_bytes(paired)
    rendered = sc_info_to_json(read_sc_info(tmp_path))
    assert rendered['crossReferences'] == {'identifiersMatch': True, 'keyBlobIsLastRecord': True}
    assert '.supf key blob is the last .supp record  yes' in render_text(read_sc_info(tmp_path))


def test_cross_references_report_a_mismatch(sc_info_dir: Path) -> None:
    # The stock fixtures deliberately do not pair up, so both checks must come back false.
    rendered = sc_info_to_json(read_sc_info(sc_info_dir))
    assert rendered['crossReferences']['keyBlobIsLastRecord'] is False


def test_cross_references_absent_without_both_supplements(tmp_path: Path,
                                                          sinf_bytes: bytes) -> None:
    directory = tmp_path / 'SC_Info'
    directory.mkdir()
    (directory / 'Example.sinf').write_bytes(sinf_bytes)
    rendered = sc_info_to_json(read_sc_info(tmp_path))
    assert rendered['crossReferences'] == {}
    assert 'Cross-references' not in render_text(read_sc_info(tmp_path))


def test_store_item_id_comes_from_the_song_tag(sc_info_dir: Path) -> None:
    info = read_sc_info(sc_info_dir)
    # The sample record's song tag is 0x1c244a91.
    assert info.store_item_id == 472140433
    assert 'Store item ID: 472140433' in render_text(info)
    assert sc_info_to_json(info)['storeItemId'] == 472140433


def test_no_app_store_url_without_a_region(sc_info_dir: Path) -> None:
    # A store item is region-scoped, so there is no valid region-less link to give.
    info = read_sc_info(sc_info_dir)
    assert info.app_store_url is None
    assert sc_info_to_json(info)['appStoreURL'] is None
    assert 'App Store URL: unknown' in render_text(info)


def test_no_store_item_id_without_the_tag(tmp_path: Path, sinf_bytes: bytes) -> None:
    directory = tmp_path / 'SC_Info'
    directory.mkdir()
    (directory / 'Example.sinf').write_bytes(sinf_bytes.replace(b'song', b'zzzz', 1))
    info = read_sc_info(tmp_path)
    assert info.store_item_id is None
    assert info.app_store_url is None
    assert 'Store item ID' not in render_text(info)
    assert sc_info_to_json(info)['storeItemId'] is None


def test_app_store_url_is_absent_without_a_record(tmp_path: Path) -> None:
    (tmp_path / 'SC_Info').mkdir()
    assert read_sc_info(tmp_path).app_store_url is None
    assert read_sc_info(tmp_path).store_item_id is None


def _write_bundle(root: Path, sinf_bytes: bytes, *, metadata: dict[str, object] | None) -> None:
    """Lay out an unpacked .ipa: metadata beside Payload, and one bundle inside it."""
    directory = root / 'Payload' / 'Example.app' / 'SC_Info'
    directory.mkdir(parents=True)
    (directory / 'Example.sinf').write_bytes(sinf_bytes)
    if metadata is not None:
        (root / 'iTunesMetadata.plist').write_bytes(plistlib.dumps(metadata))


@pytest.mark.parametrize('depth', ['root', 'payload', 'bundle', 'sc_info'])
def test_locate_accepts_every_level(tmp_path: Path, sinf_bytes: bytes, depth: str) -> None:
    _write_bundle(tmp_path, sinf_bytes, metadata=None)
    start = {
        'root': tmp_path,
        'payload': tmp_path / 'Payload',
        'bundle': tmp_path / 'Payload' / 'Example.app',
        'sc_info': tmp_path / 'Payload' / 'Example.app' / 'SC_Info',
    }[depth]
    assert read_sc_info(start).path == tmp_path / 'Payload' / 'Example.app' / 'SC_Info'


def test_locate_rejects_two_bundles(tmp_path: Path, sinf_bytes: bytes) -> None:
    _write_bundle(tmp_path, sinf_bytes, metadata=None)
    (tmp_path / 'Payload' / 'Other.app' / 'SC_Info').mkdir(parents=True)
    with pytest.raises(ValueError, match='holds 2 bundles, not one'):
        read_sc_info(tmp_path)


def test_locate_rejects_an_empty_payload(tmp_path: Path) -> None:
    (tmp_path / 'Payload').mkdir()
    with pytest.raises(ValueError, match=r'No \.app bundle'):
        read_sc_info(tmp_path)


def test_locate_rejects_a_bundle_without_sc_info(tmp_path: Path) -> None:
    (tmp_path / 'Payload' / 'Example.app').mkdir(parents=True)
    with pytest.raises(ValueError, match='No SC_Info directory in'):
        read_sc_info(tmp_path)


def test_storefront_gives_the_region_and_a_regional_url(tmp_path: Path, sinf_bytes: bytes) -> None:
    _write_bundle(tmp_path, sinf_bytes, metadata={'s': 143462, 'itemId': 472140433})
    info = read_sc_info(tmp_path)
    assert info.storefront == 143462
    assert info.region == 'jp'
    assert info.app_store_url == 'https://apps.apple.com/jp/app/id472140433'
    assert 'Storefront: 143462 (jp)' in render_text(info)


def test_storefront_falls_back_to_the_cohort_string(tmp_path: Path, sinf_bytes: bytes) -> None:
    _write_bundle(tmp_path, sinf_bytes, metadata={'storeCohort': '3|date=1388822400000&sf=143441'})
    info = read_sc_info(tmp_path)
    assert info.storefront == 143441
    assert info.region == 'us'


def test_an_unlisted_storefront_gives_no_url(tmp_path: Path, sinf_bytes: bytes) -> None:
    _write_bundle(tmp_path, sinf_bytes, metadata={'s': 999999})
    info = read_sc_info(tmp_path)
    assert info.storefront == 999999
    # The storefront is known but not one that maps to a country code, so there is no link.
    assert info.region is None
    assert info.app_store_url is None
    assert 'Storefront: 999999 (unknown region)' in render_text(info)


def test_the_record_wins_over_mismatched_metadata(tmp_path: Path, sinf_bytes: bytes) -> None:
    _write_bundle(tmp_path, sinf_bytes, metadata={'s': 143462, 'itemId': 626574779})
    info = read_sc_info(tmp_path)
    # The record sits inside the bundle, so it is the one bound to it.
    assert info.record_item_id == 472140433
    assert info.metadata_item_id == 626574779
    assert info.store_item_id == 472140433
    assert sc_info_to_json(info)['crossReferences']['metadataItemIdMatchesRecord'] is False


def test_unreadable_metadata_is_ignored(tmp_path: Path, sinf_bytes: bytes) -> None:
    _write_bundle(tmp_path, sinf_bytes, metadata=None)
    (tmp_path / 'iTunesMetadata.plist').write_bytes(b'not a plist')
    info = read_sc_info(tmp_path)
    assert info.metadata is None
    assert info.storefront is None


def test_a_supplied_region_builds_the_url(sc_info_dir: Path) -> None:
    info = read_sc_info(sc_info_dir, 'jp')
    assert info.region == 'jp'
    assert info.app_store_url == 'https://apps.apple.com/jp/app/id472140433'
    assert sc_info_to_json(info)['appStoreURL'] == 'https://apps.apple.com/jp/app/id472140433'


def test_a_supplied_region_wins_over_the_storefront(tmp_path: Path, sinf_bytes: bytes) -> None:
    _write_bundle(tmp_path, sinf_bytes, metadata={'s': 143441})
    assert read_sc_info(tmp_path).region == 'us'
    # Only the caller can know when the metadata beside a bundle is not the bundle's own.
    assert read_sc_info(tmp_path, 'jp').region == 'jp'


def test_atom_json_breaks_down_rights(sc_info_dir: Path) -> None:
    atoms = sc_info_to_json(read_sc_info(sc_info_dir))['sinf']['atoms']
    righ = next(a for a in atoms[0]['children'][2]['children'] if a['type'] == 'righ')
    assert 'body' not in righ
    assert [right['tag'] for right in righ['rights']][:3] == ['veID', 'plat', 'aver']
    assert righ['rights'][1]['description'] == 'Platform'
    assert righ['trailer'] == '8a34795bffffffee'


def test_atom_json_breaks_down_the_scheme(sc_info_dir: Path) -> None:
    atoms = sc_info_to_json(read_sc_info(sc_info_dir))['sinf']['atoms']
    schm = next(a for a in atoms[0]['children'] if a['type'] == 'schm')
    assert schm == {
        'type': 'schm',
        'description': 'Scheme',
        'version': 0,
        'schemeType': 'itun',
        'schemeVersion': 0,
    }


def test_atom_json_gives_the_iv_as_integers(sc_info_dir: Path) -> None:
    atoms = sc_info_to_json(read_sc_info(sc_info_dir))['sinf']['atoms']
    iviv = next(a for a in atoms[0]['children'][2]['children'] if a['type'] == 'iviv')
    assert iviv['bytes'] == list(SC_INFO_IV)
    assert 'body' not in iviv


def test_atom_json_omits_layout_for_decoded_leaves(sc_info_dir: Path) -> None:
    atoms = sc_info_to_json(read_sc_info(sc_info_dir))['sinf']['atoms']
    user = next(a for a in atoms[0]['children'][2]['children'] if a['type'] == 'user')
    # Once the value is decoded the raw bytes and the layout would only repeat it.
    assert user == {'type': 'user', 'description': 'Apple account ID', 'uint32': SC_INFO_ACCOUNT_ID}


def test_atom_json_keeps_the_bytes_where_nothing_is_decoded(sc_info_dir: Path) -> None:
    atoms = sc_info_to_json(read_sc_info(sc_info_dir))['sinf']['atoms']
    priv = next(a for a in atoms[0]['children'][2]['children'] if a['type'] == 'priv')
    assert priv['bodySize'] == 512
    assert len(priv['body']) == 512 * 2
