# BanBox USB CDC Shell 协议文档

> 版本: 1.0  
> 最后更新: 2026-05-26  
> 适用产品: BanBox 音效器 / BanDataHub 数据采集器

---

## 目录

1. [概述](#1-概述)
2. [物理层与传输](#2-物理层与传输)
3. [命令格式](#3-命令格式)
4. [Shell 框架架构](#4-shell-框架架构)
5. [命令参考 — 系统类](#5-命令参考--系统类)
6. [命令参考 — 硬件类](#6-命令参考--硬件类)
7. [命令参考 — 音频/音效类](#7-命令参考--音频音效类)
8. [命令参考 — Looper 类](#8-命令参考--looper-类)
9. [命令参考 — 参数管理类](#9-命令参考--参数管理类)
10. [命令参考 — 文件系统类](#10-命令参考--文件系统类)
11. [命令参考 — 调试类](#11-命令参考--调试类)
12. [命令参考 — 其他](#12-命令参考--其他)
13. [二进制数据传输协议](#13-二进制数据传输协议)
14. [附录](#14-附录)

---

## 1. 概述

BanBox 系列设备通过 USB CDC (虚拟串口) 提供交互式命令行 Shell，用于调试、配置和测试。Shell 基于 **BG Shell v2.0** 框架，采用模块化命令注册，支持短选项/长选项、命令历史、LCD 控制台输出。

### 特性

- **交互式命令行**: 支持命令编辑、退格、Ctrl+C 取消、上下箭头历史
- **模块化命令**: 每个功能模块独立注册，支持短选项 (`-x`) 和长选项 (`--xxx`)
- **双通道 IO**: USB CDC 和 BLE SPP 共享同一命令集，IO Manager 自动切换
- **LCD 控制台**: Shell 输出可同步显示到 LCD，支持 ANSI 颜色解析
- **二进制传输**: 支持 `Shell_WriteRaw` / `Shell_RecvRaw` 进行二进制数据传输 (音源下载等)
- **命令历史**: 10 条历史记录，上下箭头翻阅

### 连接参数

| 参数 | 值 |
|------|------|
| 接口 | USB CDC (虚拟串口) |
| 波特率 | 任意 (USB CDC 不依赖波特率) |
| 数据位 | 8 |
| 停止位 | 1 |
| 校验 | 无 |
| 流控 | 无 |
| 换行 | CR+LF (`\r\n`) |
| 提示符 | `$ ` |

---

## 2. 物理层与传输

### 2.1 USB CDC 接口

设备通过 USB 枚举为复合设备 (CDC + MSC)。CDC 接口提供虚拟串口，Shell 通过此接口收发文本命令。

**端点配置**:

| 端点 | 方向 | 类型 | 用途 |
|------|------|------|------|
| EP1 (0x81) | IN | Interrupt | CDC 状态通知 |
| EP2 (0x82) | IN | Bulk | CDC 数据输出 (设备→主机) |
| EP3 (0x03) | OUT | Bulk | CDC 数据输入 (主机→设备) |

### 2.2 IO 抽象层

Shell 通过 `ShellIO_t` 接口与传输层解耦：

```c
typedef uint16_t (*ShellIO_Send_t)(uint8_t *data, uint16_t len);
typedef uint16_t (*ShellIO_Recv_t)(uint8_t *data, uint16_t maxLen);
typedef uint16_t (*ShellIO_Available_t)(void);

typedef struct {
    const char         *name;       // "CDC", "BLE", "UART"
    ShellIO_Send_t      send;
    ShellIO_Recv_t      recv;
    ShellIO_Available_t available;
} ShellIO_t;
```

### 2.3 IO Manager

IO Manager 自动在 CDC 和 BLE 之间切换，提供互斥锁：

| 操作 | 说明 |
|------|------|
| 自动切换 | 有数据到达的通道自动激活 |
| 互斥锁 | `ShellIOManager_TryLock()` / `Unlock()` |
| 超时 | 长时间无活动后释放通道 |

### 2.4 输出函数

| 函数 | 说明 |
|------|------|
| `Shell_Print(str)` | 输出字符串到 IO + LCD 控制台 |
| `Shell_Printf(fmt, ...)` | 格式化输出 (256 字节缓冲区) |
| `Shell_WriteRaw(data, len)` | 原始二进制输出，绕过字符串处理 |
| `Shell_NewLine()` | 输出 `\r\n` |

### 2.5 输入处理

| 按键 | 动作 |
|------|------|
| 可打印字符 (0x20~0x7E) | 追加到命令行，回显 |
| Enter (`\r` 或 `\n`) | 执行命令，保存历史 |
| Backspace (`\b` 或 0x7F) | 删除末尾字符，发送 `\b \b` |
| Ctrl+C (0x03) | 取消当前行，显示新提示符 |
| ESC[A (上箭头) | 翻阅更早的历史命令 |
| ESC[B (下箭头) | 翻阅更新的历史命令 |

---

## 3. 命令格式

### 3.1 语法

```
$ <module> [-<short_opt> | --<long_opt>] [args...]
```

### 3.2 示例

```
$ help -a                          # 列出所有模块
$ sys -i                           # 显示系统信息
$ audio -g1 80                     # 设置吉他1音量为80
$ looper -r 0                      # 开始录制段0
$ effect set 0 room_size 50        # 设置混响房间大小
$ ls                               # 列出当前目录
$ sd -ls                           # 列出SD卡目录
$ dbg -d 0x20000000 64             # 内存转储
```

### 3.3 默认选项

模块可以定义一个默认选项 (opt 字段为空字符串 `""`)，当只输入模块名不带选项时自动调用：

```
$ ls              # 等同于 ls 的默认选项 (列出目录)
$ psram           # 等同于 psram 的默认选项 (显示内存)
$ echo hello      # 等同于 echo 的默认选项 (回显文本)
```

### 3.4 帮助系统

```
$ help -a          # 列出所有模块
$ help -m audio    # 显示 audio 模块帮助
$ help -l          # 按分类列出模块
$ help -v          # 显示版本
$ help -h          # 显示命令历史
$ help -i          # 显示当前 IO 通道
```

---

## 4. Shell 框架架构

### 4.1 数据结构

```c
/* 选项定义 */
typedef struct {
    const char     *opt;        // 短选项 (如 "v")，"" 表示默认
    const char     *longOpt;    // 长选项 (如 "volume")，可 NULL
    const char     *args;       // 参数描述 (如 "<0-100>")
    const char     *help;       // 帮助信息
    OptHandler_t    handler;    // 处理函数: int (*)(int argc, char *argv[])
} ShellOpt_t;

/* 模块定义 */
typedef struct {
    const char         *name;       // 模块名 (如 "audio")
    const char         *desc;       // 模块描述
    ModCategory_t       category;   // 分类
    const ShellOpt_t   *options;    // 选项数组 (NULL 终止)
    uint8_t             optCount;   // 选项数量
} ShellModule_t;
```

### 4.2 模块分类

| 分类 | 值 | 说明 |
|------|------|------|
| MOD_CAT_SYSTEM | 0 | 系统信息 |
| MOD_CAT_HARDWARE | 1 | 硬件控制 |
| MOD_CAT_AUDIO | 2 | 音频效果 |
| MOD_CAT_PARAM | 3 | 功能参数 |
| MOD_CAT_DEBUG | 4 | 调试工具 |

### 4.3 注册宏

```c
/* 定义选项 */
#define OPT(s, l, a, h, fn)     { s, l, a, h, fn }
#define OPT_END()               { NULL, NULL, NULL, NULL, NULL }

/* 定义模块 */
#define DEFINE_MODULE(n, d, cat, opts) \
    static const ShellModule_t _mod_##n = { #n, d, cat, opts, OPT_COUNT(opts) }

/* 注册模块 */
#define REGISTER_MODULE(n)      Shell_RegisterModule(&_mod_##n)
```

### 4.4 命令解析流程

```
输入: "audio -g1 80"
  ↓
1. 分词: argv = ["audio", "-g1", "80"], argc = 3
  ↓
2. 查找模块: argv[0] = "audio" → 找到 audio 模块
  ↓
3. 查找选项: argv[1] = "-g1" → 找到短选项 "g1"
  ↓
4. 调用处理函数: handler(argc-2, &argv[2]) = handler(1, ["80"])
```

---

## 5. 命令参考 — 系统类

### 5.1 `help` — 帮助系统 (内置)

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| `-a` | `--all` | | 列出所有模块 |
| `-m` | `--module` | `<name>` | 显示指定模块帮助 |
| `-l` | `--list` | | 按分类列出模块 |
| `-v` | `--version` | | 显示版本 |
| `-c` | `--clear` | | 清屏 |
| `-i` | `--io` | | 显示当前 IO 通道 |
| `-h` | `--history` | | 显示命令历史 |

### 5.2 `sys` — 系统信息

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| `-i` | `--info` | | 显示系统信息 |
| `-m` | `--mem` | | 显示内存状态 |
| `-t` | `--tasks` | | 列出运行中的任务 |
| `-u` | `--uptime` | | 显示运行时间 |
| `-b` | `--reboot` | | 重启系统 |
| `-f` | `--factory` | | 恢复出厂设置 |
| `-o` | `--io` | `[cmd]` | IO 控制 (cdc/ble/lock/unlock) |
| `-c` | `--console` | `[cmd]` | LCD 控制台 (on/off/clear) |
| `-d` | `--dbglcd` | `[cmd]` | DBG 输出到 LCD (on/off) |
| `-r` | `--rotate_distr` | `<0-3>` | 屏幕旋转 (0/1/2/3 = 0°/90°/180°/270°) |
| `-s` | `--chipid` | | 显示芯片唯一 ID |

**示例**:
```
$ sys -i           # 系统信息
$ sys -t           # 任务列表
$ sys -o cdc       # 切换到 CDC 通道
$ sys -c on        # 开启 LCD 控制台
```

### 5.3 `lp` — 自动低功耗

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| (默认) | | `[0\|1\|on\|off]` | 低功耗开关控制 |
| `-t` | `--timeout` | `<min>` | 设置空闲超时 (1~60 分钟) |

**示例**:
```
$ lp on            # 开启自动低功耗
$ lp -t 5          # 设置 5 分钟超时
```

### 5.4 `mode` — 设备模式控制

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| (默认) | | `[subcmd]` | 设备模式控制 |

子命令: `main` (主机), `secondary` (从机), `help`

---

## 6. 命令参考 — 硬件类

### 6.1 `gpio` — GPIO 控制

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| `-r` | `--read` | `<pin>` | 读取 GPIO |
| `-w` | `--write` | `<pin> <0\|1>` | 写入 GPIO |
| `-t` | `--toggle` | `<pin>` | 翻转 GPIO |

### 6.2 `lcd` — LCD 控制

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| `-o` | `--on` | | 开启 LCD |
| `-f` | `--off` | | 关闭 LCD |
| `-b` | `--bl` | `<0-100>` | 设置对比度 |
| `-c` | `--color` | `<0xRRGG>` | 设置背景色 |
| `-S` | `--save` | | 保存 LCD 参数 |

### 6.3 `led` — LED 控制

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| `-o` | `--on` | | LED 开 |
| `-f` | `--off` | | LED 关 |
| `-b` | `--blink` | `[ms]` | 闪烁 (默认 500ms) |

### 6.4 `battery` — 电池状态

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| `-r` | `--raw_bat` | | 显示原始 ADC 值 |
| `-v` | `--bat_val` | | 显示电量百分比 |

### 6.5 `flash` — Flash 存储

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| `-i` | `--info` | | 显示 Flash 信息 |
| `-s` | `--status` | | 显示 Flash 状态 |
| `-t` | `--test` | `[dev]` | 测试设备 (0 或 1) |
| `-r` | `--read` | `<off> <len>` | 从 Looper 读取 |
| `-e` | `--erase` | `<offset>` | 擦除 Looper 扇区 |
| `-f` | `--format` | `[dev]` | 格式化设备 |

### 6.6 `psram` — PSRAM 内存

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| (默认) | | | 显示 PSRAM 堆内存使用 |

### 6.7 `bt` — 蓝牙控制

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| `-s` | `--state` | | 显示 BT 状态 |
| `-n` | `--name` | `[name]` | 获取/设置 BT 名称 |
| `-v` | `--a2dpvol` | `<0-100>` | A2DP 音量 |
| `-S` | `--save` | | 保存 BT 参数 |

### 6.8 `ble` — BLE 控制

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| `-s` | `--state` | | 显示 BLE 状态 |

---

## 7. 命令参考 — 音频/音效类

### 7.1 `audio` — 音频控制

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| `-g1` | `--guitar1` | `<0-100>` | 吉他1 音量 |
| `-g2` | `--guitar2` | `<0-100>` | 吉他2 音量 |
| `-m1` | `--mic1` | `<0-100>` | MIC1 音量 |
| `-m2` | `--mic2` | `<0-100>` | MIC2 音量 |
| `-o` | `--output` | `<0-100>` | 主输出音量 |
| `-m` | `--mute` | `<0\|1>` | 静音开关 |
| `-S` | `--save` | | 保存音频参数 |

### 7.2 `effect` — 音效参数控制

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| (默认) | | `[subcmd] [args]` | 音效参数控制 |

**子命令**:

| 子命令 | 参数 | 说明 |
|--------|------|------|
| `list` | | 列出所有音效节点 |
| `info <id>` | | 显示节点详细信息 |
| `set <id> <param> <val>` | | 设置参数 |
| `get <id> <param>` | | 获取参数 |
| `enable <id> [on\|off]` | | 启用/禁用节点 |
| `query <id>` | | 查询节点参数 (二进制，供 App 使用) |
| `help` | | 显示帮助 |

**音效节点 ID**:

| ID | 名称 | 说明 |
|------|------|------|
| 0 | reverb | 标准混响 |
| 1 | drc | DRC 压缩器 |
| 2 | eq | 均衡器 |
| 3 | expander | 扩展器 |
| 4 | eq_guitar_l | 吉他左声道 EQ |
| 5 | eq_guitar_r | 吉他右声道 EQ |
| 6 | eq_mic_l | MIC 左声道 EQ |
| 7 | eq_mic_r | MIC 右声道 EQ |
| 8 | echo | 回声 |
| 9 | howling | 啸叫抑制 |
| 10 | 3d | 3D 音效 |
| 11 | vbass | 虚拟低音 |
| 12 | plate_reverb | 板式混响 |
| 13 | music_drc | 音乐 DRC |
| 14 | music_eq | 音乐 EQ |

**示例**:
```
$ effect list                    # 列出所有音效
$ effect info 0                  # 混响节点信息
$ effect set 0 room_size 50      # 设置混响房间大小
$ effect enable 0 on             # 启用混响
```

### 7.3 `graph` — 音效图控制

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| (默认) | | `[subcmd] [args]` | 音效图控制 |

**子命令**: `list`, `info`, `preset`, `set`, `get`, `enable`, `disable`, `snapshot`, `restore`, `help`

### 7.4 `chain` — 音效链 (多源 DAG)

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| `-l` | `--graph-list` | | 列出所有图 |
| `-c` | `--graph-create` | `<name>` | 创建图 |
| `-d` | `--graph-delete` | `<name>` | 删除图 |
| `-s` | `--graph-select` | `<hp\|spk> <name>` | 选择 HP/SPK 输出图 |
| `-a` | `--graph-apply` | `<name>` | 应用图到 EffectGraph |
| `-v` | `--graph-save` | `<name>` | 保存 EffectGraph 到链 |
| `-u` | `--graph-use` | `<name>` | 切换工作图 |
| `-w` | `--graph-show` | `[id]` | 显示图拓扑 |
| `-n` | `--node-add` | `<type> <sub>` | 添加节点 |
| `-r` | `--node-del` | `<id>` | 删除节点 |
| `-e` | `--edge-add` | `<from> <to>` | 添加边 |
| `-x` | `--edge-del` | `<from> <to>` | 删除边 |
| `-m` | `--mode` | `<0-2>` | 输出模式 (0=Auto,1=HP,2=SPK) |
| `-S` | `--save` | | 保存 (验证) |

### 7.5 `fx` — 快速音效参数访问

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| (默认) | | `<id> [param] [val]` | 快速音效参数读写 |

### 7.6 `metro` — 节拍器

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| (默认) | | `[subcmd] [args]` | 节拍器控制 |

**子命令**:

| 子命令 | 参数 | 说明 |
|--------|------|------|
| `on` | | 开启节拍器 |
| `off` | | 关闭节拍器 |
| `toggle` | | 切换节拍器 |
| `bpm` | `<60-200>` | 设置/查询 BPM |
| `beats` | `<2-8>` | 设置/查询拍号 |
| `vol` | `<0-100>` | 设置/查询音量 |
| `freq` | `<down> <reg>` | 设置频率 |
| `dur` | `<ms>` | 设置持续时间 |
| `status` | | 显示状态 |
| `help` | | 显示帮助 |

---

## 8. 命令参考 — Looper 类

### 8.1 `looper` — 音频 Looper

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| `-i` | `--init` | `[0\|1]` | 初始化 (0=NOR, 1=NAND) |
| `-s` | `--status` | | 显示 Looper 状态 |
| `-r` | `--record` | `[seg]` | 开始录制段 |
| `-p` | `--play` | `[seg]` | 播放段 |
| `-t` | `--stop` | `[seg]` | 停止段 |
| `-c` | `--clear` | `[seg]` | 清除段 (无参数=全部+擦除) |
| `-R` | `--reset` | | 重置 Looper + 擦除 Flash |
| `-e` | `--erase` | | Flash 全片擦除 (异步) |
| `-m` | `--mode` | `[song\|free]` | 获取/设置循环模式 |
| `-M` | `--metro` | `<cmd> [val]` | 节拍器控制 |
| `-x` | `--export-param` | `[mono_mix gain_pct]` | 导出设置 (单声道混音, 增益%) |
| `-q` | `--query` | | 查询 Looper 参数 (二进制，供 App) |
| `-V` | `--vol` | `[seg] [0-100]` | 段音量 |
| `-src` | `--source` | `<seg> [0-4]` | 录制源 (0=MIC_L..4=ALL_MIX) |
| `-T` | `--trim` | `<seg> [start end]` | 裁剪点 (页数, 0=完整) |
| `-cfg` | `--cfg` | `<seg> autoplay <0\|1>` | 段配置 |
| `-F` | `--flash` | `[clean\|used]` | Flash 初始化状态 |
| `-I` | `--init-seg` | `<seg> <sec>` | 部分擦除初始化段 |
| `-C` | `--chain` | `<stop> <start>\|cancel` | 链式播放 (固件定时) |
| `-J` | `--join` | `<start>\|cancel` | 接续播放 (固件定时) |
| `-W` | `--wf` | `[seg]` | 切换段停止前等待完成 |
| `-SR` | `--sync-rec` | `<trig> <rec>\|cancel` | 同步录制 (固件定时) |
| `-Si` | `--init-s` | | 初始化存储层 |
| `-Ss` | `--info-s` | | 显示存储信息 |
| `-Sb` | `--bench-s` | | 存储基准测试 |
| `-So` | `--overdub-s` | | 存储叠录测试 |

**录制源定义**:

| 值 | 名称 | 说明 |
|------|------|------|
| 0 | MIC_L | MIC 左声道 |
| 1 | MIC_R | MIC 右声道 |
| 2 | GUITAR_L | 吉他左声道 |
| 3 | GUITAR_R | 吉他右声道 |
| 4 | ALL_MIX | 全部混音 |

### 8.2 `wav` — WAV 文件导出 (SD 卡)

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| (默认) | | `<subcmd>` | WAV 导出 |

子命令: `export`, `list`, `delete`, `info`

### 8.3 `wav_ble` — WAV BLE 导出

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| (默认) | | `<subcmd>` | BLE WAV 导出 |

子命令: `export`, `status`, `cancel`

### 8.4 `drum` — 鼓机

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| `-p` | `--play` | `[loop]\|stop\|status` | 播放/停止/状态 |
| `-b` | `--bpm` | `[40-240]` | BPM |
| `-v` | `--volume` | `[0-100]` | 音量 |
| `-e` | `--edit` | `<step> <trk> <0\|1>` | 编辑步进 (step=0-15, trk=0-7) |
| `-s` | `--save` | `[slot]` | 保存到 Flash |
| `-l` | `--load` | `[slot]` | 从 Flash 加载 |
| `-P` | `--preset` | `<0-3>` | 预设 (Rock/Pop/Funk/Latin) |
| `-c` | `--clear` | | 清除所有步进 |
| `-d` | `--display` | | 显示节奏网格 |
| `-D` | `--download` | `<size>` | 下载鼓音色库 |
| `-q` | `--query` | | 查询状态 (JSON) |

---

## 9. 命令参考 — 参数管理类

### 9.1 `param` — 参数管理

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| `-l` | `--load` | | 从 Flash 加载参数 |
| `-s` | `--save` | `[module]` | 保存参数到 Flash |
| `-d` | `--default` | | 恢复默认参数 |
| `-p` | `--print` | `[module]` | 打印参数 (sys/audio/looper/bt/lcd) |
| `-i` | `--info` | | 参数系统信息 |
| `-q` | `--query` | `<target>` | 二进制格式查询 (system/volume/looper/bluetooth/lcd/effect/metronome) |
| `-e` | `--erase` | | 擦除参数扇区 (危险!) |
| `-t` | `--test` | | 测试 Flash 保存/加载 |

### 9.2 `calib` — 电池校准

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| `-s` | `--start` | | 开始放电曲线校准 |
| `-t` | `--stop` | | 停止校准 (保留已记录数据) |
| `-q` | `--query` | | 查询校准状态和当前 SOC |
| `-c` | `--clear` | | 清除保存数据，恢复默认 |
| `-i` | `--info` | | 显示校准系统信息 |

### 9.3 `sb` — 音源库管理

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| `-d` | `--download` | `<size>` | 通过数据包下载音源 |
| `-i` | `--info` | | 显示音源库和存储信息 |
| `-e` | `--erase` | | 擦除音源存储 |
| `-v` | `--verify` | | 验证音源数据完整性 |
| `-r` | `--read` | `<off> [len]` | 十六进制转储存储数据 |
| `-l` | `--load` | `[offset]` | 从存储加载音源 |
| `-t` | `--test` | `<note> [vel] [dur] [prog]` | 播放测试音符 (直接 DAC) |
| `-m` | `--midi` | `<note> [vel] [dur] [prog] [ch]` | 通过 MIDI+Graph 测试 |
| `-p` | `--play` | `[bpm] [bars]\|stop` | 鼓音序器 |
| `-g` | `--graph` | `[dur]` | 测试音效图路径 (500Hz 音调) |
| `-V` | `--volume` | `[0-100]` | 合成器音量 |

---

## 10. 命令参考 — 文件系统类

### 10.1 `ls` — 列出目录

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| (默认) | | `[path]` | 列出目录内容 |

### 10.2 `pwd` — 当前目录

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| (默认) | | | 显示当前工作目录 |

### 10.3 `cd` — 切换目录

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| (默认) | | `[path]` | 切换工作目录 |

### 10.4 `cat` — 显示文件

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| (默认) | | `<file>` | 显示文件内容 |

### 10.5 `echo` — 写入文件

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| (默认) | | `<param> <value>` | 写入参数值 |

### 10.6 `tree` — 目录树

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| (默认) | | | 显示驱动器树 |

### 10.7 `sd` — FAT32 文件系统 (SD 卡)

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| `-ls` | `--list` | | 列出当前目录 |
| `-cd` | `--cd` | `<dir>` | 切换目录 |
| `-pwd` | `--pwd` | | 显示当前目录 |
| `-cat` | `--cat` | `<file>` | 显示文件内容 |
| `-write` | `--write` | `<file> <data>` | 写入数据到文件 |
| `-rm` | `--remove` | `<file>` | 删除文件 |
| `-mkdir` | `--mkdir` | `<dir>` | 创建目录 |
| `-rmdir` | `--rmdir` | `<dir>` | 删除目录 |
| `-rename` | `--rename` | `<old> <new>` | 重命名 |
| `-info` | `--info` | | 显示文件系统信息 |
| `-diag` | `--diag` | | 诊断 FAT32 初始化 |

---

## 11. 命令参考 — 调试类

### 11.1 `dbg` — 调试工具

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| `-e` | `--echo` | `<text...>` | 回显文本 |
| `-d` | `--dump` | `<addr> <len>` | 内存转储 (十六进制) |
| `-p` | `--poke` | `<addr> <val>` | 写入内存 |
| `-k` | `--peek` | `<addr>` | 读取内存 |

**示例**:
```
$ dbg -d 0x20000000 64       # 转储 64 字节内存
$ dbg -p 0x20000000 0x55     # 写入 0x55 到地址
$ dbg -k 0x20000000          # 读取一个字节
```

### 11.2 `drivers` — 驱动列表

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| (默认) | | | 列出所有注册的驱动 |

### 11.3 `ui` — UI 系统控制 (调试)

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| `-s` | `--state` | `<state>` | 设置 UI 状态 (boot/idle/menu/looper/settings) |
| `-g` | `--get` | | 获取当前 UI 状态 |
| `-p` | `--popup` | `[title] <msg> [ms]` | 显示弹窗 |
| `-c` | `--close` | | 关闭弹窗 |
| `-r` | `--refresh` | | 刷新 UI |
| `-k` | `--keys` | | 显示按键状态 |
| `-b` | `--battery` | `<0-100>` | 设置电量显示 |
| `-t` | `--bt` | `<0-4>` | 设置蓝牙状态显示 |
| `-v` | `--volume` | `<0-100>` | 设置音量显示 |
| `-u` | `--update` | | 更新状态栏 |
| `-q` | `--query` | | 查询 UI 状态 (JSON) |
| `-d` | `--debug` | `<on\|off>` | 开启/关闭调试模式 |

---

## 12. 命令参考 — 其他

### 12.1 `ble_send` — BLE 发送

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| (默认) | | `<string>` | 通过 BLE 发送字符串 (连接时) |

### 12.2 `upg` — 固件升级

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| (默认) | | | 进入固件升级模式 (SDK Flash Boot) |

### 12.3 `remind` — 提示音

| 短选项 | 长选项 | 参数 | 说明 |
|--------|--------|------|------|
| `-l` | `--list` | | 列出所有提示音 |
| `-p` | `--play` | `<id>` | 播放指定提示音 |
| `-n` | `--on` | | 播放开机音 (id=0) |
| `-f` | `--off` | | 播放关机音 (id=1) |

---

## 13. 二进制数据传输协议

Shell 除了文本命令外，还支持通过 `Shell_WriteRaw` / `Shell_RecvRaw` 进行二进制数据传输。当前用于 **音源下载协议**。

### 13.1 音源下载流程

```
Host (PC/App)                     Device (MCU)
  |--- "sb -d <size>\r\n" ------>|  (文本命令触发下载模式)
  |                              |
  |--- AA55 数据包 ------------->|  (二进制数据包)
  |<-- AA55 响应包 --------------|
  |--- AA55 数据包 ------------->|
  |<-- AA55 响应包 --------------|
  |--- ...                      |
  |--- AA55 END 包 ------------>|
  |<-- AA55 响应包 --------------|
```

### 13.2 数据包格式 (Host→Device)

```
+--------+--------+--------+---------+---------+-----------+---------+---------+
| 0xAA   | 0x55   | CMD    | SEQ_L   | SEQ_H   | LEN_L LEN_H | DATA[N] | CRC_L CRC_H |
| 1B     | 1B     | 1B     | 1B      | 1B      | 2B        | 0~4096  | 2B      |
+--------+--------+--------+---------+---------+-----------+---------+---------+
```

### 13.3 响应包格式 (Device→Host)

```
+--------+--------+--------+---------+---------+--------+---------+---------+
| 0xAA   | 0x55   | RSP    | SEQ_L   | SEQ_H   | STATUS | CRC_L   | CRC_H   |
| 1B     | 1B     | 1B     | 1B      | 1B      | 1B     | 1B      | 1B      |
+--------+--------+--------+---------+---------+--------+---------+---------+
```

> 详细协议定义请参考 [BanBox BLE 协议文档](BanBox_BLE_Protocol.md) 第 8 节。

### 13.4 二进制查询命令

部分命令支持 `-q` / `--query` 选项，以二进制格式返回参数（供 App 使用，而非人类阅读）：

| 命令 | 查询目标 | 返回格式 |
|------|----------|----------|
| `looper -q` | Looper 参数 | AA55 二进制帧 |
| `param -q <target>` | 系统参数 | AA55 二进制帧 |
| `effect query <id>` | 音效参数 | AA55 二进制帧 |
| `drum -q` | 鼓机状态 | JSON |
| `ui -q` | UI 状态 | JSON |

---

## 14. 附录

### 14.1 欢迎信息

```
BG Card Shell v2.0
IO:CDC
'help -a' for cmds
```

### 14.2 配置常量

| 常量 | 值 | 说明 |
|------|------|------|
| SHELL_CMD_MAX_LEN | 128 | 命令行最大长度 |
| SHELL_CMD_MAX_ARGS | 15 | 最大参数数量 |
| SHELL_MODULE_MAX | 30~40 | 最大模块数量 |
| SHELL_OUT_BUF_SIZE | 256 | 输出缓冲区大小 |
| SHELL_HISTORY_MAX | 10 | 命令历史条数 |

### 14.3 BanDataHub 专用命令

BanDataHub 项目是 BanBox 的精简版，包含以下额外/替代命令：

| 模块 | 说明 |
|------|------|
| `rec` | 录制控制 (`-s/--start [single\|dual]`, `-x/--stop`, `-i/--info`, `-f/--init`) |
| `sd` | SD 卡文件系统 (同 BanBox) |
| `sysmon` | 系统监控 |

### 14.4 相关源文件索引

**框架核心**:
- `BanBox/src/banux/04_shell_commands/bg_shell.h` — Shell API 和类型定义
- `BanBox/src/banux/04_shell_commands/bg_shell.c` — Shell 引擎实现
- `BanBox/src/banux/04_shell_commands/bg_shell_commands.c` — 模块注册和大部分模块定义

**传输层**:
- `BanBox/src/banux/02_device_drivers/USB/src/shell_io_cdc.c` — USB CDC 传输
- `BanBox/src/banux/04_shell_commands/shell_io_ble.c` — BLE 传输
- `BanBox/src/banux/04_shell_commands/shell_io_manager.c` — IO 管理器

**独立命令模块**:
- `shell_cmd_effect.c` — effect 模块
- `shell_cmd_graph.c` — graph/fx/eq_test 模块
- `shell_cmd_ui.c` — ui 模块
- `shell_cmd_param.c` — param 模块
- `shell_cmd_soundbank.c` — sb 模块
- `shell_cmd_metronome.c` — metro 模块
- `shell_cmd_drum.c` — drum 模块
- `shell_cmd_battery_calib.c` — calib 模块
- `shell_cmd_fat.c` — sd 模块
- `shell_cmd_psram.c` — psram 模块
- `shell_cmd_wav.c` — wav 模块
- `shell_cmd_wav_ble.c` — wav_ble 模块
- `shell_cmd_lp.c` — lp 模块
- `shell_cmd_mode.c` — mode 模块
