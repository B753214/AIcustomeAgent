# 开发环境说明（Harness H0-1）

本文约定本仓库的 Python 版本与虚拟环境创建方式，与根目录 [README.md](../README.md)「快速开始」一致。

## 版本策略

| 项 | 约定 |
|---|---|
| 兼容范围 | Python **3.10–3.12** |
| **推荐锁定** | **Python 3.12**（本地开发、文档示例、后续 CI 以 3.12 为准） |
| 包管理 | 运行时依赖以 `pip` + `requirements*.txt` 为准（Conda 只负责解释器） |

> 若本机默认 `python` 不是 3.12，Windows 可用 `py -3.12 -m venv .venv`。

## 方式 A：venv（默认）

```powershell
cd AICustomeRobort
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
pip install -U pip
pip install -r requirements.txt
```

Linux / macOS：

```bash
cd AICustomeRobort
python3.12 -m venv .venv
source .venv/bin/activate
python --version
pip install -U pip
pip install -r requirements.txt
```

## 方式 B：Conda（可选）

仓库根目录提供 `environment.yml`（仅固定 Python 3.12 + pip）：

```powershell
cd AICustomeRobort
conda env create -f environment.yml
conda activate aicustomerobort
python --version
pip install -U pip
pip install -r requirements.txt
```

更新已有 Conda 环境中的 Python 约束：

```powershell
conda env update -f environment.yml --prune
```

## 可选依赖

| 文件 | 用途 |
|---|---|
| `requirements.txt` | 核心 API / RAG / Chat（含 pdfplumber、openai、requests） |
| `requirements-extra.txt` | CrewAI、重排（sentence-transformers + dashscope）、Playwright |
| `requirements-dev.txt` | 开发与测试 |
| `requirements-eval.txt` | 评测（RAGAS 等） |

装完 `requirements-extra.txt` 且启用浏览器降级时：

```powershell
playwright install chromium
```

## 验收（H0-1）

- [x] 文档写明兼容范围与推荐 3.12
- [x] 同时提供 venv 与 Conda 创建步骤
- [x] 一次安装命令与 README 对齐

下一阶段 **H0-2** 验证各 `requirements*.txt` 在本机可 `pip install` 成功。

## H0-2 验证记录

| 文件 | UTF-8 | 安装验证（`conda run -n agent-test`，Python 3.12） |
|---|---|---|
| `requirements.txt` | 是 | 通过 |
| `requirements-dev.txt` | 是 | 通过 |
| `requirements-extra.txt` | 是 | 通过 |
| `requirements-eval.txt` | 是 | 通过 |

> 注意：系统默认 `python` 若为 3.14（如部分 Conda `base`/`agent`），可能无法安装部分包；请使用 **3.12**（`conda activate agent-test`、`car_robot_python` 或 `environment.yml` 新建 `aicustomerobort`）。
>
> CI 工作流修正属于 **H0-5**，本步只保证分层 requirements 本机可装。

配置字段对照与缺项说明见 [config.md](./config.md)（H0-3）。
