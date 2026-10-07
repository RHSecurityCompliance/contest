r"""
This allows raw blocks like

    def func():
        variable = dedent(fr'''
            some
            content
        ''')

without the leading or trailing newlines and any common leading whitespaces.
You might think using '''\ would eliminate the first newline, but the string
is 'raw', it doesn't have escapes.

textwrap.dedent() does only the common leading whitespaces.
"""

import textwrap


def dedent(text):
    """
    Like textwrap.dedent(), but also strip leading and trailing spaces/newlines
    up to the content.
    """
    return textwrap.dedent(text.lstrip("\n").rstrip(" \n"))
