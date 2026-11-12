"""Offline tests only: no real serial connections or motion."""
import struct
import unittest

from mcea_read import crc16
from mcea_home import HOME_PREPARE, HOME_TRIGGER, HomeDevice, preconditions
from mcea_direction_test import Device, bounds, plan, validate


class FakeSerial:
    def __init__(self, exception=False, corrupt=False):
        self.pending = b''
        self.sent = []
        self.exception = exception
        self.corrupt = corrupt

    @property
    def in_waiting(self):
        return len(self.pending)

    def reset_input_buffer(self):
        self.pending = b''

    def write(self, request):
        self.sent.append(request)
        if crc16(request[:-2]) != request[-2:]:
            raise AssertionError('Invalid request CRC')
        body = bytes([request[0], request[1] | 0x80, 2]) if self.exception else request[:6]
        self.pending = body + crc16(body)
        if self.corrupt:
            self.pending = self.pending[:-1] + bytes([self.pending[-1] ^ 1])

    def flush(self):
        pass

    def read(self, count):
        # Return in fragments to exercise partial serial frames.
        count = min(count, 2)
        result, self.pending = self.pending[:count], self.pending[count:]
        return result


def device(cls=Device, **options):
    instance = cls.__new__(cls)
    instance.id = 1
    instance.log = []
    instance.serial = FakeSerial(**options)
    return instance


class ProtocolTests(unittest.TestCase):
    def test_known_crc_vectors(self):
        for text in ('01 03 02 00 00 01 85 B2', '01 03 03 02 00 01 25 8E',
                     '01 03 02 00 01 79 84', '01 03 02 00 00 B8 44'):
            frame = bytes.fromhex(text)
            self.assertEqual(crc16(frame[:-2]), frame[-2:])

    def test_homing_matches_manufacturer_vectors(self):
        port = device(HomeDevice)
        for trigger, expected in ((False, HOME_PREPARE), (True, HOME_TRIGGER)):
            self.assertEqual(crc16(expected[:-2]), expected[-2:])
            port.home_command(trigger)
            self.assertEqual(port.serial.sent[-1], expected)
        self.assertEqual(HOME_PREPARE[-4:-2], b'\x00\x20')
        self.assertEqual(HOME_TRIGGER[-4:-2], b'\x00\x22')

    def test_slow_position_packets_and_pause(self):
        port = device()
        prefix = struct.pack('>BBHHB', 1, 16, 0x1600, 6, 12)
        for control in (0x20, 0x21):
            port.write_ack(prefix + struct.pack('>6H', 3500, 0, 100, 1, 0, control))
        port.pause()
        self.assertEqual(len(port.serial.sent), 3)
        self.assertEqual(port.serial.sent[-1][:-2], bytes.fromhex('01 06 16 05 00 28'))

    def test_unsafe_commands_rejected_before_transmission(self):
        port = device()
        prefix = struct.pack('>BBHHB', 1, 16, 0x1600, 6, 12)
        for fields in ((3500, 0, 10000, 1, 0, 0x21), (3500, 0, 100, 1, 0, 0x8021),
                       (5100, 0, 100, 1, 0, 0x21), (3500, 100, 100, 1, 50, 0x1021)):
            with self.assertRaises(ValueError):
                port.write_ack(prefix + struct.pack('>6H', *fields))
        with self.assertRaises(ValueError):
            port.write_ack(struct.pack('>BBHH', 1, 6, 0x1605, 0x8020))
        self.assertEqual(port.serial.sent, [])

    def test_exception_is_not_retried(self):
        port = device(exception=True)
        with self.assertRaises(RuntimeError):
            port.pause()
        self.assertEqual(len(port.serial.sent), 1)

    def test_bad_crc_is_not_accepted(self):
        port = device(corrupt=True)
        with self.assertRaises(RuntimeError):
            port.pause()
        self.assertEqual(len(port.serial.sent), 1)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.state = dict(id=1, position=2500, homing=1, status=0x4460, alarm=0,
                          control=0x20, io=0, limit=5085, offset=100, home_direction=1)

    def test_centered_route_and_margin(self):
        self.assertEqual(bounds(self.state), (200, 4800))
        self.assertEqual(plan(2500, 200, 4800), [3500, 2500, 1500, 2500])

    def test_endpoints_rejected(self):
        for start in (0, 19, 1199, 3801, 5000):
            with self.assertRaises(RuntimeError):
                plan(start, 200, 4800)

    def test_completed_homing_request_bit_is_accepted(self):
        self.assertEqual(validate(dict(self.state, control=0x22), 1), [])
        self.assertTrue(validate(dict(self.state, control=0x22, homing=0), 1))

    def test_motion_guards(self):
        self.assertEqual(validate(self.state, 1), [])
        for field, value in (('id', 2), ('homing', 0), ('alarm', 1), ('io', 1),
                             ('control', 0x8020), ('control', 0x0220),
                             ('control', 0x28), ('status', 0x4560), ('status', 0x4060)):
            self.assertTrue(validate(dict(self.state, **{field: value}), 1), (field, value))

    def test_homing_guards(self):
        state = dict(self.state, homing=0, status=0x4420)
        self.assertEqual(preconditions(state, 1), [])
        for field, value in (('id', 2), ('home_direction', 0), ('alarm', 1),
                             ('homing', 2), ('status', 0), ('status', 0x4520),
                             ('control', 0x8020), ('io', 1)):
            self.assertTrue(preconditions(dict(state, **{field: value}), 1))


if __name__ == '__main__':
    unittest.main()
