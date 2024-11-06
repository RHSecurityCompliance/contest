import time
import socket

from lib import util


def wait_for_tcp(host, port, *, timeout=600, to_shutdown=False, compare=None):
    """
    Wait for a TCP server to start responding on a given 'host' and 'port'.

    Optionally, read len(compare) bytes from the socket and compare them to
    the bytestring specified in 'compare'. If they are different, close the
    socket and (re)try again later.
    Useful for waiting for b'SSH-' to start answering on port 22.
    """
    if compare is not None and to_shutdown:
        raise SyntaxError("compare and to_shutdown are mutually exclusive")

    state = 'stop' if to_shutdown else 'start'
    util.log(f"waiting for {host}:{port} to {state} listening for {timeout}s", skip_frames=1)

    # we don't actually do low-level networking here, we let the kernel initiate
    # the TCP connection, which however means using the kernel's backoff
    # algorithm of slowing down TCP SYN after a few timeouts (1sec, 2, 4, 8, 16,
    # etc.) - we can mitigate this by closing the socket and opening a new one,
    # resetting the backoff back to ~1s
    # - note that this is overall timeout, incl. any read(), so any server that
    # responds back needs to send its data (compare=) within this time window
    socket_timeout = 5

    # when the remote end responds with TCP RST (port closed, not blocked on
    # firewall), create_connection() fails instantly, so we also need a sleep
    # for that case
    reset_sleep = 1

    # use reliable monotonic time, not wall clock or timedeltas
    overall_end = time.monotonic() + timeout
    while time.monotonic() < overall_end:
        try:
            with socket.create_connection((host, port), timeout=socket_timeout) as s:
                if compare is not None:
                    data = s.recv(len(compare))
                    if data == compare:
                        return
                    # something else on the port? .. just wait + close
                    time.sleep(reset_sleep)
                elif to_shutdown:
                    # connected, socket still up, sleep + close and try again
                    time.sleep(reset_sleep)
                else:
                    # connection established, we're done
                    return
        except TimeoutError:
            if to_shutdown:
                return
            # don't sleep for extra time, we waited in create_connection() enough
        except OSError:
            if to_shutdown:
                return
            time.sleep(reset_sleep)
    raise TimeoutError(f"waiting for {host}:{port} to {state} timed out")
