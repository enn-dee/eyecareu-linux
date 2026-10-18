"""Direct DDC/CI backend speaking the MCCS protocol over /dev/i2c-*.

This backend has no external dependency: it drives the DDC/CI "host to
display" packet format over the Linux ``i2c-dev`` interface, which is the same
electrical path ``ddcutil`` uses.

Packet format (VESA DDC/CI 1.1):

    host  -> display : 0x51, 0x80|len, data..., checksum
    display -> host  : 0x6E, 0x80|len, data..., checksum

    Get VCP Feature request : data = 01 <vcp>
        reply data = 02 <result> <vcp> <type> <max_hi> <max_lo> <cur_hi> <cur_lo>
    Set VCP Feature request : data = 03 <vcp> <value_hi> <value_lo>

Requires the ``i2c-dev`` kernel module and read/write access to the ``/dev/i2c-N``
node (usually via the ``i2c`` / ``video`` group, see the shipped udev rule).

Reading is the awkward part.  The adapter keeps the reply in a small (~32 byte)
circular buffer: the frame rarely starts at offset 0, may wrap around the end,
and is interleaved with replayed bytes from earlier requests.  A reply is
therefore read window by window and located by scanning every rotation for a
frame whose checksum verifies and whose contents match the request.
"""

from __future__ import annotations

import errno
import fcntl
import os
import time

from .base import DdcBackend, DdcError, MonitorIdentity, VcpValue

I2C_SLAVE = 0x0703
DDC_ADDRESS = 0x37            # 7-bit DDC/CI address
DDC_SOURCE_HOST = 0x51
DDC_SOURCE_DISPLAY = 0x6E

# Delays required by the DDC/CI specification.
_T_WRITE_READ_S = 0.045
_T_RETRY_S = 0.050
_DEFAULT_RETRIES = 6
#: Size of a single DDC read.  The common ``i2c-dev`` adapters (amdgpu's
#: ``AMDGPU DM`` buses in particular) hand back the reply through a ~32 byte
#: circular buffer, so asking for more just repeats the same window.
_READ_WINDOW = 32
#: How long to scan one reply before re-issuing the request.  A display often
#: answers the *next* request when the previous reply is still queued, so the
#: caller retries rather than waiting on one very long window.  Measured to be
#: the sweet spot: a longer window wastes time on the stale frames replaying
#: from the adapter, a shorter one spends its budget waiting for a reply that
#: is still on the wire.
_REPLY_TIMEOUT_S = 0.18
#: Many displays send no reply at all to a "Set VCP Feature"; wait only briefly.
_SET_REPLY_TIMEOUT_S = 0.20
#: A reply that only appears at least this long after a request is the panel's
#: answer; anything available sooner is the adapter replaying an older transfer.
_FRESH_AFTER_S = 0.35
#: How long to keep looking for a newer frame when one was already buffered.
#: This class of panel can need well over a second to answer after a write, so
#: the window has to be generous — but a *changed* value returns the moment it
#: appears, so the full window is only ever paid when nothing changed.
_RESYNC_HOLD_S = 1.50
#: Budget for an acknowledged write (hold window plus margin for the wire).
_ACK_TIMEOUT_S = _RESYNC_HOLD_S + _FRESH_AFTER_S


def _checksum(packet: bytes) -> int:
    value = 0
    for byte in packet:
        value ^= byte
    return value


class I2cDdcBackend(DdcBackend):
    """DDC/CI transport implemented with raw ``i2c-dev`` ioctls."""

    name = "i2c"

    def __init__(self, retries: int = _DEFAULT_RETRIES) -> None:
        self._retries = retries

    # -- low level ---------------------------------------------------------
    @staticmethod
    def _device_node(bus: int) -> str:
        return f"/dev/i2c-{bus}"

    @staticmethod
    def available() -> bool:
        for entry in os.listdir("/dev"):
            if entry.startswith("i2c-"):
                return True
        return False

    def _write_packet(self, fd: int, data: bytes) -> None:
        length = len(data)
        if not 0 < length <= 127:
            raise DdcError(f"invalid DDC payload length {length}")
        packet = bytes([DDC_SOURCE_HOST, 0x80 | length]) + data
        packet += bytes([_checksum(packet)])
        os.write(fd, packet)
        time.sleep(_T_WRITE_READ_S)

    def _drain_input(self, fd: int) -> None:
        """Consume whatever earlier traffic is still queued in the adapter."""
        try:
            os.set_blocking(fd, False)
        except OSError:
            return                       # not a real i2c fd (e.g. in tests)
        try:
            for _ in range(8):
                try:
                    if len(os.read(fd, _READ_WINDOW)) < 3:
                        break
                except (BlockingIOError, OSError):
                    break
        finally:
            try:
                os.set_blocking(fd, True)
            except OSError:
                pass

    @staticmethod
    def _scan_frame(window: bytes, expect_data: int, validator=None) -> bytes | None:
        """Return the first valid DDC reply frame inside *window*.

        The adapter stores the reply in a small circular buffer, so the frame
        can begin at any offset and one that crosses the end wraps around to
        the front.  Every rotation of the window is therefore tried.  A frame
        whose checksum does not verify is only used as a last resort, so a
        mangled frame can never shadow a good one.
        """
        doubled = window + window
        fallback: bytes | None = None
        for start in range(len(window)):
            if doubled[start] != DDC_SOURCE_DISPLAY:
                continue
            length = doubled[start + 1] & 0x7F
            if not length or length < expect_data:
                continue
            end = start + 2 + length          # index of the checksum byte
            if end >= len(doubled):
                continue                      # frame is longer than the buffer
            frame = doubled[start:end + 1]
            data = frame[2:-1]
            if validator is not None and not validator(data):
                continue
            # DDC/CI replies from a display checksum to 0x50 (a plain XOR is
            # accepted too, for panels that follow the other convention).
            if _checksum(frame) in (0x50, 0x00):
                return data
            if fallback is None:
                fallback = data
        return fallback

    def _read_reply(self, fd: int, expect_data: int, validator=None,
                    timeout: float = _REPLY_TIMEOUT_S,
                    hold: float = 0.0) -> bytes:
        """Return the DDC reply frame that answers the current request.

        A single ``read()`` cannot be used, because the reply arrives through
        a circular buffer that

        * usually does not start at the frame boundary (and wraps), and
        * keeps replaying the previous transfer until the panel has answered
          the current request.

        Windows are therefore read one at a time and scanned for a frame that
        passes *validator* (which pins the VCP code or the capability offset,
        so a frame for another request is never accepted).

        *hold* additionally defeats the replay.  A frame that only appears at
        least :data:`_FRESH_AFTER_S` after the request was written is the
        panel's answer and is returned immediately.  One that is available
        straight away is a leftover, so a newer frame with a different value
        supersedes it; if none turns up within *hold* the leftover is returned
        anyway (the value simply did not change).  Reads that do not care about
        a specific value — a capability chunk, whose offset *validator* already
        pins — leave *hold* at zero and stay fast.
        """
        started = time.monotonic()
        if hold:
            timeout = max(timeout, hold + _FRESH_AFTER_S)
        deadline = started + timeout
        best: bytes | None = None
        release_at = 0.0
        try:
            os.set_blocking(fd, False)
        except OSError as exc:
            raise DdcError(f"i2c read failed: {exc}") from exc
        try:
            while True:
                try:
                    raw = os.read(fd, _READ_WINDOW)
                except BlockingIOError:
                    raw = b""
                except OSError as exc:
                    raise DdcError(f"i2c read failed: {exc}") from exc
                now = time.monotonic()
                if len(raw) >= 3:
                    data = self._scan_frame(raw, expect_data, validator)
                    if data is not None:
                        if best is None:
                            best = data
                            if not hold or now - started >= _FRESH_AFTER_S:
                                return data
                            release_at = now + hold
                        elif data != best:
                            return data            # a newer answer wins
                        elif now >= release_at:
                            return best
                if now >= deadline:
                    if best is not None:
                        return best
                    raise DdcError("no valid DDC reply")
                time.sleep(0.004)
        finally:
            try:
                os.set_blocking(fd, True)
            except OSError:
                pass

    def _transact(self, bus: int, data: bytes, expect_data: int,
                  validator=None, timeout: float = _REPLY_TIMEOUT_S,
                  hold: float = 0.0, attempts: int | None = None) -> bytes:
        node = self._device_node(bus)
        last_error: Exception | None = None
        for attempt in range(attempts or self._retries):
            fd = -1
            try:
                fd = self._open_bus(bus)
                # Clear frames left over from earlier traffic *before* writing,
                # so the reply we read belongs to this request.
                self._drain_input(fd)
                self._write_packet(fd, data)
                # Displays occasionally emit a stale frame (e.g. leftover
                # capability bytes) *after* a request; _read_reply skips those
                # rather than returning a plausible-looking wrong value.
                return self._read_reply(fd, expect_data, validator, timeout,
                                        hold)
            except OSError as exc:
                last_error = exc
                if exc.errno in (errno.EBUSY, errno.EIO, errno.EAGAIN):
                    time.sleep(_T_RETRY_S)
                    continue
                if exc.errno == errno.EACCES:
                    raise DdcError(
                        f"no permission to open {node}; add your user to the "
                        "'i2c' group (see packaging/99-eyecareu-i2c.rules)"
                    ) from exc
                raise DdcError(f"i2c error on {node}: {exc}") from exc
            except DdcError as exc:
                last_error = exc
                time.sleep(_T_RETRY_S)
            finally:
                if fd >= 0:
                    os.close(fd)
        raise DdcError(f"DDC transaction failed after {self._retries} attempts: {last_error}")

    def _open_bus(self, bus: int) -> int:
        fd = os.open(self._device_node(bus), os.O_RDWR)
        try:
            fcntl.ioctl(fd, I2C_SLAVE, DDC_ADDRESS)
        except OSError:
            os.close(fd)
            raise
        return fd

    # -- DdcBackend --------------------------------------------------------
    def get_vcp(self, monitor: MonitorIdentity, vcp: int) -> VcpValue:
        """Read *vcp* quickly, taking the first matching frame."""
        return self._get_vcp(monitor, vcp, hold=0.0)

    def get_vcp_settled(self, monitor: MonitorIdentity, vcp: int) -> VcpValue:
        """Read *vcp*, holding back a frame the adapter is replaying."""
        return self._get_vcp(monitor, vcp, hold=_RESYNC_HOLD_S)

    def _get_vcp(self, monitor: MonitorIdentity, vcp: int,
                 hold: float) -> VcpValue:
        if monitor.i2c_bus is None:
            return VcpValue(vcp=vcp, error="no i2c bus for display")
        try:
            data = self._transact(
                monitor.i2c_bus, bytes([0x01, vcp]), expect_data=8,
                validator=lambda r: len(r) >= 3 and r[0] == 0x02 and r[2] == vcp,
                hold=hold, attempts=2 if hold else None,
            )
        except DdcError as exc:
            return VcpValue(vcp=vcp, error=str(exc))
        result = data[1]
        if result != 0x00:
            return VcpValue(vcp=vcp, error=f"result 0x{result:02X}")
        maximum = (data[4] << 8) | data[5]
        current = (data[6] << 8) | data[7]
        return VcpValue(vcp=vcp, current=current, maximum=maximum,
                        vcp_type=data[3], supported=True)

    def set_vcp(self, monitor: MonitorIdentity, vcp: int, value: int) -> bool:
        if monitor.i2c_bus is None:
            return False
        value &= 0xFFFF
        payload = bytes([0x03, vcp, (value >> 8) & 0xFF, value & 0xFF])
        node = self._device_node(monitor.i2c_bus)
        last_error: Exception | None = None
        for _ in range(self._retries):
            fd = -1
            try:
                fd = self._open_bus(monitor.i2c_bus)
                self._drain_input(fd)
                self._write_packet(fd, payload)
                # Many displays do not acknowledge a "Set VCP Feature" at all
                # (the bus simply returns silence), so a missing reply is not an
                # error.  When a reply *is* sent it must confirm result code 0x00.
                try:
                    data = self._read_reply(
                        fd, expect_data=3,
                        validator=lambda r: (len(r) >= 3 and r[0] == 0x02
                                             and r[2] == vcp),
                        timeout=_SET_REPLY_TIMEOUT_S)
                except DdcError:
                    return True      # silent bus: assume the write was taken
                # The acknowledgement mirrors a "Get VCP Feature" reply, so a
                # non-zero result byte is an explicit refusal.
                return data[1] == 0x00
            except OSError as exc:
                last_error = exc
                if exc.errno == errno.EACCES:
                    raise DdcError(
                        f"no permission to open {node}; add your user to the "
                        "'i2c' group (see packaging/99-eyecareu-i2c.rules)"
                    ) from exc
                if exc.errno in (errno.EBUSY, errno.EIO, errno.EAGAIN):
                    time.sleep(_T_RETRY_S)
                    continue
                raise DdcError(f"i2c error on {node}: {exc}") from exc
            finally:
                if fd >= 0:
                    os.close(fd)
        if isinstance(last_error, DdcError):
            raise last_error
        return False

    def set_vcp_ack(self, monitor: MonitorIdentity, vcp: int,
                    value: int) -> int | None:
        """Set *vcp*, returning the value the panel reports (or ``None``).

        The acknowledgement of a "Set VCP Feature" has the same layout as a
        "Get VCP Feature" reply, so the trailing value is the mode the panel
        actually applied.  A BenQ panel answers with result 0x00 even for a
        mode it does not support — but echoes back the mode it fell back to,
        which is what makes a clamped write detectable.
        """
        if monitor.i2c_bus is None:
            raise DdcError("no i2c bus for display")
        value &= 0xFFFF
        payload = bytes([0x03, vcp, (value >> 8) & 0xFF, value & 0xFF])
        try:
            data = self._transact(
                monitor.i2c_bus, payload, expect_data=8,
                validator=lambda r: (len(r) >= 3 and r[0] == 0x02
                                     and r[2] == vcp),
                timeout=_ACK_TIMEOUT_S, hold=_RESYNC_HOLD_S, attempts=2,
            )
        except DdcError:
            return None                  # silent display: no acknowledgement
        if data[1] != 0x00:
            raise DdcError(f"display refused VCP 0x{vcp:02X} = 0x{value:04X}")
        return (data[6] << 8) | data[7]

    def get_capabilities(self, monitor: MonitorIdentity) -> str:
        if monitor.i2c_bus is None:
            return ""
        chunks: list[str] = []
        offset = 0
        stalls = 0
        # Reply payload layout: 0xE3 <offset_hi> <offset_lo> <ascii...>.
        # There is *no* separate length byte — the display returns the bytes
        # starting at the requested offset, and the host advances by however
        # many it received.  (Assuming a length byte here truncated the string
        # at the first chunk, which hid VCP 0xDC / picture-mode support.)
        while offset < 0x10000 and stalls < 3:
            reply = None
            for _ in range(3):        # the DDC bus drops chunks occasionally
                try:
                    reply = self._transact(
                        monitor.i2c_bus,
                        bytes([0xF3, (offset >> 8) & 0xFF, offset & 0xFF]),
                        expect_data=4,
                        # The display sometimes still has the *previous* chunk
                        # queued when we ask for the next one; a stale frame is
                        # also a valid 0xE3 reply, so the requested offset must
                        # match or the string would gain duplicated bytes.
                        validator=lambda r, off=offset: (
                            len(r) >= 3 and r[0] == 0xE3
                            and ((r[1] << 8) | r[2]) == off),
                    )
                    break
                except DdcError:
                    reply = None
                    time.sleep(_T_RETRY_S)
            if not reply:
                stalls += 1
                continue
            body = reply[3:]
            if not body:
                stalls += 1
                continue
            chunks.append(body.decode("ascii", "ignore"))
            offset += len(body)
            stalls = 0
        return "".join(chunks)
