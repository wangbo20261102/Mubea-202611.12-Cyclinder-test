"""MCEA supervised 10 mm direction test. No automatic homing or brake release."""
import argparse
import json
import struct
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from mcea_read import Reader, crc16

SPEED_RAW = 100  # 0.01 mm/s units: 1 mm/s
ACCEL_PERCENT = 1
DISTANCE_RAW = 1000  # 10 mm
TOLERANCE_RAW = 5  # 0.05 mm


class Device(Reader):
    def value(self, address):
        result = self.read(address)
        if 'value' not in result:
            raise RuntimeError(f"Read 0x{address:04X}: {result.get('error')}")
        return result['value']

    def write_ack(self, body):
        """Accept only control-word writes or the six-word position command."""
        function = body[1]
        if function == 6:
            address, value = struct.unpack('>HH', body[2:6])
            if address != 0x1605 or value != 0x0028:
                raise ValueError('Only the enabled-pause word may be written with function 06')
            expected = body
        elif function == 16:
            address, count = struct.unpack('>HH', body[2:6])
            if address != 0x1600 or count != 6 or body[6] != 12 or len(body) != 19:
                raise ValueError('Unexpected motion packet')
            target, push, speed, accel, force, control = struct.unpack('>6H', body[7:])
            if not (0 <= target <= 5000 and push == 0 and speed == SPEED_RAW
                    and accel == ACCEL_PERCENT and force == 0 and control in (0x20, 0x21)):
                raise ValueError('Motion parameters outside this test configuration')
            expected = body[:6]
        else:
            raise ValueError('Unsupported write function')
        request = body + crc16(body)
        record = {'tx': request.hex(' '), 'operation': 'write'}
        self.log.append(record)
        self.serial.reset_input_buffer()
        self.serial.write(request)
        self.serial.flush()
        data = bytearray()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            data.extend(self.serial.read(self.serial.in_waiting or 1))
            for offset in range(len(data) - 4):
                if data[offset] != self.id:
                    continue
                code = data[offset + 1]
                size = 5 if code == (function | 0x80) else 8
                if code not in (function, function | 0x80) or offset + size > len(data):
                    continue
                frame = bytes(data[offset:offset + size])
                if crc16(frame[:-2]) != frame[-2:]:
                    continue
                if code == (function | 0x80):
                    record.update(rx=frame.hex(' '), error=f'Modbus exception {frame[2]}')
                    raise RuntimeError(record['error'])
                if frame[:-2] != expected:
                    continue
                record['rx'] = frame.hex(' ')
                time.sleep(0.02)
                return
        record.update(rx=bytes(data).hex(' '), error='Write acknowledgement timeout')
        raise RuntimeError('Write result uncertain. No automatic retry.')

    def pause(self):
        # Keep motor enabled; request pause without forcing brake release.
        self.write_ack(struct.pack('>BBHH', self.id, 6, 0x1605, 0x0028))

    def snapshot(self):
        return {name: self.value(address) for name, address in (
            ('id', 0x0302), ('position', 0x160C), ('homing', 0x0200),
            ('status', 0x1611), ('alarm', 0x160F), ('control', 0x1605),
            ('io', 0x0402), ('limit', 0x0306), ('offset', 0x0308))}


def validate(state, device_id):
    problems = []
    word = state['status']
    if state['id'] != device_id:
        problems.append('Device ID mismatch')
    if state['homing'] != 1 or not word & (1 << 6):
        problems.append('尚未回零。请用厂家软件完成回零后再测试。')
    if state['alarm'] or word & (1 << 9):
        problems.append(f"存在报警：0x{state['alarm']:04X}")
    if not word & (1 << 10):
        problems.append('电机未使能。')
    if word & (1 << 8):
        problems.append('电机仍在运动。')
    if state['io'] != 0:
        problems.append('I/O 控制已开启，不能同时进行本测试。')
    # A completed home may leave Bit1 set. The next full command clears it.
    allowed_control = 0x0023 if state['homing'] == 1 and word & (1 << 6) else 0x0021
    if state['control'] & ~allowed_control:
        problems.append('控制字包含暂停、回零、点动或其他模式位，请先检查厂家软件。')
    return problems


def bounds(state):
    # Conservative allowance for nominal stroke, configured stroke and origin offset.
    margin = 100 + abs(state['offset'])
    return margin, min(5000, state['limit']) - margin


def plan(start, low, high):
    targets = [start + DISTANCE_RAW, start, start - DISTANCE_RAW, start]
    if any(not low <= point <= high for point in [start] + targets):
        raise RuntimeError(
            f'起点 {start / 100:.2f} mm 无法进行双向各10 mm测试；'
            f'本次保守位置范围为 {low / 100:.2f}～{high / 100:.2f} mm。'
            '请先用厂家软件回零，并低速移到约25 mm，随后重新启动本程序。')
    return targets


def parse_target_mm(text):
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError('目标位置必须为毫米数。') from exc
    if not value.is_finite() or not 0 <= value <= 50:
        raise argparse.ArgumentTypeError('目标位置必须在 0～50 mm 之间。')
    raw = int(value * 100)
    if value != Decimal(raw).scaleb(-2):
        raise argparse.ArgumentTypeError('目标位置的最小单位为 0.01 mm。')
    return raw


def confirm(message, token):
    response = input(f'{message}\n输入 {token} 继续，其他输入退出：').strip()
    if response != token:
        raise RuntimeError('操作员取消；不继续执行下一段。')


def check_motion_stop(stop_event):
    if stop_event is not None and stop_event.is_set():
        raise RuntimeError('操作员请求暂停。')


def move(device, target, expected_start, low, high, report, *, stop_event=None):
    before = device.snapshot()
    errors = validate(before, device.id)
    if errors:
        raise RuntimeError('; '.join(errors))
    if abs(before['position'] - expected_start) > TOLERANCE_RAW:
        raise RuntimeError('等待期间位置发生变化，测试中止，请重新读取起点。')
    live_low, live_high = bounds(before)
    high = min(high, live_high)
    if not max(low, live_low) <= target <= high:
        raise RuntimeError('目标位置超出当前允许行程。')
    if not low <= before['position'] <= high:
        raise RuntimeError('当前位置超出本段允许范围。')
    segment = {'from_mm': before['position'] / 100, 'target_mm': target / 100,
               'feedback': [], 'complete': False}
    report['segments'].append(segment)
    values = [target, 0, SPEED_RAW, ACCEL_PERCENT, 0, 0x20]
    prefix = struct.pack('>BBHHB', device.id, 16, 0x1600, 6, 12)
    # Clear the start bit, then raise it. Both packets carry the complete slow parameters.
    check_motion_stop(stop_event)
    report['write_attempted'] = True
    device.write_ack(prefix + struct.pack('>6H', *values))
    values[-1] = 0x21
    check_motion_stop(stop_event)
    report['trigger_attempted'] = True
    device.write_ack(prefix + struct.pack('>6H', *values))
    deadline = time.monotonic() + abs(target - before['position']) / SPEED_RAW + 15
    settled = 0
    last_print = 0
    while time.monotonic() < deadline:
        check_motion_stop(stop_event)
        alarm = device.value(0x160F)
        check_motion_stop(stop_event)
        status = device.value(0x1611)
        check_motion_stop(stop_event)
        position = device.value(0x160C)
        check_motion_stop(stop_event)
        segment['feedback'].append({'time': time.time(), 'position': position,
                                    'status': status, 'alarm': alarm})
        if alarm or status & (1 << 9) or not status & (1 << 10) or not status & (1 << 6):
            raise RuntimeError('报警、失能或回零状态丢失，终止测试。')
        if not low <= position <= high:
            raise RuntimeError('位置超出本次保守测试范围。')
        if position < min(target, before['position']) - 30 or position > max(target, before['position']) + 30:
            raise RuntimeError('反馈位置偏离本段预期范围。')
        if time.monotonic() - last_print > 0.5:
            print(f'当前位置 {position / 100:.2f} mm → 目标 {target / 100:.2f} mm', flush=True)
            last_print = time.monotonic()
        arrived = abs(position - target) <= TOLERANCE_RAW and not status & (1 << 8) and status & (1 << 5)
        settled = settled + 1 if arrived else 0
        if settled >= 3:
            segment.update(complete=True, final_mm=position / 100)
            return
        time.sleep(0.08)
    raise RuntimeError('运动超时；不自动返回或重试。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='COM3')
    parser.add_argument('--baud', type=int, default=115200)
    parser.add_argument('--id', type=int, default=1)
    parser.add_argument('--check', action='store_true', help='Read position and validate only; no writes')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--target-mm', dest='target_raw', metavar='MM', type=parse_target_mm, help='Move once to an absolute position at 1 mm/s')
    mode.add_argument('--center', action='store_true', help='Prepare at 25 mm before capturing the test start')
    args = parser.parse_args()
    if not 1 <= args.id <= 247:
        parser.error('ID must be 1..247')
    report = {'time': datetime.now().astimezone().isoformat(), 'connection': vars(args),
              'speed_mm_s': 1, 'acceleration_percent': ACCEL_PERCENT, 'distance_mm': 10,
              'segments': [], 'write_attempted': False, 'success': False}
    device = None
    try:
        device = Device(args.port, args.baud, args.id)
        initial = device.snapshot()
        report['initial'] = initial
        start = initial['position']
        report['original_position_mm'] = start / 100
        print(f'当前原始位置：{start / 100:.2f} mm；回零状态：{initial["homing"]}')
        low, high = bounds(initial)
        report['allowed_range_mm'] = [low / 100, high / 100]
        errors = validate(initial, args.id)
        if args.center and not 0 <= start <= high:
            errors.append('当前位置不适合执行向中部的准备运动。')
        if args.target_raw is not None:
            target = args.target_raw
            if start != 0 and not low <= start <= high:
                errors.append('当前位置超出允许范围，请重新检查设备状态。')
            if not low <= target <= high:
                errors.append(f'目标超出允许范围 {low / 100:.2f}～{high / 100:.2f} mm。')
            if errors:
                raise RuntimeError('\n'.join(errors))
            report['targets_mm'] = [target / 100]
            print(f'定位：{start / 100:.2f} → {target / 100:.2f} mm，速度 1 mm/s。')
            if not args.check and start != target:
                confirm('确认路径无障碍、负载固定、现场停止装置可用，并关闭其他控制软件。', 'START')
                move(device, target, start, 0 if start == 0 else low, high, report)
                print('定位完成，已确认到位。')
            elif args.check:
                print('只读检查通过。')
            else:
                print('当前位置已等于目标位置，无需移动。')
            report['success'] = True
            return 0

        planned_start = 2500 if args.center else start
        try:
            targets = plan(planned_start, low, high)
        except RuntimeError as exc:
            errors.append(str(exc))
        if errors:
            raise RuntimeError('\n'.join(errors))
        report['targets_mm'] = [p / 100 for p in targets]
        route = ([start, planned_start] if args.center else [start]) + targets
        print('路线：' + ' → '.join(f'{p / 100:.2f} mm' for p in route))
        if args.check:
            print('检查通过。此次只读检查，没有发送写入指令。')
            report['success'] = True
            return 0
        print('速度1 mm/s，每段约10秒。正负指位置值增减，实际上下方向由现场观察。')
        print('Ctrl+C 会尝试发送暂停；通信或程序故障时不保证停止，现场需能切断驱动运动。')
        confirm('确认上述完整路线无障碍、负载可靠固定，并关闭其他控制软件。', 'START')
        if args.center:
            print('先以1 mm/s移到25 mm，之后重新记录位置作为双向测试起点。')
            move(device, planned_start, start, min(low, start), high, report)
            centered = device.snapshot()
            errors = validate(centered, args.id)
            if errors:
                raise RuntimeError('; '.join(errors))
            start = centered['position']
            if abs(start - planned_start) > TOLERANCE_RAW:
                raise RuntimeError('准备运动未稳定在25 mm附近。')
            targets = plan(start, low, high)
            report['targets_mm'] = [p / 100 for p in targets]
            confirm(f'准备完成，测试起点为{start/100:.2f} mm，下一段正向10 mm。', 'GO')
        report['start_mm'] = start / 100
        previous = start
        for index, target in enumerate(targets):
            if index:
                confirm(f'下一段将移动到 {target / 100:.2f} mm。', 'GO')
            move(device, target, previous, low, high, report)
            previous = target
            if index in (0, 2):
                direction = '位置值增加方向' if index == 0 else '位置值减少方向'
                note = input(f'{direction}已经走完10 mm。请记录实际方向（上/下/伸出/缩回等）：').strip()
                report.setdefault('observed_directions', {})[direction] = note
        report['success'] = True
        print('两方向各10 mm测试完成，已返回本次起点。')
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        report['error'] = str(exc) or '操作员按下 Ctrl+C'
        print(f'测试停止：{report["error"]}')
        if device is not None and report['write_attempted']:
            try:
                device.pause()
                report['pause_acknowledged'] = True
                print('已收到暂停指令应答；仍需现场确认停止。不自动返回起点。')
            except (Exception, KeyboardInterrupt) as stop_error:
                report['pause_error'] = str(stop_error)
                print('暂停未确认！请立即使用现场停止装置。')
        return 1
    finally:
        if device is not None:
            report['frames'] = device.log
            device.close()
        output = Path(__file__).resolve().parent / 'logs' / ('direction_test_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.json')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'测试记录：{output}')


if __name__ == '__main__':
    raise SystemExit(main())
