#!/usr/bin/python3

import os
import sys
import socket
import select
import struct
import logging
import glob
import time
import tarfile
import subprocess
from pathlib import Path


# max length in bytes for various streaming operations
BUFF_SIZE = 8192

#_log = logging.getLogger(__name__).debug


#class ServerError(RuntimeError):
#    pass


class _SimpleFileIO:
    """
    Wrapper for OS file descriptors providing .write() and .read() for tarfile.

    Using os.fdopen() would close the underlying file descriptor, and doing
    os.dup() on it as a workaround is unnecessary overhead and might fail on
    insufficient open file count (RLIMIT).
    """
    def __init__(self, fd):
        self.fd = fd

    def read(self, length):
        return os.read(self.fd, length)

    def write(self, buff):
        return os.write(self.fd, buff)


class _SimpleSocketIO:
    """
    Same idea as _SimpleFileIO, but optimized for sockets.
    """
    def __init__(self, sock):
        self.sock = sock

    def read(self, length):
        buff = bytearray()
        while length > 0:
            recv_len = BUFF_SIZE if length > BUFF_SIZE else length
            part = self.sock.recv(recv_len)
            buff += part
            length -= len(part)
        return buff

    def write(self, buff):
        return self.sock.sendall(buff)


# all 'length'-style fields are 4 bytes of network endianness (big endian)
class _Opcode:
    # request a PONG response
    PING = b'\x01'

    # reply to a PING request
    PONG = b'\x02'

    # execute a command
    # - 4 bytes with length of an _ExecMetadata block
    # - the _ExecMetadata packed block itself
    EXEC = b'\x03'

    # provide a piece of output from the executed command
    # - 4 bytes with length of the output
    # - the output itself, without any termination
    STDOUT = b'\x04'
    STDERR = b'\x05'
    # return code of a finished command
    # - 1 byte with the status code
    RETCODE = b'\x06'

    # retrieve (download) file contents
    # - 4 bytes with length of the file path (glob pattern)
    # - the file path itself, unterminated
    GET = b'\x07'
    # the retrieved file contents
    # - 4 bytes with length of the file contents
    # - the file contents, unterminated
    GETOUT = b'\x08'

    # send (upload) file contents
    # - 4 bytes with length of the destination path (file name)
    # - 4 bytes with length of the file contents
    # - the path itself, unterminated
    # - the file contents, unterminated
    PUT = b'\x09'

    # notify the sender that an unexpected exception happened
    # - 4 bytes with length of the verbose string
    # - the string itself, unterminated
    ERROR = b'\x0a'


class _ExecMetadata:
    """Internal bytes representation of parameters for EXEC opcode."""
    # packed format:
    # - 4 bytes with length of the argument array
    # - 4 bytes with length of the CWD path
    # - 4 bytes with length of the environment array
    # - 1 byte as boolean indicating whether to run in a shell
    # - the argument array, with NUL-separated args, last not terminated
    # - the CWD path, without termination
    # - environment array, with NUL-separated pairs of key/value, ie.
    #   keyX\0valueX\0keyY\0valueY , without termination after last value

    def __init__(self, args=None, cwd=None, env=None, shell=False):
        self.args = args if args else []
        self.cwd = cwd if cwd else ''
        self.env = env if env else {}
        self.shell = shell

    def pack(self):
        args_array = b'\x00'.join(x.encode() for x in self.args)
        cwd_bytes = self.cwd.encode()
        env_flat = (y for x in self.env.items() for y in x)
        env_array = b'\x00'.join(x.encode() for x in env_flat)

        return (struct.pack('!III?', len(args_array), len(cwd_bytes), len(env_array), self.shell)
                + args_array
                + cwd_bytes
                + env_array)

    @classmethod
    def unpack(cls, buff):
        new = cls()
        args_len, cwd_len, env_len, new.shell = struct.unpack_from('!III?', buff)
        off = struct.calcsize('!III?')

        if args_len > 0:
            args_array = buff[off:off+args_len]
            new.args = [x.decode() for x in args_array.split(b'\x00')]
        off += args_len

        new.cwd = buff[off:off+cwd_len].decode()
        off += cwd_len

        if env_len > 0:
            env_array = [x.decode() for x in buff[off:off+env_len].split(b'\x00')]
            new.env = dict(zip(env_array[0::2], env_array[1::2]))

        return new


class Server:
    def __init__(self, client_fd):
        self.log = logging.getLogger(f'{__name__}.{self.__class__.__name__}').debug
        self.sock = _SimpleFileIO(client_fd)

    def handle_request(self):
        action = self.sock.read(1)
        if len(action) == 0:
            return False
        self.log(f"handling opcode {action[0]:#x}")

        if action == _Opcode.PING:
            self.log("sending PONG")
            self.sock.write(_Opcode.PONG)

        elif action == _Opcode.EXEC:
            meta_len = struct.unpack('!I', self.sock.read(4))[0]
            meta_block = self.sock.read(meta_len)
            meta = _ExecMetadata.unpack(meta_block)
            self.log(f"executing {meta.args}")
            self.stream_subprocess(meta)

        elif action == _Opcode.GET:
            path_len = struct.unpack('!I', self.sock.read(4))[0]
            path = self.sock.read(path_len).decode()
            self.log(f"handling GET {path}")
            self.send_file(path)

        elif action == _Opcode.PUT:
            path_len, contents_len = struct.unpack('!II', self.sock.read(8))
            path = self.sock.read(path_len).decode()
            self.log(f"handling PUT {path}")
            self.receive_file(path, contents_len)

        else:
            raise RuntimeError(f"unknown opcode: {action[0]:#x}")

        return True

    def stream_subprocess(self, meta):
        stdout_r = stdout_w = stderr_r = stderr_w = None

        try:
            stdout_r, stdout_w = os.pipe()
            stderr_r, stderr_w = os.pipe()

            cwd = meta.cwd if meta.cwd else None
            env = meta.env if meta.env else None
            proc = subprocess.Popen(
                meta.args, cwd=cwd, env=env, shell=meta.shell,
                stdout=stdout_w, stderr=stderr_w
            )

            while True:
                read_events, _, _ = select.select([stdout_r, stderr_r], [], [], 0.01)
                if read_events:
                    for fileno in read_events:
                        if fileno == stdout_r:
                            opcode = _Opcode.STDOUT
                        else:
                            opcode = _Opcode.STDERR

                        out = os.read(fileno, BUFF_SIZE)

                        packet = opcode + struct.pack('!I', len(out)) + out
                        self.sock.write(packet)
                    continue

                # on timeout, check if the process has ended, handle retcode
                ret = proc.poll()
                if ret is not None:
                    self.log(f"subprocess ended with {ret}")
                    packet = _Opcode.RETCODE + struct.pack('B', ret)
                    self.sock.write(packet)
                    return

        finally:
            for fd in [stdout_r, stdout_w, stderr_r, stderr_w]:
                if fd is not None:
                    os.close(fd)

    def send_file(self, path):
        path = Path(path)
        length = path.stat().st_size
        # open first, to catch errors even before sending a packet
        with open(path, 'rb') as f:
            packet = _Opcode.GETOUT + struct.pack('!I', length)
            self.sock.write(packet)
            while True:
                part = f.read(BUFF_SIZE)
                if len(part) == 0:
                    break
                self.sock.write(part)

    def receive_file(self, path, length):
        with open(path, 'wb') as f:
            while length > 0:
                part_len = BUFF_SIZE if length > BUFF_SIZE else length
                part = self.sock.read(part_len)
                f.write(part)
                length -= len(part)


class Client:
    def __init__(self, path):
        """Connect to a unix sock path provided by libvirt."""
        self.log = logging.getLogger(f'{__name__}.{self.__class__.__name__}').debug
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.connect(path)
        self.conn = _SimpleSocketIO(conn)

    def ping(self):
        self.log("sending PING")
        self.conn.write(_Opcode.PING)
        reply = self.conn.read(1)
        if reply != _Opcode.PONG:
            raise RuntimeError(f"got opcode {reply} instead of PONG")
        self.log("got PONG")

    def exec(self, *cmd, cwd=None, env=None, shell=False, capture=False, text=False):
        self.log(f"running {cmd}")
        meta = _ExecMetadata(cmd, cwd=cwd, env=env, shell=shell).pack()
        packet = _Opcode.EXEC + struct.pack('!I', len(meta)) + meta
        self.conn.write(packet)

        stdout_buff = bytearray()
        stderr_buff = bytearray()

        while True:
            opcode = self.conn.read(1)
            _check_error_opcode(opcode, self.conn)

            if opcode == _Opcode.STDOUT:
                out_len = struct.unpack('!I', self.conn.read(4))[0]
                if capture:
                    stdout_buff += self.conn.read(out_len)
                else:
                    sys.stdout.buffer.write(self.conn.read(out_len))
                    sys.stdout.buffer.flush()

            elif opcode == _Opcode.STDERR:
                err_len = struct.unpack('!I', self.conn.read(4))[0]
                if capture:
                    stderr_buff += self.conn.read(err_len)
                else:
                    sys.stderr.buffer.write(self.conn.read(err_len))
                    sys.stderr.buffer.flush()

            elif opcode == _Opcode.RETCODE:
                return_code = struct.unpack('B', self.conn.read(1))[0]
                break

            else:
                raise RuntimeError(f"unexpected opcode {opcode}")

        self.log(f"returned {return_code}")
        if capture:
            return (return_code, stdout_buff, stderr_buff)
        else:
            return return_code

    def download(self, path, dest_dir='.'):
        self.log(f"downloading {path} to {dest_dir}")
        # open first, to catch local errors even before sending a request
        dest_file = Path(dest_dir) / Path(path).name
        with open(dest_file, 'wb') as f:
            path_bytes = path.encode()
            packet = _Opcode.GET + struct.pack('!I', len(path_bytes)) + path_bytes
            self.conn.write(packet)

            reply = self.conn.read(1)
            _check_error_opcode(reply, self.conn)

            length = struct.unpack('!I', self.conn.read(4))[0]
            while length > 0:
                part_len = BUFF_SIZE if length > BUFF_SIZE else length
                part = self.conn.read(part_len)
                f.write(part)
                length -= len(part)

    def upload(self, path, dest_dir='/root'):
        self.log(f"uploading {path} to {dest_dir}")
        path_bytes = path.encode()
        path = Path(path)
        length = path.stat().st_size
        with open(path, 'rb') as f:
            packet = _Opcode.PUT + struct.pack('!II', len(path_bytes), length) + path_bytes
            self.conn.write(packet)
            while length > 0:
                part_len = BUFF_SIZE if length > BUFF_SIZE else length
                part = f.read(part_len)
                self.conn.write(part)
                length -= len(part)


# TODO: replace with glob.glob(..., root_dir=...) in python3.10
def _relative_glob(pattern, root_dir):
    root = Path(root_dir).resolve()
    matches = []
    for x in glob.glob(str(root / pattern)):
        matches.append(Path(x).relative_to(root))
    return matches


def _send_error_opcode(fobj):
    tb_bytes = traceback.format_exc().rstrip().encode()
    packet = _Opcode.ERROR + struct.pack('!I', len(tb_bytes)) + tb_bytes
    fobj.write(packet)


def _check_error_opcode(opcode, fobj):
    if opcode != _Opcode.ERROR:
        return
    tb_len = struct.unpack('!I', fobj.read(4))[0]
    tb = fobj.read(details_len).decode()
    raise RuntimeError(f"shell failed inside guest:\n{tb}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"usage: {sys.argv[0]} /dev/virtio-ports/something")
        sys.exit(1)

    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s %(name)s:%(funcName)s:%(lineno)d: %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S')

    port = os.open(sys.argv[1], os.O_RDWR)
    server = Server(port)

    # /dev/virtio-ports/* character device files behave like /dev/null when
    # the host unix socket is disconnected - any reads return immediately with
    # 0 bytes read, and select/poll always indicate immediate read events -
    # this means there's no efficient way for us to wait until the host connects
    # (hence the sleep), but that's fine, because as soon as it does (likely
    # even before guest boots), any reads start blocking and we stop eating CPU

    while True:
        try:
            if not server.handle_request():
                time.sleep(0.1)
        except:
            # TODO: actually call _send_error_opcode(), but we probably need to
            #       open the virtio-port as O_NONBLOCK first, otherwise we might
            #       end up blocking/waiting to send ie. KeyboardInterrupt to
            #       a port without any reader, blocking the server
            logging.exception("unexpected error")
            time.sleep(0.1)  # just in case
