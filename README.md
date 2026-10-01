# Obra Dinn 存档工具

《Return of the Obra Dinn》的存档查看 / 编辑工具。

界面是一个本地网页，程序自己起一个只监听 `127.0.0.1` 的小服务器 —— **不联网、不上传任何数据**，所有操作都只读写你本机的存档文件。

> 非官方工具，与 Lucas Pope / 3909 无关。
> 存档格式是自己逆向出来的，仓库里**不含**游戏的反编译源码和素材。

---

## 它能做什么

**游戏槽位（P1 / P2 / P3）**

每张卡片直接显示这份存档的状态：解对数 `x / 60`、阶段（调查 / 推理 / 保险评估 / 办公室）、结局走向（好 / 中等 / 坏）、主人公性别、已解锁章节数。

- **导出到存档库** —— 把槽位内容收进工具的存档库
- **切换性别** —— 改主人公性别（只影响文本称呼，与玩法无关）
- **下载** —— 直接存到本机任意位置
- **详细信息** —— 浮层里给全量字段：路径 / 大小 / 修改时间 / 完整 sha256、船上区与办公室区的解对情况、空白脸数、已解锁章节、包裹 / 猴爪 / 看破书页 / 已通关标志、游玩时长……

**预制存档**

随程序分发的 5 份只读模板，一键装到任意槽位：

| 名字 | 内容 |
|---|---|
| 坏结局存档 | 0/60 · 信封 · 坏结局信件 |
| 中等结局存档 | 56/60 · 信封 · 中等结局信件 |
| 好结局存档 | 58/60 · 包裹 |
| 直接推理存档 | 0/60，但全部现场已看过，可直接开始推理 |
| “船长干的”存档 | 0/60，用来触发 `KillerCaptain` 成就 |

预制存档是**只读**的：删不掉、改不了，装到槽位之后随便你怎么改。

**存档库与备份**

- 导入任意存档文件进库，库里可以导出 / 下载 / 删除 / 切性别
- 按槽位列出备份，**包括游戏自己留的 `-Recent` 快照**（槽位被覆盖后的救命稻草），可以一键恢复
- 任何写入之前都会先把原文件备份一份

**其它**

- 页头 `A-` / `A+` 缩放界面字号（记在浏览器本地）
- 整个界面按窗口大小计算尺寸，不写死像素
- 打包版是「app 模式」窗口：没有地址栏和标签页，像原生程序，启动即最大化

---

## 快速开始（从源码运行）

```bash
git clone https://github.com/Yide-Zhang/ObraDinn-SaveTool.git
cd ObraDinn-SaveTool
python run_gui.py
```

不需要装任何第三方包 —— **运行时只用标准库**。Python 3.12 或更高（在 3.12 / 3.13 上实测通过，更低版本未测试）。

常见参数：

```bash
python run_gui.py --port 9000    # 指定端口（默认 8722，被占用会自动往后找）
python run_gui.py --no-browser   # 只起服务，不开窗口
python run_gui.py --tab          # 用普通浏览器标签页，而不是 app 窗口
```

开发时设 `OBRADINN_GUI_DEV=1`，改 `gui/web.py` 后刷新浏览器即可生效，不用重启服务。

### 命令行也能单独用

`save_tool.py` 是个「库 + 薄 CLI」，GUI 就是调它：

```bash
python save_tool.py slots                        # 列出三个槽位
python save_tool.py info ObraDinnSave-P1.txt     # 打印摘要
python save_tool.py gender ObraDinnSave-P1.txt --toggle
python save_tool.py export SRC DST               # 导出（校验 + 复制）
python save_tool.py import SRC --slot P1         # 导入（自动备份 + 回读校验）
python save_tool.py backups P1                   # 列备份
```

---

## 打包成可执行文件

```bash
python -m pip install pyinstaller
python build_gui.py
```

- Windows → `dist/ObraDinnSaveTool.exe`（单文件，约 9 MB，双击不弹黑窗）
- macOS → `dist/ObraDinnSaveTool.app`（需要在该平台上构建，PyInstaller 不能交叉编译）

打完会自带字体和预制存档，拷走即可用。打包后没有控制台，退出请点界面上的「退出程序」。

---

## 存档在哪里

| 平台 | 游戏存档目录 |
|---|---|
| Windows | `C:\Users\<你>\AppData\LocalLow\3909\ObraDinn\` |
| macOS | `~/Library/Application Support/co.3909.ObraDinn/` |

里面有 `ObraDinnSave-P1/P2/P3.txt`，以及 `Backup/` 目录下游戏自己保留的上一份快照。

工具自己的东西：

| | 存档库 | 日志 |
|---|---|---|
| 源码运行 / Windows 打包 | 程序旁边的 `saves/` | 程序旁边的 `ObraDinnSaveTool.log` |
| macOS 打包 | `~/Documents/ObraDinnSaves` | `~/Library/Logs/ObraDinnSaveTool.log` |

存档库默认放在程序旁边，所以整个文件夹拷到哪都能用（便携）。也可以用环境变量 `OBRADINN_LIBRARY` 指定别的位置。

---

## 项目结构

```
run_gui.py              入口：起服务、开窗口、把 print 接到日志文件
build_gui.py            PyInstaller 打包
smoke_gui.py            对运行中的实例做一次冒烟测试

gui/server.py           本地 HTTP 后端（只用标准库）
gui/web.py              单文件前端（HTML / CSS / JS 全内嵌，无外部依赖）
gui/data.py             从游戏数据生成好的常量表，见下方说明
gui/fonts/              界面字体（已子集化，2.75 MB → 529 KB）
gui/presets/            预制存档 + 显示名清单

save_tool.py            存档读写核心：摘要、导出、导入、备份
make_envelope_save.py   XXTEA 容器读写 + 区域划分 / 结局判定
tea_decrypt.py          XXTEA 解密
parse_assets.py         游戏 TextAsset 解析（**可选**，见下）
test_roundtrip.py       回写链路的往返校验
```

**关于 `parse_assets.py`**：它读的是从游戏里导出的 TextAsset 文本（`Crew` / `Moments` 等，属于游戏资源，本仓库不含）。没有那份导出也能正常用 —— `save_tool` 会自动回退到 `gui/data.py` 里固化好的名单，这也是打包版的行为。

---

## 说明与限制

- **只动本机文件**。服务只绑定 `127.0.0.1`；页面里所有文件路径都必须落在「游戏存档目录 ∪ 存档库 ∪ 预制存档目录」之内，防止页面被诱导读写任意文件。
- **写入前一律先备份**，并且写完会回读校验。
- 存档外层是 UTF-8 XML，`<data>` 里是 Base64 的 **XXTEA** 密文，密钥由游戏代码里的两段字符串拼出来（见 `tea_decrypt.py`）。
- 逆向针对的是游戏 **1.2.122** 版。其它版本可能有字段差异，工具会尽量容错，但不保证。
- 没有实现的部分：不生成新的存档（预制存档是预先造好的静态文件），不改剧情推进类字段。

---

## 致谢与许可

**字体**（都在 `gui/fonts/`，已做子集化）

- **IM FELL English**（`IMFeENrm28P.ttf`）— Igino Marini，SIL Open Font License 1.1
  <https://iginomarini.com/fell/>
- **思源宋体 SC / Source Han Serif SC**（`SourceHanSerifSC-SemiBold-subset.otf`）— Adobe，SIL Open Font License 1.1
  <https://github.com/adobe-fonts/source-han-serif>

两者都用 SIL OFL 1.1 授权，许可全文见 <https://scripts.sil.org/OFL>。
注意 OFL 的两条要求：分发时需随附许可证副本；以及第 3 条对**保留字体名**的限制 —— 本仓库里的字体是子集（属于 OFL 定义的「修改版本」），单独再分发字体文件时请留意这一点。

**代码**

本仓库暂未指定开源许可证（默认保留所有权利）。如果希望别人自由使用和修改，建议补一个，比如 MIT。

---

## 免责声明

本工具会**修改游戏存档**。虽然所有写入前都会自动备份，但请自行承担风险 —— 建议先手动复制一份存档目录。作者不对存档损坏或成就异常负责。
