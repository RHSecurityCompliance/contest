import sys
import logging
import runpy

import results


logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(name)s:%(funcName)s:%(lineno)d: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

#import trace
#tracer = trace.Trace(
#    ignoredirs=[sys.prefix, sys.exec_prefix],
#    trace=1, count=0)

try:
    runpy.run_path(sys.argv[1], run_name='__main__')
    #tracer.runfunc(runpy.run_path, sys.argv[1])
except Exception as e:
    results.report('error', note=f'{type(e).__name__}: {str(e)}')
    raise e from None

# here we rely on the test to report pass/fail for itself, as its control flow
# reached an end successfully - we care only about it ending prematurely due to
# an exception (handled above)
