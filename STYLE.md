## Code style check

Check your code with `flake8`, which has been configured via `setup.cfg`.

## Line length

Keep line length to under 80, but don't be pedantic about it. If a line looks
better without a break, leave it longer.  
Don't exceed 100 characters on a line unless there's a good reason for it
(waive that reason via `# noqa` to avoid codestyle warning).

Try to always keep docstrings under 80, don't make them unnecessarily wider.

## Control flow

Don't hide control flow, let the user see what's happening

All state is tracked by the test, not by supporting modules (libraries),
modules either
- provide state-less functions
- context manager based classes

In the first case, it's up to the test to clean up:

```
import atexit

variant = 'foo'
atexit.register(cleanup_something, variant)
x = setup_something(variant)
do(x)
```

The `setup_something` function itself must not touch `atexit`.

In the second, python takes care of it:

```
variant = 'foo'
with Something(variant) as x:
    do(x)
```

## Shebang

Use `#!/usr/bin/python3` as shebang in python scripts.

If this binary is not available, install the appropriate packages
(should be done by TMT via test requirements).

Do not use `#!/usr/libexec/platform-python`, which is not available outside
of RHEL and may have unknown python version.

## Python features

Prefer modern Python features over older (but still valid) ones, namely:

- f-strings over `.format()` and `%`
  - unless required by a module, ie. `logging` needs `%(blabla)s`
- `pathlib.Path` over `os.path.*`
  - `Path('some/path') / subdir / another_dir`
  - `Path().name` instead of `os.path.basename()`
  - `Path().parent` instead of `os.path.dirname()`
  - see others on https://docs.python.org/3.6/library/pathlib.html#methods
- `subprocess.run()` over `.check_output()` and `.call()`

However avoid using these new features:

- explicit data types like `varname: int = 5`
  - incl. function parameters and return type

## Quotes

Use single `''` for identifier-like strings (array key, argparse parameter name,
etc.).  
Use double `""` for human-facing sentences (several words with spaces, etc.).

```
'-a', '--argument'
x = ['first', 'second', ...]
f'{key}={value}'
f"To get {value}, request {key} from the DB"
Exception("you went too fast, try going slower")
```

This applies to multi-line strings too, use `'''` for data-based formats,
and `"""` for human-readable texts and docstrings.

## Import namespaces

Generally avoid importing objects from modules into the current namespace,
prefer referencing them via their import names.

```
import os
import subprocess
import pathlib
import textwrap

...

subprocess.run(...)
x = pathlib.Path(...)
y = textwrap.dedent("""\
        foo
          bar""")
```

However a unique enough identifier that is repeated several/many times
can be imported directly into the current namespace:

```
from pathlib import Path

x = Path(...)
y = Path(...)

z = some_func(x, y, Path(...))
```

```
from concurrent.futures import ThreadPoolExecutor

e = ThreadPoolExecutor(...)
```

Avoid overriding python keywords with imported identifiers, ie. avoid

```
from os import open

open(...)  # overrides built-in open()
```

## Import order

Try to keep the most commonly used modules at the top of the import list,
for consistency across tests. Put less common ones lower down.

```
import os
import sys
...
import inspect
```

Additionally, put any more complex import statements **after** the simple
`import` lines.

```
import os
import sys
import inspect
import xml.etree.ElementTree as ET
from pathlib import Path
```

Finally, put imports of custom libraries after all the imports from standard
ones, separated by an empty line.

```
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import results
import virt
from util import AutoCleanup
```

## None comparisons

Don't be pedantic about `None` checking. If a function argument doesn't make
sense when empty, include that logic into the check. It makes for a more
readable code that serves two purposes - to check for non-`None` and to check
that the argument is sane.

```
def func(arg=None):
    # prefer this
    if arg:
        ...

    # over this
    if arg is not None:
        ...
```

## Prefer operators over methods

Use expressions like `some_list += another_list` instead of
`some_list.extend(another_list)`.

However **do** use methods where an operator doesn't exist, don't try to come up
with workarounds that would use operators.

Use `some_list.append(item)` instead of `some_list += [item]`.

## Close blocks on the same indent level

Use the alternate (C-style) blocks allowed by PEP8, same for function calls
if the argument list is too long.
```
my_list = [
    1,
    2,
]
ret = func_call(
    some_long_arg="probably useless long text that should be in a variable",
    another_arg=123,
)
```

If a multiline dict/str/other constant is specified as a single argument,
combine the opening `(` and closing `)` of the function call with the opening
and closing of the constant.
```
ret = func_call({
    'x': 123,
    'y': 234,
})
```
However do not use this syntax if you would pass extra arguments to `func_call`
after the dict.

## Use comma on the last line

In list/dict/etc. and even function definitions and calls spread across multiple
lines, always use `,` on the last line, even if it's technically unnecessary.
```
my_list = [
    1,
    2,
]
```
This ensures easy editing of the contents without somebody forgetting to add `,`
to an existing line, and simplifies git diffs as they won't display the `,`
addition on the unchanged line.

(This applies to all modern-ish languages, incl. C89.)

## Avoid getters/setters

Prefer the pythonic approach of accessing class variables directly, even from
the outside, if possible. Do not create `get()` / `set()` that just read/write
the variable value.

```
obj = Class()
obj.amount = 10
obj.harvest()
```

However if the `get()` / `set()` would provide additional value (ie. formatting)
feel free to use them (under some appropriate name).

Avoid (for now) using `@property` to hack this, we don't have public APIs.

## Log tactically

Use `util.log('something')` when something

- will take a long time with no output
- will perform notable changes to an OS
- is a significant workflow step

Use the `util.subprocess_run(...)` function (instead of `subprocess.run(...)`)
when you want the execution to be automatically logged.  
For insignificant or harmless (read-only) commands, use `subprocess.run(...)`
to not flood the logs.

## TODOs

Obsoletes/replaces when we drop support for Python 3.6:

- `subprocess.run()` - replace `universal_newlines` with `text`

Misc:

- maybe move all python stuff to `lib/python/` and leave `lib/` for other things too ?
  - runconf
  - waiveconf
  - pseudotty and other executables
  - ...
  - adjust `libdir` in `util` appropriately ?
