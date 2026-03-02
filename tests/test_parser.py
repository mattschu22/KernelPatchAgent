"""Tests for kernel_patcher.parser — zero API tokens."""

import pytest

from kernel_patcher.parser import Parser
from tests.conftest import (
    SAMPLE_INPUT_TEXT,
    SAMPLE_MULTI_FILE_INPUT,
    SAMPLE_MULTI_FILE_RESPONSE,
    SAMPLE_RESPONSE_TEXT,
)


@pytest.fixture
def parser():
    return Parser()


# ---------------------------------------------------------------------------
# remove_line_numbers
# ---------------------------------------------------------------------------

class TestRemoveLineNumbers:
    def test_strips_leading_numbers(self, parser):
        text = "1 #include <linux/kernel.h>\n2 int main() {}"
        result = parser.remove_line_numbers(text)
        assert result == "#include <linux/kernel.h>\nint main() {}"

    def test_handles_no_numbers(self, parser):
        text = "#include <linux/kernel.h>"
        result = parser.remove_line_numbers(text)
        assert result == "#include <linux/kernel.h>"

    def test_handles_empty_string(self, parser):
        assert parser.remove_line_numbers("") == ""

    def test_handles_blank_lines(self, parser):
        text = "1 hello\n\n3 world"
        result = parser.remove_line_numbers(text)
        assert "hello" in result
        assert "world" in result


# ---------------------------------------------------------------------------
# parse_input
# ---------------------------------------------------------------------------

class TestParseInput:
    def test_single_file(self, parser):
        result = parser.parse_input(SAMPLE_INPUT_TEXT)
        assert "net/smc/smc_sysctl.c" in result
        content = result["net/smc/smc_sysctl.c"]
        assert "#include <linux/kernel.h>" in content
        assert "smc_sysctl_init" in content

    def test_multi_file(self, parser):
        result = parser.parse_input(SAMPLE_MULTI_FILE_INPUT)
        assert len(result) == 2
        assert "fs/ext4/file.c" in result
        assert "fs/ext4/namei.c" in result
        assert "ext4_func" in result["fs/ext4/file.c"]
        assert "ext4_namei_func" in result["fs/ext4/namei.c"]

    def test_empty_string(self, parser):
        result = parser.parse_input("")
        assert result == {}

    def test_no_markers(self, parser):
        result = parser.parse_input("just some random text")
        assert result == {}

    def test_preserves_code_structure(self, parser):
        result = parser.parse_input(SAMPLE_INPUT_TEXT)
        content = result["net/smc/smc_sysctl.c"]
        assert "return 0;" in content


# ---------------------------------------------------------------------------
# parse_response
# ---------------------------------------------------------------------------

class TestParseResponse:
    def test_single_file(self, parser):
        result = parser.parse_response(SAMPLE_RESPONSE_TEXT)
        assert "net/smc/smc_sysctl.c" in result
        content = result["net/smc/smc_sysctl.c"]
        assert "#include <linux/kernel.h>" in content
        assert "int ret = 0;" in content

    def test_multi_file(self, parser):
        result = parser.parse_response(SAMPLE_MULTI_FILE_RESPONSE)
        assert len(result) == 2
        assert "fs/ext4/file.c" in result
        assert "fs/ext4/namei.c" in result

    def test_empty_string(self, parser):
        result = parser.parse_response("")
        assert result == {}

    def test_no_markers(self, parser):
        result = parser.parse_response("just some random text")
        assert result == {}

    def test_malformed_missing_close_tag(self, parser):
        text = '<file path="foo.c">\nint x;\n'
        result = parser.parse_response(text)
        assert result == {}


# ---------------------------------------------------------------------------
# Round-trip: parse_input -> patch -> parse_response
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_filenames_match(self, parser):
        original = parser.parse_input(SAMPLE_INPUT_TEXT)
        patched = parser.parse_response(SAMPLE_RESPONSE_TEXT)
        assert set(original.keys()) == set(patched.keys())

    def test_multi_file_filenames_match(self, parser):
        original = parser.parse_input(SAMPLE_MULTI_FILE_INPUT)
        patched = parser.parse_response(SAMPLE_MULTI_FILE_RESPONSE)
        assert set(original.keys()) == set(patched.keys())
