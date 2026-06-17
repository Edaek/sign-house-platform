"""Tests for OCR text cleaning functions."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.ocr_service import _normalize_unicode_punctuation, clean_ocr_text


class TestNormalizeUnicodePunctuation:
    def test_fullwidth_comma(self):
        assert _normalize_unicode_punctuation('\uff0c') == ','

    def test_fullwidth_period(self):
        assert _normalize_unicode_punctuation('\uff0e') == '.'

    def test_fullwidth_parens(self):
        assert _normalize_unicode_punctuation('\uff08hello\uff09') == '(hello)'

    def test_fullwidth_dollar_to_S(self):
        assert _normalize_unicode_punctuation('\uff04') == 'S'

    def test_em_dash_to_hyphen(self):
        assert _normalize_unicode_punctuation('\u2014') == '-'

    def test_smart_quotes(self):
        assert _normalize_unicode_punctuation('\u201chello\u201d') == '"hello"'

    def test_non_breaking_space(self):
        assert _normalize_unicode_punctuation('\u00a0') == ' '

    def test_no_change_for_ascii(self):
        assert _normalize_unicode_punctuation('S1-2x') == 'S1-2x'


class TestCleanOcrText:
    def test_empty_string(self):
        assert clean_ocr_text('') == ''

    def test_none(self):
        assert clean_ocr_text(None) == ''

    def test_dollar_to_S(self):
        assert clean_ocr_text('$1-2') == 'S1-2'

    def test_strip_brackets(self):
        assert clean_ocr_text('[S1-2]') == 'S1-2'

    def test_strip_curly_braces(self):
        assert clean_ocr_text('{S3-4}') == 'S3-4'

    def test_strip_exclamation(self):
        assert clean_ocr_text('!S1-2!') == 'S1-2'

    def test_remove_special_chars(self):
        assert clean_ocr_text('S1@#2') == 'S12'

    def test_keep_hyphen(self):
        assert clean_ocr_text('S1-2') == 'S1-2'

    def test_keep_dot(self):
        assert clean_ocr_text('S1.2') == 'S1.2'

    def test_keep_x(self):
        assert clean_ocr_text('S1-2x') == 'S1-2x'

    def test_unicode_fullwidth_dollar(self):
        assert clean_ocr_text('\uff041-2') == 'S1-2'

    def test_complex_noise(self):
        assert clean_ocr_text('|[S1-2]|') == 'S1-2'

    def test_trailing_noise(self):
        assert clean_ocr_text('S1-2...') == 'S1-2'

    def test_preserves_spaces(self):
        assert clean_ocr_text('S1 2') == 'S1 2'
