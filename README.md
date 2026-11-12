# DH MCEA 电缸调试工具

使用 Python 3.12，通过 USB 转 RS485 与 DH-Robotics MCEA 内置驱动电缸通信。提供参数读取、受监督回零和双向各 10 mm 慢速方向测试。

本项目已对一台 MCEA-3G-02-050-C-W-F 进行通信和运动验证。其他型号、固件或安装方式需重新核对手册，不能直接套用行程及方向结论。

## 文件

| 文件 | 用途 |
|---|---|
| `mcea_read.py` | 读取55项已核实的公开寄存器，保存原始通信帧 |
| `mcea_home.py` | 人工输入HOME后，按厂家规定执行单方向回零 |
| `mcea_direction_test.py` | 1 mm/s、双向各10 mm测试，可先移至25 mm |
| `requirements.txt` | Python依赖 |
| `tests/` | 离线协议及运动范围检查，不连接硬件 |
| `docs/` | 设备资料、协议、操作、实测结果及GitHub上传说明 |
| 根目录的 `.cmd` 文件 | Windows双击入口：读取、回零、准备并慢速测试 |

## 安装

Windows PowerShell，在项目目录执行：

```powershell
py -3.12 -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
$env:PYTHONIOENCODING = "utf-8"
```

不需要激活环境，也不需要更改PowerShell执行策略。
安装完成后也可双击对应的`.cmd`入口；回零与运动测试仍需在窗口内输入确认词。

## 先读取，再操作

本次已验证连接：COM3、115200波特率、8数据位、无校验、1停止位、Modbus站号1。重新插拔后端口可能变化。先连接24 V电源和正确的RS485转接器，关闭占用串口的其他软件。

```powershell
# 只读查询，不运动
& ".\.venv\Scripts\python.exe" .\mcea_read.py --port COM3 --baud 115200 --id 1

# 回零前只读检查
& ".\.venv\Scripts\python.exe" .\mcea_home.py --port COM3 --check

# 回零：输入HOME才执行，可能发生端部寻找运动
& ".\.venv\Scripts\python.exe" .\mcea_home.py --port COM3

# 方向测试前只读检查：计划先到25 mm
& ".\.venv\Scripts\python.exe" .\mcea_direction_test.py --port COM3 --center --check

# 运动测试：输入START，后续各段输入GO
& ".\.venv\Scripts\python.exe" .\mcea_direction_test.py --port COM3 --center
```

`--center`路线为：原位置 → 25 → 35 → 25 → 15 → 25 mm。到达中部后重新读取当前位置作为测试起点，实际目标按该读数计算。省略`--center`时，以现位置为起点，必须有双侧各10 mm余量。程序不会因未回零而自动回零。

日志保存在`logs/`，默认不提交Git。不存在串口或通信失败时不自动重发运动指令。

## 运行边界

- 确认完整路径无人员或障碍、线缆不受拉扯、工装与负载固定，现场停止装置可用。程序没有障碍物检测。
- 方向测试使用1 mm/s、加减速度1%；回零速度由驱动器逻辑决定，不能保证同样为1 mm/s。
- Ctrl+C只尝试软件暂停，保持电机使能。通信断开、关闭窗口或软件故障时不保证停止。竖直负载应防止坠落。
- 暂停和报警后不自动返回、不清除报警、不强制松抱闸。再次操作前检查实际状态。
- 电流原始字不是实测推力。未回零的位置反馈不能作为已标定坐标。

## 验证

```powershell
& ".\.venv\Scripts\python.exe" -m unittest discover -s tests -v
```

测试不会打开串口或移动设备。现场验证已完成双向各10 mm，正方向向下由操作员确认；最后返回中点因USB串口断开未完成，不能把整轮路线标为全部成功。详情见[实测记录](docs/TEST_RESULTS.md)。

## 文档

- [设备规格和接线](docs/DEVICE.md)
- [通信及寄存器](docs/PROTOCOL.md)
- [操作与恢复](docs/OPERATIONS.md)
- [实测结果](docs/TEST_RESULTS.md)
- [上传GitHub](docs/GITHUB.md)

项目仓库：[wangbo20261102/Mubea-202611.12-Cyclinder-test](https://github.com/wangbo20261102/Mubea-202611.12-Cyclinder-test)。许可证尚未指定；如需对外开源，请由仓库所有者选择许可证。
