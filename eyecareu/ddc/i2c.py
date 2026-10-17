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
_DEFAULT_RETRIES = 3


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

    def _read_reply(self, fd: int, expect_data: int) -> bytes:
        raw = os.read(fd, 128)
        if len(raw) < 3:
            raise DdcError("short DDC reply")
        if raw[0] != DDC_SOURCE_DISPLAY:
            raise DdcError(f"unexpected DDC source 0x{raw[0]:02X}")
        length = raw[1] & 0x7F
        if length == 0:
            raise DdcError("empty DDC reply")
        data = raw[2:2 + length]
        if len(data) < expect_data:
            raise DdcError(f"truncated DDC reply ({len(data)} < {expect_data})")
        return data

    def _transact(self, bus: int, data: bytes, expect_data: int,
                  validator=None) -> bytes:
        node = self._device_node(bus)
        last_error: Exception | None = None
        for attempt in range(self._retries):
            fd = -1
            try:
                fd = self._open_bus(bus)
                self._write_packet(fd, data)
                reply = self._read_reply(fd, expect_data)
                # Displays occasionally emit a stale frame (e.g. leftover
                # capability bytes) *after* a request; reject it and retry
                # rather than returning a plausible-looking wrong value.
                if validator is not None and not validator(reply):
                    raise DdcError("unexpected DDC reply for request")
                return reply
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
        if monitor.i2c_bus is None:
            return VcpValue(vcp=vcp, error="no i2c bus for display")
        try:
            data = self._transact(
                monitor.i2c_bus, bytes([0x01, vcp]), expect_data=8,
                validator=lambda r: len(r) >= 3 and r[0] == 0x02 and r[2] == vcp,
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
                self._write_packet(fd, payload)
                # Many displays do not acknowledge a "Set VCP Feature" at all
                # (the bus simply returns silence), so a missing reply is not an
                # error.  When a reply *is* sent it must confirm result code 0x00.
                try:
                    data = self._read_reply(fd, expect_data=2)
                except DdcError:
                    return True
                if data[0] != 0x02:
                    return True
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
