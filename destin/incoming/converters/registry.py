"""The ordered list of conversion rules."""
from __future__ import annotations

from ._base import Rule, name_match, suffix_match
from .audio import raw_to_wav
from .data import bin_to_json, ctl_to_json
from .images import ppm_to_png, pvr_pack_to_png, spvr2png_converter
from .models import ian_to_obj
from .models_dc import mbin_to_obj, mlbin_to_json
from .sound_dc import mlt_to_json, osb_to_wav
from .state import cfg_to_json, lev_to_json, sav_to_json, xxx_to_json
from .text import txt_to_utf8

__all__ = ('RULES',)

RULES: tuple[Rule, ...] = (
    Rule('pvr-pack', name_match('_t.pvr'), pvr_pack_to_png),
    Rule('pvr', suffix_match('.pvr'), spvr2png_converter),
    Rule('ppm', suffix_match('.ppm'), ppm_to_png),
    Rule('ian', suffix_match('.ian'), ian_to_obj),
    Rule('raw-cdda', suffix_match('.raw'), raw_to_wav),
    Rule('dc-model-index', name_match('_ml.bin'), mlbin_to_json),
    Rule('dc-model', name_match('_m.bin'), mbin_to_obj),
    Rule('terrain-bin', suffix_match('.bin'), bin_to_json),
    Rule('ctl', suffix_match('.ctl'), ctl_to_json),
    Rule('save', suffix_match('.sav'), sav_to_json),
    Rule('level-snapshot', suffix_match('.lev'), lev_to_json),
    Rule('debug-snapshot', suffix_match('.xxx'), xxx_to_json),
    Rule('config', suffix_match('.cfg'), cfg_to_json),
    Rule('osb', suffix_match('.osb'), osb_to_wav),
    Rule('mlt', suffix_match('.mlt'), mlt_to_json),
    Rule('txt', suffix_match('.txt'), txt_to_utf8),
)
"""Conversion rules in priority order; the first matching rule handles a file."""
