# BanBox BLE 通信协议文档

> 版本: 1.0  
> 最后更新: 2026-05-26  
> 适用产品: BanBox 音效器 (BG_PRODUCT_ID = 0x0001)

---

## 目录

1. [概述](#1-概述)
2. [BLE GATT 服务定义](#2-ble-gatt-服务定义)
3. [AA55 协议帧格式](#3-aa55-协议帧格式)
4. [命令 ID 总表](#4-命令-id-总表)
5. [链路层机制](#5-链路层机制)
6. [连接与同步流程](#6-连接与同步流程)
7. [数据命令详细定义](#7-数据命令详细定义)
   - 7.1 [CMD_VOLUME (0x30)](#71-cmd_volume-0x30)
   - 7.2 [CMD_DRC (0x10)](#72-cmd_drc-0x10)
   - 7.3 [CMD_REVERB (0x11)](#73-cmd_reverb-0x11)
   - 7.4 [CMD_EQ (0x12)](#74-cmd_eq-0x12)
   - 7.5 [CMD_DELAY (0x13)](#75-cmd_delay-0x13)
   - 7.6 [CMD_GAIN (0x14)](#76-cmd_gain-0x14)
   - 7.7 [CMD_LOOPER (0x20)](#77-cmd_looper-0x20)
   - 7.8 [CMD_LOOPER_SEG_STATE (0x21)](#78-cmd_looper_seg_state-0x21)
   - 7.9 [CMD_METRONOME (0x31)](#79-cmd_metronome-0x31)
   - 7.10 [CMD_SYSTEM (0x32)](#710-cmd_system-0x32)
   - 7.11 [CMD_BATTERY_CALIB (0x33)](#711-cmd_battery_calib-0x33)
   - 7.12 [CMD_WAV_EXPORT (0x40)](#712-cmd_wav_export-0x40)
8. [音源下载协议 (Soundbank DL)](#8-音源下载协议-soundbank-dl)
9. [旧版 ABBA 协议 (已废弃)](#9-旧版-abba-协议-已废弃)
10. [附录](#10-附录)

---

## 1. 概述

BanBox 系统由 **MCU 下位机** (BP10 芯片, NDS32 架构, FreeRTOS) 和 **Android App 上位机** 组成，通过 BLE 4.2 进行双向通信。

通信采用 **AA55 协议** — 基于 CRC16 校验的可靠帧协议，支持 ACK/NACK 重传机制。协议同时承载：
- **参数同步**: App 连接后全量同步设备参数
- **实时控制**: 音效参数、音量、Looper 控制
- **系统通知**: 电量、系统状态、低功耗状态
- **大数据传输**: WAV 文件导出、音源数据下载

### 数据流向

```
App (Android)                          MCU (BP10)
     |                                     |
     |--- WRITE (AB01) ------------------>|  命令下发
     |<-- NOTIFY (AB02) -----------------|  状态上报/ACK
     |                                     |
```

---

## 2. BLE GATT 服务定义

### 2.1 服务信息

| 属性 | 值 |
|------|------|
| Service UUID | `0xAB00` |
| 设备名格式 | `BG-ctrl-XXXX` (XXXX = 芯片 ID 后 4 位十六进制) |
| 协商 MTU | 250 |

### 2.2 Characteristic 列表

| 名称 | UUID | 属性 | Handle | 用途 |
|------|------|------|--------|------|
| AB01 | `0000ab01-0000-1000-8000-00805f9b34fb` | READ + WRITE | 0x0006 | App → MCU (写入命令) |
| AB02 | `0000ab02-0000-1000-8000-00805f9b34fb` | NOTIFY | 0x0008 | MCU → App (主要通知通道) |
| AB03 | `0000ab03-0000-1000-8000-00805f9b34fb` | NOTIFY | 0x000B | MCU → App (备用通道，当前未使用) |

### 2.3 通信通道选择

App 写入 AB01 的数据由 MCU `app_att_write()` 回调接收，根据前两个字节判断协议类型：
- **AA55 帧头** (`0xAA 0x55`): 路由到 `BleProto_OnFrameReceived()` 处理二进制协议
- **其他**: 路由到 `ShellIO_BLE_OnDataReceived()` 处理文本 Shell 命令

MCU 通过 AB02 (GattServerNotify) 向 App 发送数据，单次最大 200 字节。

---

## 3. AA55 协议帧格式

### 3.1 帧结构

```
+--------+--------+--------+--------+============+--------+--------+
| 0xAA   | 0x55   | CMD    | SEQ    | PAYLOAD[N] | CRC_HI | CRC_LO |
| 1 byte | 1 byte | 1 byte | 1 byte | 0~200 bytes| 1 byte | 1 byte |
+--------+--------+--------+--------+============+--------+--------+
  帧头 (2B)                帧头共 4B                    CRC16 (2B)

总帧长 = 4 + N + 2 字节，其中 N ≤ 200
```

### 3.2 字段说明

| 字段 | 偏移 | 长度 | 说明 |
|------|------|------|------|
| Header | 0 | 2B | 固定 `0xAA 0x55` |
| CMD | 2 | 1B | 命令 ID，见第 4 节 |
| SEQ | 3 | 1B | 序列号，范围 1~254，到 254 后回绕到 1 |
| Payload | 4 | NB | 命令载荷，最大 200 字节 |
| CRC16 | 4+N | 2B | CRC16-CCITT 校验 (大端序)，计算范围: Header + CMD + SEQ + Payload |

### 3.3 CRC16 算法

- **多项式**: 0x1021 (CRC16-CCITT)
- **初始值**: 0xFFFF
- **计算范围**: 从 Header[0] 到 Payload[N-1] (不含 CRC 字段本身)
- **字节序**: CRC 高字节在前 (大端序)
- **查表实现**: 使用 256 项查表加速

```
伪代码:
crc = 0xFFFF
for each byte b in [Header0, Header1, CMD, SEQ, Payload...]:
    crc = (crc << 8) ^ table[(crc >> 8) ^ b] & 0xFFFF
return crc  // 高字节先发
```

### 3.4 SEQ 序列号规则

- 范围: 1~254 (0 和 0xFF 不使用)
- 递增: 每次发送新帧时 `seq++`，到 254 后回绕到 1
- ACK 匹配: ACK 帧的 SEQ 必须与被确认帧的 SEQ 一致
- 线程安全: MCU 端使用 `taskENTER_CRITICAL()` 保护计数器

---

## 4. 命令 ID 总表

### 4.1 链路控制命令 (cmd < 0x10)

| 命令 | 值 | 方向 | 说明 |
|------|------|------|------|
| BLE_CMD_ACK | 0x00 | 双向 | 确认应答。Payload[0] = 被确认的 CMD |
| BLE_CMD_NACK | 0x01 | 双向 | 否认应答。无 Payload |
| BLE_CMD_SYNC_REQ | 0x02 | App→MCU | 请求全量参数同步 |
| BLE_CMD_SYNC_START | 0x03 | MCU→App | 同步开始标记。Payload[0] = 参数组数量 |
| BLE_CMD_SYNC_END | 0x04 | MCU→App | 同步结束标记。无 Payload |

### 4.2 音效参数命令 (0x10~0x1F)

| 命令 | 值 | 方向 | 说明 |
|------|------|------|------|
| BLE_CMD_DRC | 0x10 | 双向 | DRC 压缩器参数 |
| BLE_CMD_REVERB | 0x11 | 双向 | 混响参数 |
| BLE_CMD_EQ | 0x12 | 双向 | 均衡器参数 |
| BLE_CMD_DELAY | 0x13 | 双向 | 延迟效果参数 |
| BLE_CMD_GAIN | 0x14 | 双向 | 增益控制 |

### 4.3 Looper 命令 (0x20~0x2F)

| 命令 | 值 | 方向 | 说明 |
|------|------|------|------|
| BLE_CMD_LOOPER | 0x20 | 双向 | Looper 参数 |
| BLE_CMD_LOOPER_SEG_STATE | 0x21 | MCU→App | 各段运行时状态 (重连同步) |

### 4.4 系统/控制命令 (0x30~0x3F)

| 命令 | 值 | 方向 | 说明 |
|------|------|------|------|
| BLE_CMD_VOLUME | 0x30 | 双向 | 音量参数 |
| BLE_CMD_METRONOME | 0x31 | 双向 | 节拍器参数 |
| BLE_CMD_SYSTEM | 0x32 | 双向 | 系统通知 (子类型区分) |
| BLE_CMD_BATTERY_CALIB | 0x33 | 双向 | 电池校准 |

### 4.5 数据传输命令 (0x40~0x4F)

| 命令 | 值 | 方向 | 说明 |
|------|------|------|------|
| BLE_CMD_WAV_EXPORT | 0x40 | 双向 | WAV 文件 BLE 导出 |

### 4.6 命令分类

```c
#define BLE_CMD_IS_DATA(cmd)  ((cmd) >= 0x10)
```

- **数据命令** (cmd ≥ 0x10): 需要回复 ACK
- **链路命令** (cmd < 0x10): ACK/NACK/SYNC，不需要二次确认

---

## 5. 链路层机制

### 5.1 可靠发送 (SendReliable)

用于 App→MCU 的参数设置命令。

```
发送方                              接收方
  |--- Frame(cmd, seq, payload) ---->|
  |                                  |--- 校验 CRC
  |<------ ACK(seq, cmd) ------------|  CRC 正确
  |                                  |--- 或 NACK(seq) --- CRC 错误
  
超时未收到 ACK → 重发 (最多 5 次)
```

**参数:**
- ACK 超时: 200ms (MCU), 300ms (App)
- 最大重试: 5 次
- 重试间隔: 超时时间

### 5.2 单次发送 (SendOnce)

用于 MCU→App 的批量数据流 (如 WAV 导出数据包)。不等待 ACK，不重试。

```
发送方                              接收方
  |--- Frame(cmd, seq, payload) ---->|
  (不等待 ACK，继续发送下一帧)
```

### 5.3 同步发送 (Sync Send)

用于 MCU→App 的全量参数同步。fire-and-forget 模式，不等待 ACK。

**参数:**
- 每帧最多重试: 3 次 (仅发送失败时重试，不等 ACK)
- 重试间隔: 30ms
- 帧间隔: 50ms (大于典型 BLE 连接间隔，降低栈负载)
- 失败策略: 单个参数发送失败后跳过，继续下一个

### 5.4 ACK 排队机制

MCU 收到数据命令后，ACK 被放入队列 (`g_pending_acks[]`)，在 `BleProto_Process()` 中统一发送。同步期间 ACK 发送暂停，同步结束后有 300ms 冷却期再排空积压 ACK。

**原因**: `send_frame()` 使用 static 缓冲区，同步任务与主循环并发调用会导致数据覆盖和 BLE 栈崩溃。

---

## 6. 连接与同步流程

### 6.1 完整连接流程

```
App                                    MCU
 |------- BLE Scan (BG-ctrl-XXXX) ---->|
 |------- BLE Connect ---------------->|
 |------- Request MTU = 250 ---------->|
 |------- Discover Services ---------->|
 |------- Enable CCCD on AB02 ------->|  (写入 0x0001 使能 Notify)
 |                                     |  触发 BleProto_RequestSync()
 |                                     |  (延迟 500ms 后启动同步任务)
 |<-- SYNC_START (group_count=6) -----|
 |<-- VOLUME (5 bytes) ---------------|
 |<-- DRC (5 bytes) ------------------|
 |<-- REVERB (3 bytes) ---------------|
 |<-- EQ (3+N*10 bytes) --------------|
 |<-- METRONOME (5 bytes) ------------|
 |<-- LOOPER (15 bytes) --------------|
 |<-- LOOPER_SEG_STATE (12 bytes) ----|
 |<-- SYNC_END -----------------------|
 |<-- SYSTEM/BATTERY (2 bytes) -------|
 |<-- SYSTEM/LP_STATE (2 bytes) ------|
 |<-- SYSTEM/LP_TIMEOUT (2 bytes) ----|
 |<-- SYSTEM/PRODUCT_ID (3 bytes) ----|
 |                                     |
 |  (同步完成，App 更新 UI)            |
```

### 6.2 同步参数组

同步期间 MCU 按固定顺序发送以下参数组 (group_count = 6):

| 序号 | 命令 | 说明 |
|------|------|------|
| 1 | CMD_VOLUME | 5 通道音量 |
| 2 | CMD_DRC | DRC 压缩器 |
| 3 | CMD_REVERB | 混响 |
| 4 | CMD_EQ | 均衡器 |
| 5 | CMD_METRONOME | 节拍器 |
| 6 | CMD_LOOPER + CMD_LOOPER_SEG_STATE | Looper 参数 + 各段状态 |

SYNC_END 之后额外发送:
- CMD_SYSTEM/BATTERY — 当前电量
- CMD_SYSTEM/LP_STATE — 低功耗开关状态
- CMD_SYSTEM/LP_TIMEOUT — 低功耗超时
- CMD_SYSTEM/PRODUCT_ID — 产品标识

### 6.3 断连重连

MCU 在 BLE 断开时调用 `BleProto_OnDisconnected()`，清除同步状态。App 重连后再次使能 CCCD，MCU 自动触发新的全量同步。

---

## 7. 数据命令详细定义

### 7.1 CMD_VOLUME (0x30)

**方向**: 双向  
**Payload 长度**: 5 字节

| 偏移 | 长度 | 字段 | 类型 | 范围 | 说明 |
|------|------|------|------|------|------|
| 0 | 1 | mic1_volume | uint8 | 0~100 | MIC1 音量 |
| 1 | 1 | mic2_volume | uint8 | 0~100 | MIC2 音量 |
| 2 | 1 | guitar1_volume | uint8 | 0~100 | 吉他1 音量 |
| 3 | 1 | guitar2_volume | uint8 | 0~100 | 吉他2 音量 |
| 4 | 1 | output_volume | uint8 | 0~100 | 主输出音量 |

---

### 7.2 CMD_DRC (0x10)

**方向**: 双向  
**Payload 长度**: 5 字节 (MCU 同步) / 8 字节 (App 解析兼容)

MCU 同步发送格式 (5 字节):

| 偏移 | 长度 | 字段 | 类型 | 说明 |
|------|------|------|------|------|
| 0 | 2 | threshold | uint16 LE | DRC 阈值 |
| 2 | 1 | ratio | uint8 | 压缩比 |
| 3 | 1 | attack | uint8 | 启动时间 |
| 4 | 1 | release | uint8 | 释放时间 |

> **注意**: App 端 `BleParamCache.getDrcParams()` 按 8 字节解析 (每个参数 uint16 LE)，与 MCU 同步发送的 5 字节格式存在差异。App→MCU 下发时应使用 8 字节格式。

App 下发格式 (8 字节):

| 偏移 | 长度 | 字段 | 类型 | 说明 |
|------|------|------|------|------|
| 0 | 2 | threshold | uint16 LE | DRC 阈值 |
| 2 | 2 | ratio | uint16 LE | 压缩比 |
| 4 | 2 | attack | uint16 LE | 启动时间 |
| 6 | 2 | release | uint16 LE | 释放时间 |

---

### 7.3 CMD_REVERB (0x11)

**方向**: 双向  
**Payload 长度**: 3 字节

| 偏移 | 长度 | 字段 | 类型 | 范围 | 说明 |
|------|------|------|------|------|------|
| 0 | 1 | room_size | uint8 | 0~100 | 房间大小 |
| 1 | 1 | damping | uint8 | 0~100 | 阻尼 |
| 2 | 1 | wet_dry | uint8 | 0~100 | 干湿比 |

---

### 7.4 CMD_EQ (0x12)

**方向**: 双向  
**Payload 长度**: 3 + band_count × 10 字节 (最大 103 字节 = 3 + 10×10)

| 偏移 | 长度 | 字段 | 类型 | 说明 |
|------|------|------|------|------|
| 0 | 1 | band_count | uint8 | 频段数量 (最大 10) |
| 1 | 2 | pregain | uint16 LE | 前级增益 |
| 3+ | 10×N | bands[N] | 见下 | 各频段参数 |

**每个频段 (10 字节)**:

| 偏移 | 长度 | 字段 | 类型 | 说明 |
|------|------|------|------|------|
| +0 | 2 | gain | uint16 LE | 频段增益 |
| +2 | 1 | reserved | uint8 | 保留 (填 0) |
| +3 | 4 | f0 | uint32 LE | 中心频率 (Hz) |
| +7 | 2 | Q | uint16 LE | Q 值 (×1000) |
| +9 | 1 | type | uint8 | 滤波器类型 |
| +10 | 1 | enable | uint8 | 频段开关 (0=关, 1=开) |

---

### 7.5 CMD_DELAY (0x13)

**方向**: 双向  
**Payload 长度**: 待定义

> 当前代码中已定义命令 ID 但未实现具体载荷格式。

---

### 7.6 CMD_GAIN (0x14)

**方向**: 双向  
**Payload 长度**: 待定义

> 当前代码中已定义命令 ID 但未实现具体载荷格式。

---

### 7.7 CMD_LOOPER (0x20)

**方向**: 双向  
**Payload 长度**: 15 字节

| 偏移 | 长度 | 字段 | 类型 | 说明 |
|------|------|------|------|------|
| 0 | 1 | loop_count | uint8 | 循环段数 |
| 1 | 1 | overdub_mode | uint8 | 叠录模式 |
| 2 | 1 | quantize | uint8 | 量化模式 |
| 3 | 1 | click_volume | uint8 | 节拍音量 (0~100) |
| 4 | 1 | tempo | uint8 | 速度 (BPM) |
| 5 | 1 | time_signature | uint8 | 拍号 |
| 6 | 2 | fade_time | uint16 LE | 淡入淡出时间 (ms) |
| 8 | 1 | segment_rec_source[0] | uint8 | 段0 录制源 |
| 9 | 1 | segment_rec_source[1] | uint8 | 段1 录制源 |
| 10 | 1 | segment_rec_source[2] | uint8 | 段2 录制源 |
| 11 | 1 | segment_rec_source[3] | uint8 | 段3 录制源 |
| 12 | 1 | export_mono_mix | uint8 | 导出单声道混音开关 |
| 13 | 2 | export_gain_pct | uint16 LE | 导出增益 (百分比) |

---

### 7.8 CMD_LOOPER_SEG_STATE (0x21)

**方向**: MCU→App (仅上报)  
**Payload 长度**: 12 字节

| 偏移 | 长度 | 字段 | 类型 | 说明 |
|------|------|------|------|------|
| 0 | 1 | seg0_state | uint8 | 段0 状态 |
| 1 | 1 | seg1_state | uint8 | 段1 状态 |
| 2 | 1 | seg2_state | uint8 | 段2 状态 |
| 3 | 1 | seg3_state | uint8 | 段3 状态 |
| 4 | 2 | seg0_length | uint16 LE | 段0 长度 (页数) |
| 6 | 2 | seg1_length | uint16 LE | 段1 长度 (页数) |
| 8 | 2 | seg2_length | uint16 LE | 段2 长度 (页数) |
| 10 | 2 | seg3_length | uint16 LE | 段3 长度 (页数) |

**段状态值**:

| 值 | 含义 |
|------|------|
| 0 | INACTIVE — 空闲，无录音数据 |
| 1 | RECORDING — 正在录制 |
| 2 | PLAYING — 正在播放 |
| 3 | STOPPED — 已停止，有录音数据 |

---

### 7.9 CMD_METRONOME (0x31)

**方向**: 双向  
**Payload 长度**: 5 字节

| 偏移 | 长度 | 字段 | 类型 | 说明 |
|------|------|------|------|------|
| 0 | 1 | tempo | uint8 | 速度 (BPM) |
| 1 | 1 | time_signature | uint8 | 拍号 |
| 2 | 1 | click_volume | uint8 | 节拍音量 (0~100) |
| 3 | 1 | overdub_mode | uint8 | 叠录模式 |
| 4 | 1 | quantize | uint8 | 量化模式 |

---

### 7.10 CMD_SYSTEM (0x32)

**方向**: 双向 (子类型区分)  
**Payload 格式**: `[sub_cmd, ...]`

#### 7.10.1 SUB_BATTERY (0x01)

**方向**: MCU→App  
**Payload 长度**: 2 字节

| 偏移 | 长度 | 字段 | 类型 | 范围 | 说明 |
|------|------|------|------|------|------|
| 0 | 1 | sub_cmd | uint8 | 0x01 | 子命令标识 |
| 1 | 1 | soc | uint8 | 0~100 | 电池电量百分比 |

#### 7.10.2 SUB_STATE (0x02)

**方向**: MCU→App  
**Payload 长度**: 2 字节

| 偏移 | 长度 | 字段 | 类型 | 说明 |
|------|------|------|------|------|
| 0 | 1 | sub_cmd | uint8 | 0x02 | 子命令标识 |
| 1 | 1 | state | uint8 | 见下 | 系统状态 |

**系统状态值**:

| 值 | 含义 |
|------|------|
| 0x00 | IDLE — 空闲态，无音频 I/O，低功耗模式 |
| 0x01 | NORMAL — 正常态，音频系统活跃 |
| 0x02 | TRANSFER — 数据传输态，WAV/OTA 大数据传输中，音频已静音 |

#### 7.10.3 SUB_LP_STATE (0x03)

**方向**: MCU→App  
**Payload 长度**: 2 字节

| 偏移 | 长度 | 字段 | 类型 | 说明 |
|------|------|------|------|------|
| 0 | 1 | sub_cmd | uint8 | 0x03 | 子命令标识 |
| 1 | 1 | enabled | uint8 | 0/1 | 自动低功耗启用状态 |

> App→MCU 控制通过文本 Shell 命令 `"lp 1"` / `"lp 0"` 实现，不走 AA55 协议。

#### 7.10.4 SUB_LP_TIMEOUT (0x04)

**方向**: MCU→App  
**Payload 长度**: 2 字节

| 偏移 | 长度 | 字段 | 类型 | 范围 | 说明 |
|------|------|------|------|------|------|
| 0 | 1 | sub_cmd | uint8 | 0x04 | 子命令标识 |
| 1 | 1 | timeout_min | uint8 | 1~60 | 空闲超时 (分钟) |

#### 7.10.5 SUB_PRODUCT_ID (0x05)

**方向**: MCU→App  
**Payload 长度**: 3 字节

| 偏移 | 长度 | 字段 | 类型 | 说明 |
|------|------|------|------|------|
| 0 | 1 | sub_cmd | uint8 | 0x05 | 子命令标识 |
| 1 | 2 | product_id | uint16 LE | 产品标识 | 

**产品 ID 定义**:

| 值 | 产品 |
|------|------|
| 0x0001 | BanBox 音效器 |

---

### 7.11 CMD_BATTERY_CALIB (0x33)

**方向**: 双向 (子命令区分)  
**Payload 格式**: `[sub_cmd, ...]`

#### 7.11.1 App→MCU 子命令

| 子命令 | 值 | Payload 长度 | 说明 |
|------|------|------|------|
| CALIB_CMD_START | 0x01 | 1 | 开始校准 |
| CALIB_CMD_STOP | 0x02 | 1 | 停止校准 |
| CALIB_CMD_STATUS | 0x03 | 1 | 查询状态 |
| CALIB_CMD_CLEAR | 0x04 | 1 | 清除校准数据 |

#### 7.11.2 MCU→App 子命令

| 子命令 | 值 | 说明 |
|------|------|------|
| CALIB_CMD_STATUS_RSP | 0x83 | 状态响应 (含放电曲线数据) |

#### 7.11.3 校准数据结构 (Flash 存储)

```c
typedef struct {
    uint16_t magic;                    // 0xBA77
    uint8_t  version;                  // 1
    uint8_t  valid_steps;              // 有效步数 (0~18)
    uint16_t v_shutdown_mv;            // 实际关机电压 (mV)
    uint16_t reserved;
    uint32_t step_duration_s[18];      // 每 0.1V 电压段的放电秒数
    uint32_t total_duration_s;         // 总放电秒数
    uint16_t crc;                      // CRC16 校验
} BattCalibData_t;
```

- 电压范围: 4.20V ~ 2.40V
- 步进: 0.10V (共 18 步)
- Flash 地址: 0x151000 (独立 4KB 扇区)

---

### 7.12 CMD_WAV_EXPORT (0x40)

**方向**: 双向 (子命令区分)  
**用途**: 通过 BLE 将 Looper 录音段导出为 WAV 文件

#### 7.12.1 子命令总表

| 子命令 | 值 | 方向 | 说明 |
|------|------|------|------|
| EXPORT_REQ | 0x01 | App→MCU | 导出请求 |
| EXPORT_START | 0x02 | MCU→App | 导出开始 (含 WAV 头) |
| DATA_PACKET | 0x03 | MCU→App | 数据包 |
| EXPORT_END | 0x04 | MCU→App | 导出完成 |
| CANCEL | 0x05 | App→MCU | 取消导出 |

#### 7.12.2 EXPORT_REQ (0x01) — App→MCU

**Payload 长度**: 3 字节

| 偏移 | 长度 | 字段 | 类型 | 说明 |
|------|------|------|------|------|
| 0 | 1 | sub_cmd | uint8 | 0x01 |
| 1 | 1 | segment_mask | uint8 | 段掩码 (bit0~3 对应 seg0~seg3) |
| 2 | 1 | output_channels | uint8 | 1=单声道, 2=立体声 |

**声道转换规则**:
- 录制段为立体声 → 导出单声道时取左声道
- 录制段为单声道 → 导出立体声时复制到两个声道
- 多段混音导出: 各段长度必须一致，否则返回 LEN_MISMATCH

#### 7.12.3 EXPORT_START (0x02) — MCU→App

**Payload 长度**: 53 字节

| 偏移 | 长度 | 字段 | 类型 | 说明 |
|------|------|------|------|------|
| 0 | 1 | sub_cmd | uint8 | 0x02 |
| 1 | 4 | total_packets | uint32 LE | 数据包总数 |
| 5 | 4 | total_data_bytes | uint32 LE | 音频数据总字节数 |
| 9 | 44 | wav_header | uint8[44] | 标准 WAV 文件头 (44 字节) |

#### 7.12.4 DATA_PACKET (0x03) — MCU→App

**Payload 长度**: 5 + pcm_len 字节 (pcm_len ≤ 188)

| 偏移 | 长度 | 字段 | 类型 | 说明 |
|------|------|------|------|------|
| 0 | 1 | sub_cmd | uint8 | 0x03 |
| 1 | 4 | packet_index | uint32 LE | 数据包序号 (从 0 开始) |
| 5 | ≤188 | pcm_data | uint8[] | PCM 音频数据 |

**PCM 数据对齐**:
- 每包最大 188 字节 (对齐到 4 字节，一个立体声采样 = 4 字节)
- 使用 `BleProto_SendOnce()` 发送 (不等 ACK)
- 每次调用 `LooperWavBle_ProcessTick()` 发送一包

#### 7.12.5 EXPORT_END (0x04) — MCU→App

**Payload 长度**: 2 字节

| 偏移 | 长度 | 字段 | 类型 | 说明 |
|------|------|------|------|------|
| 0 | 1 | sub_cmd | uint8 | 0x04 |
| 1 | 1 | result | uint8 | 结果码 |

**结果码**:

| 值 | 含义 |
|------|------|
| 0 | OK — 导出成功 |
| 1 | ERROR — 导出错误 |
| 2 | CANCELLED — 被用户取消 |
| 3 | BUSY — 设备忙 (正在导出) |
| 4 | NO_DATA — 无录音数据 |
| 5 | LEN_MISMATCH — 多段长度不一致 |

#### 7.12.6 CANCEL (0x05) — App→MCU

**Payload 长度**: 1 字节

| 偏移 | 长度 | 字段 | 类型 | 说明 |
|------|------|------|------|------|
| 0 | 1 | sub_cmd | uint8 | 0x05 |

#### 7.12.7 导出流程时序

```
App                                    MCU
 |--- EXPORT_REQ -------------------->|  (segment_mask, channels)
 |                                    |  (准备数据，生成 WAV 头)
 |<-- EXPORT_START -------------------|  (total_packets, total_bytes, WAV_header)
 |<-- DATA_PACKET (index=0) ----------|
 |<-- DATA_PACKET (index=1) ----------|
 |<-- ...                            |
 |<-- DATA_PACKET (index=N-1) --------|
 |<-- EXPORT_END ---------------------|  (result=0)
 
 (或 App 取消)
 |--- CANCEL ------------------------>|  
 |<-- EXPORT_END ---------------------|  (result=2)
```

---

## 8. 音源下载协议 (Soundbank DL)

> 独立于 AA55 协议的二级协议，用于音源数据批量下载到 Flash。

### 8.1 数据包格式 (Host→Device)

```
+--------+--------+--------+---------+---------+-----------+---------+---------+
| 0xAA   | 0x55   | CMD    | SEQ_L   | SEQ_H   | LEN_L LEN_H | DATA[N] | CRC_L CRC_H |
| 1B     | 1B     | 1B     | 1B      | 1B      | 2B        | 0~4096  | 2B      |
+--------+--------+--------+---------+---------+-----------+---------+---------+

总长 = 7 + N + 2 字节
```

### 8.2 响应包格式 (Device→Host)

```
+--------+--------+--------+---------+---------+--------+---------+---------+
| 0xAA   | 0x55   | RSP    | SEQ_L   | SEQ_H   | STATUS | CRC_L   | CRC_H   |
| 1B     | 1B     | 1B     | 1B      | 1B      | 1B     | 1B      | 1B      |
+--------+--------+--------+---------+---------+--------+---------+---------+

总长 = 8 字节
```

### 8.3 命令码

| 命令 | 值 | 方向 | 说明 |
|------|------|------|------|
| DL_CMD_DATA | 0x01 | Host→Device | 数据包 |
| DL_CMD_END | 0x02 | Host→Device | 传输结束 |
| DL_CMD_QUERY | 0x03 | Host→Device | 查询状态 |
| DL_CMD_ABORT | 0x04 | Host→Device | 中止传输 |

### 8.4 响应码

| 响应 | 值 | 方向 | 说明 |
|------|------|------|------|
| DL_RSP_ACK | 0x81 | Device→Host | 确认 |
| DL_RSP_NAK | 0x82 | Device→Host | 否认 |
| DL_RSP_STATUS | 0x83 | Device→Host | 状态响应 |
| DL_RSP_READY | 0x84 | Device→Host | 准备就绪 |

### 8.5 状态码

| 状态 | 值 | 说明 |
|------|------|------|
| DL_STATUS_OK | 0x00 | 成功 |
| DL_STATUS_CRC_ERR | 0x01 | CRC 校验失败 |
| DL_STATUS_FLASH_ERR | 0x02 | Flash 写入/擦除失败 |
| DL_STATUS_SEQ_ERR | 0x03 | 序列号不连续 |
| DL_STATUS_OVERFLOW | 0x04 | 数据溢出 (超出存储空间) |
| DL_STATUS_TIMEOUT | 0x05 | 超时 |
| DL_STATUS_ABORT | 0x06 | 已中止 |
| DL_STATUS_BUSY | 0x07 | 设备忙 |

### 8.6 协议参数

| 参数 | 值 |
|------|------|
| 单包最大数据量 | 4096 字节 (1 个 Flash 扇区) |
| 接收超时 | 5000 ms |
| 总下载超时 | 300000 ms (5 分钟) |
| CRC16 | CCITT/XMODEM, 多项式 0x1021, 初始值 0xFFFF |

---

## 9. 旧版 ABBA 协议 (已废弃)

> 早期协议，已被 AA55 协议取代。保留此处仅作历史参考。

### 9.1 帧格式

```
[0xAB] [0xBA] [ctrl_type] [ctrl_word] [data_len] [data...] [0xCD]
```

### 9.2 控制类型

| ctrl_type | 值 | 说明 |
|-----------|------|------|
| HARDWARE_EVENT | 0x00 | 硬件控制 |
| EFFECT_EVENT | 0x01 | 音效控制 |

### 9.3 硬件命令 (HARDWARE_EVENT)

| ctrl_word | 值 | 说明 |
|-----------|------|------|
| DAC_VOLUME | 0 | DAC 音量 |
| MIC_VOLUME | 1 | MIC 音量 |
| LINE_IN_VOLUME | 2 | Line-In 音量 |
| PLAY_SELECT | 3 | 播放选择 |
| DEBUG_SETTING | 4 | 调试设置 |

### 9.4 音效命令 (EFFECT_EVENT)

| ctrl_word | 值 | 说明 |
|-----------|------|------|
| REVERB_STD | 0 | 标准混响 |
| REVERB_PLATE | 1 | 板式混响 |
| DRC | 2 | DRC 压缩 |

---

## 10. 附录

### 10.1 多字节整数字节序

除非特别说明，所有多字节整数使用 **小端序 (Little-Endian)**，即低字节在前。

### 10.2 BLE 传输限制

| 参数 | 值 |
|------|------|
| 协商 MTU | 250 字节 |
| 单次 GattServerNotify 最大 | 200 字节 |
| AA55 帧最大长度 | 206 字节 (4 + 200 + 2) |
| WAV 导出每包 PCM 数据 | 188 字节 |

### 10.3 Shell 命令通道

除了 AA55 二进制协议，App 还可以通过 AB01 写入文本 Shell 命令。MCU 根据数据前两个字节判断：
- `0xAA 0x55` → 二进制协议帧
- 其他 → 文本 Shell 命令 (如 `"lp 1"`, `"vol 50"` 等)

### 10.4 线程安全注意事项

1. `send_frame()` 使用 static 缓冲区，通过 `s_frame_mutex` 互斥量保护
2. 同步任务 (优先级 3) 可能抢占主循环，ACK 在同步期间排队延迟发送
3. 同步结束后有 300ms 冷却期，等待 BLE 栈恢复后再排空积压 ACK
4. Shell 命令在同步期间缓冲，同步结束后处理

### 10.5 相关源文件索引

**MCU 端 (C)**:

| 文件 | 说明 |
|------|------|
| `BanBox/src/banux/02_device_drivers/bluetooth/inc/ble_protocol.h` | 协议核心定义 |
| `BanBox/src/banux/02_device_drivers/bluetooth/src/ble_protocol.c` | 协议核心实现 |
| `BanBox/src/banux/02_device_drivers/bluetooth/src/ble_app_func.c` | GATT Profile 定义 |
| `BanBox/src/banux/02_device_drivers/bluetooth/src/ble_app_callback.c` | BLE 连接事件回调 |
| `BanBox/src/banux/04_shell_commands/shell_io_ble.c` | Shell BLE 适配层 |
| `BanBox/src/banux/05_component/audio_looper/looper_wav_ble_export.h` | WAV 导出协议定义 |
| `BanBox/src/banux/05_component/audio_looper/looper_wav_ble_export.c` | WAV 导出实现 |
| `BanBox/src/banux/05_component/bangtsynth/01_hal/bg_soundbank_dl_protocol.h` | 音源下载协议定义 |
| `BanBox/src/banux/02_device_drivers/power_mgr/battery_calib.h` | 电池校准定义 |
| `BanBox/src/banux/05_component/sys_param/sys_param.h` | 系统参数结构体 |
| `BanBox/src/banux/02_device_drivers/bluetooth/inc/ble_process.h` | 旧版 ABBA 协议 (已废弃) |

**App 端 (Java)**:

| 文件 | 说明 |
|------|------|
| `app/src/main/java/com/example/myapplication/BleProtocol.java` | 协议核心定义 (帧编解码) |
| `app/src/main/java/com/example/myapplication/BluetoothHelper.java` | BLE 连接管理 |
| `app/src/main/java/com/example/myapplication/BleParamCache.java` | 参数缓存与解析 |
| `app/src/main/java/com/example/myapplication/WavBleReceiver.java` | WAV BLE 接收与组装 |
| `app/src/main/java/com/example/myapplication/BleFileTransfer.java` | 音源文件传输 |
