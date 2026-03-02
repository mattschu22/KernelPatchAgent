"""Tests for kernel_patcher.diff — zero API tokens."""

import pytest

from kernel_patcher.diff import DiffGenerator


@pytest.fixture
def diff_gen(tmp_dir):
    return DiffGenerator(work_dir=str(tmp_dir))


class TestDiffGenerator:
    def test_simple_diff(self, diff_gen):
        old = {"file.c": "int main() { return 0; }\n"}
        new = {"file.c": "int main() { return 1; }\n"}
        diff = diff_gen.generate(old, new)
        assert "file.c" in diff
        assert "-int main() { return 0; }" in diff
        assert "+int main() { return 1; }" in diff

    def test_identical_files_no_diff(self, diff_gen):
        old = {"file.c": "int x = 1;\n"}
        new = {"file.c": "int x = 1;\n"}
        diff = diff_gen.generate(old, new)
        assert diff.strip() == ""

    def test_new_file(self, diff_gen):
        old = {}
        new = {"new.c": "void f() {}\n"}
        diff = diff_gen.generate(old, new)
        assert "new.c" in diff
        assert "+void f() {}" in diff

    def test_deleted_file(self, diff_gen):
        old = {"gone.c": "void g() {}\n"}
        new = {}
        diff = diff_gen.generate(old, new)
        assert "gone.c" in diff
        assert "-void g() {}" in diff

    def test_multi_file_diff(self, diff_gen):
        old = {
            "a.c": "int a = 1;\n",
            "b.c": "int b = 2;\n",
        }
        new = {
            "a.c": "int a = 10;\n",
            "b.c": "int b = 20;\n",
        }
        diff = diff_gen.generate(old, new)
        assert "a.c" in diff
        assert "b.c" in diff
        assert "+int a = 10;" in diff
        assert "+int b = 20;" in diff

    def test_nested_path(self, diff_gen):
        old = {"net/smc/smc_sysctl.c": "// old\n"}
        new = {"net/smc/smc_sysctl.c": "// new\n"}
        diff = diff_gen.generate(old, new)
        assert "smc_sysctl.c" in diff

    def test_empty_files(self, diff_gen):
        old = {"empty.c": ""}
        new = {"empty.c": ""}
        diff = diff_gen.generate(old, new)
        assert diff.strip() == ""

    def test_skips_empty_filename(self, diff_gen):
        old = {"": "content"}
        new = {"": "content"}
        diff = diff_gen.generate(old, new)
        assert diff == ""
