# 通信协议与寄存器

协议：Modbus RTU；串口默认115200、8N1、站号1。以下是本项目已经核对并读取的公开地址，按零基协议地址直接发送，不使用40001偏移。

## 帧与运动方式

- 只读程序只实现03；CRC16多项式0xA001，初值0xFFFF，CRC低字节先发送。
- 回零按手册使用10连续写0x1600起的6个字，控制字由0x0020到0x0022。
- 慢速定位同样写完整6字，速度原始值100对应1 mm/s，加速度1%，推压段及推压力为0，控制字由0x0020到0x0021。
- 软件暂停用06写0x1605=0x0028；不强制松抱闸、不失能，不构成安全级停止。
- 运动和回零写入必须取得对应地址及数量的有效应答，异常或超时不自动重发。

## 已实现的可读地址

| 地址 | 程序字段 |
|---|---|
| `0x0100` | `homing_command_state` |
| `0x0101` | `push_force_percent` |
| `0x0102` | `push_distance_0_01mm` |
| `0x0103` | `target_position_0_01mm` |
| `0x0104` | `speed_percent` |
| `0x0105` | `acceleration_percent` |
| `0x0106` | `relative_position_raw` |
| `0x0107` | `jog_command_raw` |
| `0x0200` | `homing_status` |
| `0x0201` | `motion_status` |
| `0x0202` | `actual_position_0_01mm` |
| `0x0204` | `motor_current_raw` |
| `0x0301` | `homing_direction` |
| `0x0302` | `device_id` |
| `0x0303` | `baud_code` |
| `0x0304` | `stopbits_code` |
| `0x0305` | `parity_code` |
| `0x0306` | `stroke_limit_0_01mm` |
| `0x0308` | `origin_offset_0_01mm` |
| `0x0309` | `push_speed_percent` |
| `0x030A` | `push_direction` |
| `0x0402` | `io_mode_enabled` |
| `0x0405` | `io_group_1_position_0_01mm` |
| `0x0406` | `io_group_1_acceleration_percent` |
| `0x0407` | `io_group_1_speed_percent` |
| `0x0408` | `io_group_1_push_distance_0_01mm` |
| `0x0409` | `io_group_1_push_force_percent` |
| `0x040A` | `io_group_2_position_0_01mm` |
| `0x040B` | `io_group_2_acceleration_percent` |
| `0x040C` | `io_group_2_speed_percent` |
| `0x040D` | `io_group_2_push_distance_0_01mm` |
| `0x040E` | `io_group_2_push_force_percent` |
| `0x040F` | `io_group_3_position_0_01mm` |
| `0x0410` | `io_group_3_acceleration_percent` |
| `0x0411` | `io_group_3_speed_percent` |
| `0x0412` | `io_group_3_push_distance_0_01mm` |
| `0x0413` | `io_group_3_push_force_percent` |
| `0x0414` | `io_group_4_position_0_01mm` |
| `0x0415` | `io_group_4_acceleration_percent` |
| `0x0416` | `io_group_4_speed_percent` |
| `0x0417` | `io_group_4_push_distance_0_01mm` |
| `0x0418` | `io_group_4_push_force_percent` |
| `0x0504` | `power_on_auto_home` |
| `0x1600` | `extended_target_position_0_01mm` |
| `0x1601` | `extended_push_distance_0_01mm` |
| `0x1602` | `extended_speed_0_01mm_s` |
| `0x1603` | `extended_acceleration_percent` |
| `0x1604` | `extended_push_force_percent` |
| `0x1605` | `extended_control_word` |
| `0x160C` | `extended_actual_position_0_01mm` |
| `0x160D` | `extended_motor_current_mA_raw` |
| `0x160E` | `extended_actual_speed_0_01mm_s_raw` |
| `0x160F` | `extended_alarm_code` |
| `0x1610` | `extended_reserved_emergency_status_raw` |
| `0x1611` | `extended_status_word` |

字段名包含0_01mm时，毫米值=原始值/100；百分比设定不代表实测速度或推力。扩展速度单位0.01mm/s。电流保留16位原始值，符号解释按具体固件核对。

## 状态与边界

0x0200：0未回零、1回零完成、2回零中。0x0201：0运动中、1到位、2堵转。扩展状态字0x1611使用Bit10使能、Bit9报警、Bit8运动、Bit6回零完成、Bit5到位。不能只凭到位位判断已经回零。

手册中部分表格存在文字或排版不一致；程序保留原始值。控制器就绪位不作为唯一运动依据，未公开寄存器不扫描。回零方向1本机配置为后退端寻找，不等于所有安装中的向上或向下。

资料来源：[大寰编写的MCEA操作手册（第三方镜像）](https://manualzz.com/doc/87795589/dh-%E5%A4%A7%E5%AF%B0mcea%E7%94%B5%E7%BC%B8%E6%93%8D%E4%BD%9C%E6%89%8B%E5%86%8C-%E7%94%A8%E6%88%B7%E6%8C%87%E5%8D%97)。本项目未复制分发整本手册。
