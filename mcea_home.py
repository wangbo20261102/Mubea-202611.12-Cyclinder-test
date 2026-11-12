"""Supervised MCEA homing, using the manufacturer's exact two RTU commands."""
import argparse
import json
import struct
import time
from datetime import datetime
from pathlib import Path

from mcea_direction_test import Device
from mcea_read import crc16


# Manufacturer manual section 2.4.3.1; no direction/offset/Flash changes.
HOME_PREPARE = bytes.fromhex('01 10 16 00 00 06 0C 00 00 00 00 00 00 00 00 00 00 00 20 E5 6B')
HOME_TRIGGER = bytes.fromhex('01 10 16 00 00 06 0C 00 00 00 00 00 00 00 00 00 00 00 22 64 AA')


class HomeDevice(Device):
    def home_command(self, trigger):
        template = HOME_TRIGGER if trigger else HOME_PREPARE
        body = bytes([self.id]) + template[1:-2]
        packet = body + crc16(body)
        expected = body[:6]
        record = {'operation': 'home_trigger' if trigger else 'home_prepare', 'tx': packet.hex(' ')}
        self.log.append(record)
        self.serial.reset_input_buffer()
        self.serial.write(packet)
        self.serial.flush()
        data = bytearray()
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            data.extend(self.serial.read(self.serial.in_waiting or 1))
            for offset in range(len(data) - 4):
                if data[offset] != self.id or data[offset + 1] not in (0x10, 0x90):
                    continue
                size = 5 if data[offset + 1] == 0x90 else 8
                frame = bytes(data[offset:offset + size])
                if len(frame) != size or crc16(frame[:-2]) != frame[-2:]:
                    continue
                if frame[1] == 0x90:
                    record.update(rx=frame.hex(' '), error=f'Modbus exception {frame[2]}')
                    raise RuntimeError(record['error'])
                if frame[:-2] == expected:
                    record['rx'] = frame.hex(' ')
                    time.sleep(0.03)
                    return
        record.update(rx=bytes(data).hex(' '), error='Acknowledgement timeout')
        raise RuntimeError('回零指令应答未确认，不自动重发。')


def preconditions(state, expected_id):
    errors = []
    if state['id'] != expected_id:
        errors.append('设备ID不匹配。')
    if state['alarm'] or state['status'] & 0x0200:
        errors.append('设备存在报警。')
    if not state['status'] & 0x0400:
        errors.append('请先通过厂家软件完成电机使能。')
    if state['status'] & 0x0100:
        errors.append('设备正在运动。')
    if state['io'] != 0:
        errors.append('I/O模式已开启，需先检查外部控制。')
    if state['control'] & ~0x0021:
        errors.append('控制字包含暂停、回零、点动或其他模式，请先通过厂家软件检查。')
    if state['home_direction'] != 1:
        errors.append('回零方向已改变，本程序只允许已核实的方向1（后退）。')
    if state['homing'] == 2:
        errors.append('正在回零，不能重复触发。')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='COM3')
    parser.add_argument('--baud', type=int, default=115200)
    parser.add_argument('--id', type=int, default=1)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.id <= 247:
        parser.error('ID must be 1..247')
    report = {'time': datetime.now().astimezone().isoformat(), 'connection': vars(args),
              'write_attempted': False, 'success': False, 'feedback': []}
    device = None
    try:
        device = HomeDevice(args.port, args.baud, args.id)
        state = device.snapshot()
        state['home_direction'] = device.value(0x0301)
        report['initial'] = state
        print(f"当前位置反馈：{state['position']/100:.2f} mm；回零状态：{state['homing']}")
        print('方向1：后退方向寻找端部。安装后的实际上下方向需现场观察。')
        errors = preconditions(state, args.id)
        if errors:
            raise RuntimeError('\n'.join(errors))
        if state['homing'] == 1 and state['status'] & 0x0040:
            print('已回零，不重复回零。可以通过厂家软件低速移至中部后进行方向测试。')
            report['success'] = True
            return 0
        if args.check:
            print('回零前检查通过；只读模式，未发送回零指令。')
            report['success'] = True
            return 0
        print('回零会发生实际运动。内部回零速度未获确认，不保证为1 mm/s。')
        print('确认滑台到后退端的全部路径无障碍，竖直负载已可靠固定，现场停止装置可用。')
        print('Ctrl+C仅尝试软件暂停；关闭窗口或拔USB不能保证停止。')
        if input('输入 HOME 开始回零，其他输入退出：').strip() != 'HOME':
            raise RuntimeError('操作员取消。')
        # Recheck after operator confirmation; do not act on stale state.
        current = device.snapshot()
        current['home_direction'] = device.value(0x0301)
        errors = preconditions(current, args.id)
        if errors:
            raise RuntimeError('\n'.join(errors))
        if current['homing'] == 1:
            raise RuntimeError('等待期间回零状态已改变，退出，不重复触发。')
        report['write_attempted'] = True
        device.home_command(False)
        device.home_command(True)
        print('已发送回零指令，正在读取反馈……')
        deadline = time.monotonic() + 25
        stable = 0
        while time.monotonic() < deadline:
            alarm = device.value(0x160F)
            word = device.value(0x1611)
            homing = device.value(0x0200)
            position = device.value(0x160C)
            report['feedback'].append(dict(time=time.time(), alarm=alarm, status=word,
                                           homing=homing, position=position))
            print(f'回零状态={homing}，位置={position/100:.2f} mm，报警=0x{alarm:04X}', flush=True)
            if alarm or word & 0x0200 or not word & 0x0400:
                raise RuntimeError('回零中报警或失能，停止后续操作。')
            done = homing == 1 and word & 0x0040 and not word & 0x0100
            stable = stable + 1 if done else 0
            if stable >= 3:
                report['success'] = True
                print('设备反馈回零成功。请现场确认没有把外部障碍物当作端部。')
                print('原点偏置保持原设置，回零后位置不一定恰好为0.00 mm。')
                print('本程序结束，不自动移至中点，也不启动方向测试。')
                return 0
            time.sleep(0.2)
        raise RuntimeError('25秒内未确认回零成功；不自动重试。')
    except (Exception, KeyboardInterrupt) as exc:
        report['error'] = str(exc) or 'Ctrl+C'
        print(f'操作停止：{report["error"]}')
        if device is not None and report['write_attempted']:
            try:
                device.pause()
                report['pause_acknowledged'] = True
                print('已收到暂停应答，请现场确认停止。')
            except (Exception, KeyboardInterrupt) as stop_error:
                report['pause_error'] = str(stop_error)
                print('暂停未确认，请立即使用现场停止装置。')
        return 1
    finally:
        if device is not None:
            report['frames'] = device.log
            device.close()
        destination = Path(__file__).resolve().parent / 'logs' / ('homing_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.json')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'回零记录：{destination}')


if __name__ == '__main__':
    raise SystemExit(main())
