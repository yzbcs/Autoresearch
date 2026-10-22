"""Linux Landlock write boundary for model-authored builder subprocesses.
ABI 1 blocks ordinary file writes/removal/creation outside allowed directories.
It does not cover the later ABI's separate truncate right; this is not a full
hostile-code sandbox. No capabilities or server configuration are changed.
"""
import ctypes
import os
from pathlib import Path


def restrict_writes(directories):
    libc = ctypes.CDLL(None, use_errno=True)
    abi = libc.syscall(444, 0, 0, 1)
    if abi < 1:
        raise RuntimeError('FigureCrafter requires Linux Landlock write confinement on this server')
    # WRITE_FILE, REMOVE_DIR/FILE, MAKE_*; ABI 1 rights, plus TRUNCATE if available.
    mask = (1 << 1) | sum(1 << i for i in range(4, 13))
    if abi >= 3:
        mask |= 1 << 14
    class Attr(ctypes.Structure):
        _fields_ = [('handled_access_fs', ctypes.c_uint64)]
    class Rule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [('allowed_access', ctypes.c_uint64), ('parent_fd', ctypes.c_int)]
    attr = Attr(mask)
    fd = libc.syscall(444, ctypes.byref(attr), ctypes.sizeof(attr), 0)
    if fd < 0:
        raise OSError(ctypes.get_errno(), 'Landlock ruleset creation failed')
    try:
        for folder in directories:
            p = Path(folder).resolve()
            p.mkdir(parents=True, exist_ok=True)
            parent = os.open(p, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = Rule(mask, parent)
                if libc.syscall(445, fd, 1, ctypes.byref(rule), 0):
                    raise OSError(ctypes.get_errno(), 'Landlock path rule failed')
            finally:
                os.close(parent)
        # /dev/null is a non-persistent output sink required by LibreOffice shell helpers.
        parent = os.open('/dev/null', os.O_PATH | os.O_CLOEXEC)
        try:
            rule = Rule(1 << 1, parent)
            if libc.syscall(445, fd, 1, ctypes.byref(rule), 0):
                raise OSError(ctypes.get_errno(), 'Landlock null-device rule failed')
        finally:
            os.close(parent)
        if libc.prctl(38, 1, 0, 0, 0) or libc.syscall(446, fd, 0):
            raise OSError(ctypes.get_errno(), 'Landlock restriction failed')
    finally:
        os.close(fd)
    return {'landlock_abi': abi, 'write_roots': [str(Path(p).resolve()) for p in directories],
            'limitation': 'ABI 1 lacks separate truncate mediation' if abi < 3 else None}
