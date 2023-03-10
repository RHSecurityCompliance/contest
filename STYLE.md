Philosophy:

Don't hide control flow, let the user see what's happening

All state is tracked by the test, not by supporting modules (libraries),
modules either
* provide state-less functions
* context manager based classes

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

---

Use `#!/usr/bin/python3` as shebang.

If this binary is not available, install the appropriate packages (should be
done by top-level FMF/TMT configuration).

Do not use `#!/usr/libexec/platform-python`, which is not available outside
of RHEL and may have unknown python version.

---

Check your code with `pycodestyle-3`, which has been configured via `setup.cfg`.

---

Keep line length to under 80, but don't be pedantic about it. If a line looks
better without a break, leave it longer.  
Don't exceed 100 characters on a line unless there's a good reason for it
(waive that reason via `# nopep8` or `# noqa` to avoid codestyle warning).

Try to always keep docstrings under 80, don't make them unnecessarily wider.

---

Prefer modern Python features over older (but still valid) ones, namely:

* f-strings over `.format()` and `%`
 * unless required by a module, ie. `logging` needs `%(blabla)s`
* pathlib over `os.path.*`
 * unless you wouldn't use any path splitting/joining, in which case just
   use `os.path.*`, ie. to get a basename string from a path string
* `subprocess.run()` over `.check_output()` and `.call()`

However avoid using these new features:

* explicit data types like `varname: int = 5`
 * incl. function parameters and return type

---

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

---

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

Unless you need to repeat it many times, then it's probably okay.

```
from pathlib import Path

x = Path(...)
y = Path(...)

z = some_func(x, y, Path(...))
```

---

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

---

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

---

Misc:

* prefer operators over methods
 * ie. `list += another_list` instead of `list.extend(another_list)`
 * but **do** use methods where appropriate
  * ie. `list.append(item)` instead of forcing `list += [item]`

---

Obsoletes/replaces when we drop support for Python 3.6:

* `subprocess.run()` - replace `universal_newlines` with `text`
