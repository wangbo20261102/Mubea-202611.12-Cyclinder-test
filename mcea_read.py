"""MCEA Modbus RTU reader. Only function 03 is implemented; no motion writes."""
import argparse
import json
import struct
import time
from datetime import datetime
from pathlib import Path

import serial


def crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return struct.pack('<H', crc)


class Reader:
    def __init__(self, port, baud, device_id, parity='N', stopbits=1):
        self.id = device_id
        self.log = []
        self.serial = serial.Serial(port=None, baudrate=baud, bytesize=8,
                                    parity=parity, stopbits=stopbits,
                                    timeout=0.03, write_timeout=1)
        self.serial.dtr = False
        self.serial.rts = False
        self.serial.port = port
        self.serial.open()
        time.sleep(0.1)

    def read(self, address, timeout=0.45):
        body = struct.pack('>BBHH', self.id, 3, address, 1)
        request = body + crc16(body)
        self.serial.reset_input_buffer()
        self.serial.write(request)
        self.serial.flush()
        data = bytearray()
        deadline = time.monotonic() + timeout
        record = {'address': f'0x{address:04X}', 'tx': request.hex(' ')}
        while time.monotonic() < deadline:
            data.extend(self.serial.read(self.serial.in_waiting or 1))
            for offset in range(max(0, len(data) - 256), len(data) - 4):
                if data[offset] != self.id:
                    continue
                function = data[offset + 1]
                length = 5 if function == 0x83 else 7
                if function not in (3, 0x83) or offset + length > len(data):
                    continue
                frame = bytes(data[offset:offset + length])
                if crc16(frame[:-2]) != frame[-2:]:
                    continue
                if function == 3 and frame[2] != 2:
                    continue
                record['rx'] = frame.hex(' ')
                if function == 0x83:
                    record['error'] = f'Modbus exception {frame[2]}'
                else:
                    record['value'] = int.from_bytes(frame[3:5], 'big')
                self.log.append(record)
                time.sleep(0.02)
                return record
        record.update(rx=bytes(data).hex(' '), error='No valid response before timeout')
        self.log.append(record)
        return record

    def close(self):
        self.serial.close()


# Documented basic readable registers; unavailable registers are recorded as errors.
REGISTERS = {
    0x0100: 'homing_command_state',
    0x0101: 'push_force_percent',
    0x0102: 'push_distance_0_01mm',
    0x0103: 'target_position_0_01mm',
    0x0104: 'speed_percent',
    0x0105: 'acceleration_percent',
    0x0106: 'relative_position_raw',
    0x0107: 'jog_command_raw',
    0x0200: 'homing_status',
    0x0201: 'motion_status',
    0x0202: 'actual_position_0_01mm',
    0x0204: 'motor_current_raw',
    0x0301: 'homing_direction',
    0x0302: 'device_id',
    0x0303: 'baud_code',
    0x0304: 'stopbits_code',
    0x0305: 'parity_code',
    0x0306: 'stroke_limit_0_01mm',
    0x0308: 'origin_offset_0_01mm',
    0x0309: 'push_speed_percent',
    0x030A: 'push_direction',
    0x0402: 'io_mode_enabled',
    0x0504: 'power_on_auto_home',
    0x1600: 'extended_target_position_0_01mm',
    0x1601: 'extended_push_distance_0_01mm',
    0x1602: 'extended_speed_0_01mm_s',
    0x1603: 'extended_acceleration_percent',
    0x1604: 'extended_push_force_percent',
    0x1605: 'extended_control_word',
    0x160C: 'extended_actual_position_0_01mm',
    0x160D: 'extended_motor_current_mA_raw',
    0x160E: 'extended_actual_speed_0_01mm_s_raw',
    0x160F: 'extended_alarm_code',
    0x1610: 'extended_reserved_emergency_status_raw',
    0x1611: 'extended_status_word',
}
for group in range(4):
    for field, suffix in enumerate(('position_0_01mm', 'acceleration_percent',
                                    'speed_percent', 'push_distance_0_01mm',
                                    'push_force_percent')):
        REGISTERS[0x0405 + group * 5 + field] = f'io_group_{group + 1}_{suffix}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='COM3')
    parser.add_argument('--id', type=int, default=1)
    parser.add_argument('--baud', type=int, default=115200)
    parser.add_argument('--parity', choices=['N', 'E', 'O'], default='N')
    parser.add_argument('--stopbits', type=int, choices=[1, 2], default=1)
    parser.add_argument('--probe', action='store_true', help='Only read ID and homing status')
    args = parser.parse_args()
    if not 1 <= args.id <= 247:
        parser.error('Device ID must be 1..247; broadcast is not supported')
    report = {'time': datetime.now().astimezone().isoformat(), 'connection': vars(args),
              'protocol': 'Modbus RTU, function 03 only', 'communication_confirmed': False,
              'identity_note': 'Register responses alone do not verify nameplate model or serial number.'}
    reader = None
    try:
        reader = Reader(args.port, args.baud, args.id, args.parity, args.stopbits)
        # A matching ID readback helps distinguish device replies from noise/echo.
        identity = reader.read(0x0302)
        status = reader.read(0x0200)
        confirmed = identity.get('value') == args.id and 'value' in status
        report['communication_confirmed'] = confirmed
        report['probe'] = [identity, status]
        if confirmed:
            print('Communication confirmed: ID register and homing status returned valid CRCs.')
            if not args.probe:
                report['parameters'] = {}
                for address, name in REGISTERS.items():
                    result = reader.read(address)
                    report['parameters'][name] = result
                    print(f"{result['address']} {name}: {result.get('value', result.get('error'))}")
                values = {name: item['value'] for name, item in report['parameters'].items() if 'value' in item}
                report['decoded'] = {}
                for name, value in values.items():
                    if name.endswith('_0_01mm'):
                        report['decoded'][name.replace('_0_01mm', '_mm')] = value / 100
                word = values.get('extended_status_word')
                if word is not None:
                    report['decoded']['extended_status_bits'] = {
                        label: bool(word & (1 << bit)) for bit, label in
                        [(15, 'controller_ready'), (10, 'motor_enabled'), (9, 'alarm_active'),
                         (8, 'moving'), (6, 'homed'), (5, 'in_position')]
                    }
        else:
            print('Communication NOT confirmed. Inspect report before any further action.')
    except (serial.SerialException, OSError) as exc:
        report['error'] = str(exc)
        print(f'Connection error: {exc}')
    finally:
        if reader is not None:
            report['frames'] = reader.log
            reader.close()
        destination = Path(__file__).resolve().parent / 'logs' / ('mcea_read_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.json')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'Report: {destination}')
    return 0 if report['communication_confirmed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
