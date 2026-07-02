"""Silence noisy ALSA/JACK stderr chatter that pyaudio triggers on device
enumeration (harmless 'Unknown PCM' / 'jack server is not running' lines that
flooded the journal). Additive: no behavioural change to any audio feature."""
import os
import contextlib
from ctypes import CFUNCTYPE, c_char_p, c_int, cdll

_ALSA_HANDLER = None  # keep a reference so the C callback is not GC'd


def install_alsa_silencer():
    """Process-wide: swallow ALSA lib error messages at the C level."""
    global _ALSA_HANDLER
    try:
        proto = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)

        def _noop(filename, line, function, err, fmt):
            return

        _ALSA_HANDLER = proto(_noop)
        cdll.LoadLibrary("libasound.so.2").snd_lib_error_set_handler(_ALSA_HANDLER)
    except Exception:
        pass  # never let logging-hygiene break startup


@contextlib.contextmanager
def quiet():
    """Redirect fd 2 to /dev/null for the block — catches JACK/ALSA C chatter
    that bypasses the ALSA error handler (e.g. jackd connection probes)."""
    devnull = saved = None
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        saved = os.dup(2)
        os.dup2(devnull, 2)
        yield
    finally:
        try:
            if saved is not None:
                os.dup2(saved, 2)
        finally:
            if devnull is not None:
                os.close(devnull)
            if saved is not None:
                os.close(saved)
