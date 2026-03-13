"""Parse model input/output formats for kernel patch files."""

from __future__ import annotations

import re


class Parser:
    """Parses the input/output formats used by the kernel patching pipeline.

    Input format (kBench data):
        [start of path/to/file.c]
        path/to/file.c
        1 #include <linux/foo.h>
        2 ...
        [end of path/to/file.c]

    Output format (model response):
        <file path="path/to/file.c">
        #include <linux/foo.h>
        ...
        </file>
    """

    def remove_line_numbers(self, content: str) -> str:
        """Strip leading line-number prefixes from each line."""
        lines = content.split("\n")
        for idx, line in enumerate(lines):
            match = re.match(r"^\d+", line)
            if match:
                lines[idx] = line.replace(match.group(), "", 1)[1:]
        return "\n".join(lines)

    def parse_input(self, text: str) -> dict[str, str]:
        """Parse kBench input format into {filename: content} dict.

        Format:
            [start of FILE]
            FILE
            1 line1
            2 line2
            [end of FILE]
        """
        ret: dict[str, str] = {}
        while text:
            start_marker = "[start of "
            start_idx = text.find(start_marker)
            if start_idx == -1:
                break

            filename_start = start_idx + len(start_marker)
            filename_end = text.find("]\n", filename_start)
            if filename_end == -1:
                break
            filename = text[filename_start:filename_end]

            content_start = filename_end + text[filename_end:].find("\n") + 1
            end_marker = f"\n[end of {filename}]"
            content_end = text.find(end_marker)
            if content_end == -1:
                break

            # Skip the filename line that follows the start marker
            content_start = content_start + text[content_start:].find("\n") + 1

            content = self.remove_line_numbers(text[content_start:content_end])
            ret[filename] = content

            text = text[content_end + len(end_marker) :]

        return ret

    def parse_response(self, text: str) -> dict[str, str]:
        """Parse model response format into {filename: content} dict.

        Format:
            <file path="FILE">
            content
            </file>
        """
        ret: dict[str, str] = {}
        while text:
            start_marker = '<file path="'
            start_idx = text.find(start_marker)
            if start_idx == -1:
                break

            filename_start = start_idx + len(start_marker)
            filename_end = text.find('">\n', filename_start)
            if filename_end == -1:
                break
            filename = text[filename_start:filename_end]

            content_start = filename_end + text[filename_end:].find("\n") + 1
            content_end = text.find("\n</file>")
            if content_end == -1:
                break

            content = self.remove_line_numbers(text[content_start:content_end])
            ret[filename] = content

            text = text[content_end + len("\n</file>") :]

        return ret
