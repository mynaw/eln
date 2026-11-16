# ELN · 单机电子实验记录本

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)

一个**完全离线、双击即用**的化学实验记录本。数据就是一个 SQLite 文件加一个附件目录，
拷走就能带走全部记录；不需要装数据库、不需要浏览器、不需要账号。

取的是 [Chemotion ELN](https://www.chemotion.net/) 的核心模型（集合 / 药剂 / 反应 / 组成 /
结构 / 附件 / 子结构检索），但把 Rails + PostgreSQL + Docker 那一整套服务端全砍掉了。

![主界面](assets/screenshot.png)

## 声明

**本项目的全部代码由 DeepSeek-V4.1-Flash 构建**（含本 README、手册与全部脚本）。

- 生成结果经过自动化自检（`python selfcheck.py`，497 项全绿）后发布；使用前建议再自行审阅关键逻辑。
- 代码按「现状」提供，不对适用于特定用途作任何担保；用于实验记录、数据处理前请自行评估与测试。
- 第三方组件的版权与许可归各自作者，详见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。

## 能做什么

| 模块 | 说明 |
|---|---|
| **药剂台账** | 名称 / 编号 / CAS / SMILES / 分子量 / 纯度 / 状态 / 存放位置；SMILES 实时出结构图与分子式 |
| **反应记录** | 条件、操作、产率；**组成表按当量双向换算**，改用量自动重算其它行 |
| **结构检索** | 文本、**子结构**（SMARTS）、相似性（Tanimoto）三种模式 |
| **绘制区** | 内置画板画结构式与反应式，存 JSON 可再编辑；可导出 PNG，或交给 ChemDraw / Ketcher 编辑后读回 |
| **电子效应** | 选中取代基，按常见基团的 σ 值给出趋势判断 |
| **实验笔记** | 块式记录（文本 / 步骤 / 化学 / 表格 / 计算），可导出 Markdown / HTML |
| **导入导出** | SDF / CSV 进出；单条记录导出 PDF / DOCX；整库打包成 `.eln` 标准包 |
| **日历视图** | 按日期回看当天做了哪些实验 |

![画板](assets/drawpad.png)
![实验笔记](assets/notebook.png)

## 获取与运行

### 方式一：免安装版（推荐）

下载 `ELN-<版本>-win64.zip`，解压后任选其一：

- **直接用**：双击 `ELN\ELN.exe`
- **装到本机**：双击 `安装.bat` —— 复制到 `%LOCALAPPDATA%\Programs\ELN`，
  并创建桌面与开始菜单快捷方式（不需要管理员权限）。卸载运行 `卸载.bat`。

首次启动会在程序目录自动建 `eln.db`（空库）和 `attachments/`。

### 方式二：源码运行

```bash
git clone https://github.com/mynaw/eln.git
cd eln
pip install -r requirements.txt      # 必需：rdkit pillow pywin32
python gui.py
```

Windows 上也可以直接双击 `Start.bat`（自动找 PATH 里的 `pythonw`）。

**想看演示数据**（4 个药剂 / 1 个反应 / 2 张图，不含任何真实实验记录）：

```bash
python tools/load_demo.py     # 复制 demo/eln_demo.db → eln.db（已存在则跳过）
```

### 可选：Ketcher 编辑器

内置画板之外，还可以把结构送进 [Ketcher](https://github.com/epam/ketcher)（EPAM 开源，
手感接近 ChemDraw）编辑后回写。它是前端工程，需要先构建一次：

```bash
cd vendor/ketcher-app && npm ci && npm run build
```

或双击 `tools/build_ketcher.bat`。**不构建也不影响其它功能**，只是「用 Ketcher 编辑」不可用。

## 数据与隐私

- **完全离线**：不做任何后台请求。只有主动点「CAS 查结构」时才会访问
  NCI Cactus / PubChem 的公开接口，结果缓存在 `cas_cache.json`，可随时删除。
- **数据在哪**：程序目录下的 `eln.db`（SQLite 单文件）+ `attachments/`（附件副本）。
  整个文件夹拷走就是完整迁移，`备份.bat` 会打包成 zip。
- **密码**：账户密码用加盐哈希 + Windows DPAPI 存储，不上传任何地方。
- **多人共用**：不建议直接共享同一个库（SQLite 单文件写入）。多设备请用 SDF/CSV 汇总，
  或启用内置的网页服务模式（见手册）。

## 已知限制

- **Windows 优先**：界面用 Tkinter，macOS / Linux 上能跑但未做适配测试。
- **画板不画立体化学**：楔形键/虚线键画不出来。但结构**预览与导出**图会按 SMILES 的
  `@`/`@@` 正确画出楔形并标注 (R)/(S)/(E)/(Z)；画板本身只管二维骨架。
- **不做智能推断**：缩写基团（OBz、TBS…）只作标注，不会展开成真实结构；
  箭头上下的试剂文字只作图注，不进反应 SMILES。
- **单机单人**：没有权限管理与审计追踪，不是合规级 ELN。
- 完整边界说明见 [`MANUAL.md`](MANUAL.md) 第十二章。

## 目录结构（主要部分）

```
eln/
├── gui.py             主窗口：三栏布局、工具栏、列表与详情
├── dialogs.py         新建 / 编辑对话框（药剂、反应、组成）
├── drawpad.py         绘制区：画板 + RDKit 转换 + ChemDraw/Ketcher 交换
├── notebook.py        块式实验笔记
├── store.py           SQLite 数据层（schema / 迁移 / 查询）
├── chem.py            RDKit 封装：解析、出图、性质计算
├── structure.py       子结构 / 相似性检索
├── recexport.py       记录导出 PDF / DOCX
├── webapp.py          可选的网页服务模式
├── tools/             备份、演示库、Ketcher 构建、打包脚本
├── demo/eln_demo.db   演示数据（不含真实记录）
└── MANUAL.md          完整用户手册（程序内按 F1 打开同一份）
```

## 开发与自检

```bash
python selfcheck.py       # 497 项自检，全绿输出「通过 N 项，失败 0 项」
```

自检覆盖数据层、检索、导出、绘制、笔记、鉴权、打包等模块，改完代码跑一遍最省心。

## 许可证

本项目以 **MIT** 许可发布，见 [LICENSE](LICENSE)。

依赖的第三方组件（RDKit / Pillow / Tcl-Tk / Ketcher / fpdf2 等）各自遵循其原有许可，
义务与说明见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。
