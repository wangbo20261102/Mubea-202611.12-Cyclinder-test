"""Windows control panel for single-step motion of a DH MCEA cylinder."""

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from serial.tools import list_ports

from mcea_direction_test import Device, bounds, move, validate


BAUD = 115200
DEVICE_ID = 1
STEPS = {'0.10': 10, '0.50': 50, '1.00': 100, '2.00': 200, '4.00': 400}


def jog_target(state, delta):
    position = state['position']
    low, high = bounds(state)
    target = position + delta
    if (position == 0 or low <= position <= high) and low <= target <= high:
        return target
    return None


class JogWindow:
    def __init__(self, root):
        self.root = root
        self.root.title('MCEA 电缸点动')
        self.root.minsize(510, 340)
        self.root.protocol('WM_DELETE_WINDOW', self.close)

        self.port = tk.StringVar()
        self.step = tk.StringVar(value='1.00')
        self.armed = tk.BooleanVar(value=False)
        self.position = tk.StringVar(value='— mm')
        self.travel = tk.StringVar(value='行程范围待读取')
        self.status = tk.StringVar(value='选择 USB 转 RS485 串口，再点击读取状态。')
        self.results = queue.Queue()
        self.state = None
        self.stop_event = None
        self.busy = False
        self.closing = False

        panel = ttk.Frame(root, padding=18)
        panel.pack(fill='both', expand=True)
        connection = ttk.Frame(panel)
        connection.pack(fill='x')
        ttk.Label(connection, text='串口').pack(side='left', padx=(0, 8))
        self.port_box = ttk.Combobox(connection, textvariable=self.port, width=9, state='readonly')
        self.port_box.pack(side='left')
        self.port_box.bind('<<ComboboxSelected>>', self.reset_connection)
        self.scan_button = ttk.Button(connection, text='刷新串口', command=self.scan)
        self.scan_button.pack(side='left', padx=8)
        self.read_button = ttk.Button(connection, text='读取状态', command=self.read)
        self.read_button.pack(side='left')

        ttk.Label(panel, text='最近反馈位置').pack(anchor='w', pady=(16, 0))
        ttk.Label(panel, textvariable=self.position, font=('Segoe UI', 24)).pack(anchor='w')
        ttk.Label(panel, textvariable=self.travel).pack(anchor='w', pady=(0, 10))
        self.arm_checkbox = ttk.Checkbutton(
            panel, text='已确认路径无障碍、负载固定、现场停止装置可用',
            variable=self.armed, command=self.update_controls,
        )
        self.arm_checkbox.pack(anchor='w')

        controls = ttk.Frame(panel)
        controls.pack(fill='x', pady=12)
        ttk.Label(controls, text='步长 mm').pack(side='left')
        self.step_box = ttk.Combobox(
            controls, textvariable=self.step, values=tuple(STEPS), width=5, state='readonly',
        )
        self.step_box.pack(side='left', padx=(5, 12))
        self.step_box.bind('<<ComboboxSelected>>', lambda _event: self.update_controls())
        self.minus = ttk.Button(controls, text='− 点动', command=lambda: self.jog(-1))
        self.minus.pack(side='left', padx=(0, 5))
        self.plus = ttk.Button(controls, text='+ 点动', command=lambda: self.jog(1))
        self.plus.pack(side='left')
        self.pause_button = ttk.Button(controls, text='软件暂停', command=self.pause)
        self.pause_button.pack(side='right')

        ttk.Label(panel, text='每次点击移动一步 · 速度 1 mm/s · 紧急情况使用现场停止装置').pack(anchor='w')
        ttk.Label(panel, textvariable=self.status, wraplength=470, justify='left').pack(anchor='w', pady=(8, 0))
        self.scan()
        self.root.after(50, self.poll_result)

    def scan(self):
        ports = [port for port in list_ports.comports() if port.vid is not None]
        devices = [port.device for port in sorted(ports)]
        self.port_box.configure(values=devices)
        if self.port.get() not in devices:
            preferred = [port.device for port in ports if (port.vid, port.pid) == (0x0403, 0x6001)]
            self.port.set(preferred[0] if len(preferred) == 1 else '')
        self.reset_connection()
        if not devices:
            self.status.set('未发现 USB 串口，请检查转接器并刷新。')

    def reset_connection(self, _event=None):
        self.armed.set(False)
        self.show_state(None)
        self.status.set('点击“读取状态”检查电缸。')
        self.update_controls()

    def show_state(self, state):
        self.state = state
        if state is None:
            self.position.set('— mm')
            self.travel.set('行程范围待读取')
            return
        low, high = bounds(state)
        self.position.set(f"{state['position'] / 100:.2f} mm")
        self.travel.set(f'允许目标范围 {low / 100:.2f}～{high / 100:.2f} mm')

    def update_controls(self):
        ready = (
            not self.busy and self.state is not None and self.armed.get()
            and not validate(self.state, DEVICE_ID)
        )
        for button, sign in ((self.minus, -1), (self.plus, 1)):
            enabled = ready and jog_target(self.state, sign * STEPS[self.step.get()]) is not None
            button.configure(state='normal' if enabled else 'disabled')
        self.arm_checkbox.configure(state='disabled' if self.busy or self.state is None else 'normal')
        self.scan_button.configure(state='disabled' if self.busy else 'normal')
        self.read_button.configure(state='normal' if self.port.get() and not self.busy else 'disabled')
        for box in (self.port_box, self.step_box):
            box.configure(state='disabled' if self.busy else 'readonly')
        self.pause_button.configure(
            state='normal' if self.stop_event is not None and not self.stop_event.is_set() else 'disabled',
        )

    def read(self):
        if not self.busy and self.port.get():
            self.start_work()

    def jog(self, sign):
        if self.busy or not self.armed.get() or self.state is None or validate(self.state, DEVICE_ID):
            return
        target = jog_target(self.state, sign * STEPS[self.step.get()])
        if target is not None:
            self.start_work(target, self.state['position'])

    def start_work(self, target=None, start=None):
        self.busy = True
        self.stop_event = threading.Event() if target is not None else None
        if target is None:
            self.status.set('正在读取电缸状态…')
        else:
            self.status.set(f'本步目标 {target / 100:.2f} mm，等待设备反馈…')
        self.update_controls()
        threading.Thread(
            target=self.communicate, args=(self.port.get(), target, start, self.stop_event),
        ).start()

    def communicate(self, port, target, start, stop_event):
        device = None
        state = None
        report = {'segments': [], 'write_attempted': False}
        try:
            device = Device(port, BAUD, DEVICE_ID)
            if target is not None:
                before = device.snapshot()
                if before['position'] != start:
                    raise RuntimeError('位置已变化，请重新读取状态。')
                low, high = bounds(before)
                move(device, target, start, 0 if start == 0 else low, high, report,
                     stop_event=stop_event)
            state = device.snapshot()
            problems = validate(state, DEVICE_ID)
            if problems:
                status = ' '.join(problems)
            elif target is None:
                status = '状态读取成功。确认现场条件后即可点动。'
            else:
                status = f"已确认本步到位，最新反馈 {state['position'] / 100:.2f} mm。"
            result = (state, status, bool(problems))
        except Exception as exc:
            status = str(exc)
            if device is not None and report.get('trigger_attempted') and not report['segments'][-1]['complete']:
                try:
                    device.pause()
                    status += '\n驱动器已应答暂停，请现场确认已停止。'
                except Exception:
                    status += '\n暂停未获应答，请立即使用现场停止装置。'
            result = (None, status, True)
        finally:
            if device is not None:
                try:
                    device.close()
                except Exception as exc:
                    result = (None, f'{result[1]}\n关闭串口时出错：{exc}', True)
        self.results.put(result)

    def poll_result(self):
        try:
            state, status, failed = self.results.get_nowait()
        except queue.Empty:
            self.root.after(50, self.poll_result)
            return
        self.busy = False
        self.stop_event = None
        if self.closing:
            if failed:
                messagebox.showwarning('电缸状态', status, parent=self.root)
            self.root.destroy()
            return
        if failed:
            self.armed.set(False)
        self.show_state(state)
        self.status.set(status)
        self.update_controls()
        self.root.after(50, self.poll_result)

    def pause(self):
        if self.stop_event is not None:
            self.stop_event.set()
            self.armed.set(False)
            self.status.set('已请求暂停，等待驱动器反馈…')
            self.update_controls()

    def close(self):
        if not self.busy:
            self.root.destroy()
            return
        self.closing = True
        self.pause()


if __name__ == '__main__':
    root = tk.Tk()
    JogWindow(root)
    root.mainloop()
