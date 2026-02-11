import os
import sys
import runpy
import traceback
import tempfile
import urllib3
from pathlib import Path

from lib import results

# disable annoying warnings when using requests with verify=False,
# we know we're disabling TLS verification, yes, it's a bad idea in production,
# we don't need to have our logs spammed by good advice
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# get test.py absolute path now, as we're changing CWD below
test_script = Path(sys.argv[1]).absolute()

# RHEL-8 (seemingly all python versions, even ones that are fine on RHEL-9+)
# has broken sys.path handling by runpy, which inserts empty '' into it,
# rather than the directory containing the script
# work around this by doing the insertion ourselves here - at worst, it'll be
# there twice, causing no harm
sys.path.insert(0, str(test_script.parent))

# run inside a temporary directory
# - this is because TMT is happy to run multiple tests inside the same dir,
#   if all the tests are defined in .fmf files inside one directory
# - yes, it means tests now can't access local files directly, but you can
#   import local modules just fine (because python remembers the test.py path,
#   it doesn't rely on CWD) and you can access non-module files via either
#   importlib.resources or (more realistically) by using the current file:
#   Path(inspect.getfile(inspect.currentframe())).parent
with tempfile.TemporaryDirectory() as tmpdir:
    os.chdir(tmpdir)
    try:
        runpy.run_path(str(test_script), run_name='__main__')
    except Exception as e:
        traceback.print_exc()
        results.report_and_exit('error', note=f'{type(e).__name__}: {str(e)}')

# here we rely on the test to report pass/fail for itself, as its control flow
# reached an end successfully - we care only about it ending prematurely due to
# an exception (handled above)
