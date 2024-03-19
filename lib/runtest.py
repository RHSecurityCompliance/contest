import os
import sys
import re
import runpy
import signal
import traceback
import tempfile
import urllib3
from pathlib import Path

from lib import util, results


# handle test duration on our own, don't rely on TMT -
# this is because when TMT triggers a timeout, we fall into one of two cases:
#   1) "best" case - error that test didn't provide results.yaml (yet);
#      note that this error result has no output.txt, so you can't actually see
#      what the test timed out on
#   2) worst case - test reported some PASS results before timing out, and TMT
#      takes this as all possible results and silently PASSes the test as if
#      nothing happened
#
# this is not a problem for Beaker, which captures test output separately and
# actually cares about the exit code of the test script
def _setup_timeout_handling():
    metadata_yaml = os.environ['TMT_TEST_METADATA']  # exception if undefined
    test_metadata = Path(metadata_yaml).read_text()
    duration_match = re.search('\nduration: ?([0-9]+)([a-z]+)\n', test_metadata)
    if duration_match:
        length, unit = duration_match.groups()
        if unit == 'm':
            duration = int(length)*60
        elif unit == 'h':
            duration = int(length)*60*60
        elif unit == 'd':
            duration = int(length)*60*60*24
        else:
            duration = int(length)
    else:
        # use TMT's default of 5m
        duration = 300

    # leave 10 seconds for our alarm timeout code
    duration -= 10

    def _alarm_timed_out(signum, frame):
        # sys.exit does run all cleanups (context manager, atexit, etc.),
        # but do not rely on them finishing within 10 seconds - instead,
        # emit the error result now + let TMT kill the test if cleanups
        # take too long
        # - the sys.exit() here also skips the exception catch-all in
        #   the wider runtest.py body because SystemExit is not a subclass
        #   of Exception
        results.report_and_exit('error', note="timed out: test exceeded duration time")

    signal.signal(signal.SIGALRM, _alarm_timed_out)
    signal.alarm(duration)


if util.running_in_tmt():
    _setup_timeout_handling()

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
