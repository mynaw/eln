# 第三方组件与许可

本项目自身以 **MIT** 许可发布（见 `LICENSE`）。它依赖或可选依赖以下第三方组件，
各自的许可与版权归其作者所有。

## 运行时必需

| 组件 | 许可 | 用途 | 说明 |
|---|---|---|---|
| [RDKit](https://www.rdkit.org/) | BSD-3-Clause | 结构解析、2D 出图、子结构/相似性检索、分子性质 | `pip install rdkit` |
| [Pillow](https://python-pillow.org/) | HPND（MIT-CMU 系） | 结构图与缩略图渲染 | `pip install pillow` |
| Tcl/Tk（Python 自带 `tkinter`） | BSD 系（Tcl/Tk License） | 图形界面 | 随 Python 发行 |
| [pywin32](https://github.com/mhammond/pywin32) | PSF-2.0 | Windows 剪贴板、DPAPI、快捷方式 | `pip install pywin32` |

## 可选

| 组件 | 许可 | 用途 |
|---|---|---|
| [markdown](https://python-markdown.github.io/) / [Pygments](https://pygments.org/) | BSD-3-Clause / BSD-2-Clause | 笔记 Markdown 渲染与代码高亮 |
| [tkinterweb](https://github.com/Andereoo/TkinterWeb) | MIT | 笔记内置浏览器预览 |
| [fpdf2](https://py-pdf.github.io/fpdf2/) | LGPL-3.0 | 记录导出 PDF |
| [python-docx](https://python-docx.readthedocs.io/) | MIT | 记录导出 DOCX |
| [Ketcher](https://github.com/epam/ketcher)（`ketcher-react` / `ketcher-standalone`） | **Apache-2.0** | 可选的增强结构编辑器 |

## 关于 Ketcher（Apache-2.0）

- 本仓库**不包含** Ketcher 的构建产物（`vendor/ketcher-app/dist` 已在发布时移除）。
  `vendor/ketcher-app/` 里只有本项目编写的桥接层（`src/main.jsx`、`index.html`、
  `package.json`、`vite.config.js`），Ketcher 作为 npm 依赖在构建时下载。
- 构建方式：`cd vendor/ketcher-app && npm ci && npm run build`，或运行 `tools/build_ketcher.bat`。
  构建产物仅在本机使用，不再二次分发。
- 若你重新分发构建好的 `dist`，需一并保留 Ketcher 的 Apache-2.0 `LICENSE`，
  并在显著位置说明修改（Apache-2.0 §4(b)）。本项目对 Ketcher 的改动仅限于
  桥接层（启动参数注入与回写通道），未修改 Ketcher 自身源码。

## 数据来源

- 应用完全离线运行。仅当用户主动使用「CAS 查结构」时，才会访问
  [NCI Cactus](https://cactus.nci.nih.gov/) / [PubChem](https://pubchem.ncbi.nlm.nih.gov/) 的公开接口，
  结果缓存在 `cas_cache.json`，可随时删除。
- 仓库中的 `demo/eln_demo.db` 为程序生成的示例数据，不含任何真实实验记录。
