# 随机抽签器

一款基于 Python + Tkinter 开发的**可视化随机抽签小工具**，界面简洁、逻辑严谨，适用于日常随机抽签、随机点名、随机分配场景。

## ✨ 项目特点

- **等概率不放回抽取**：每个号码出现的概率完全相同，一轮抽完不会重复

- 内置黑名单：自动跳过指定禁用号码

- 可视化剩余数量提示，实时展示抽取状态

- 一键重置数字池，操作简单

- 配置热加载：改完 `config.json` 保存即生效，无需重启

- 内置关于页面，展示开源协议与项目地址

- 原生 GUI 界面，跨平台可用、无广告、纯轻量

## ⚙️ 配置文件

程序目录下会自动生成 `config.json`，可在「帮助 → 编辑配置文件」中直接修改：

| 字段 | 说明 | 默认值 |
| --- | --- | --- |
| `pool_min` | 号码下界 | `1` |
| `pool_max` | 号码上界 | `54` |
| `excluded` | 黑名单，这些号码不会被抽到 | `[37, 39, 50]` |

抽签为**不放回**模式：抽中的号码离开号码池，直到抽完或点击重置。
除黑名单外，没有任何加权或屏蔽逻辑——每个候选号码等概率出现。

## 🛠 运行环境

- Python 3.8+

- 内置 Tkinter（Python 自带，无需额外安装依赖）

## 🚀 使用方法

### 1. 源码运行

```bash
python random_draw.py
```

### 2. 运行测试

```bash
python -m unittest discover -p "test_*.py"
```

### 3. 打包成 Windows EXE

#### 方式一：GitHub Actions（推荐，无需本地 Windows）

仓库已配置 `.github/workflows/build-exe.yml`。推送到 `main` 后会自动：

1. 在 Ubuntu 上跑单元测试
2. 在 Windows runner 上并行打包（PyInstaller 与 Nuitka 各一份）
3. 产出 `RandomDraw-pyinstaller` 与 `RandomDraw-nuitka` 两个 artifact

在仓库的 **Actions → Build EXE → Artifacts** 下载即可，
也可以在 Actions 页面点 **Run workflow** 手动触发。

两个版本各有取舍：**Nuitka** 编译为原生代码，杀软误报率明显更低（推荐分发用）；
**PyInstaller** 产物更小、构建更快。

#### 方式二：本地 Windows 构建

```powershell
pip install pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name RandomDraw random_draw.py
```

或用 Nuitka：

```powershell
pip install nuitka
python -m nuitka --standalone --onefile --windows-disable-console --enable-plugin=tk-inter --assume-yes-for-downloads --output-filename=RandomDraw.exe random_draw.py
```

## 📂 项目结构

```Plain Text
.
├── random_draw.py                    # 界面层（Tkinter）
├── draw_core.py                      # 配置解析与抽签核心，不依赖 Tkinter
├── test_draw_core.py                 # 抽签核心单元测试
├── test_packaging.py                 # 打包相关单元测试（含开机自启路径）
├── .github/workflows/build-exe.yml   # CI：测试并打包 Windows EXE
├── README.md                         # 项目说明文档
└── LICENSE                           # 开源协议文件
```

## 📄 开源协议

本项目采用 **GNU General Public License v3.0 (GPL‑3.0)** 开源。
详见仓库根目录下的 LICENSE 文件。

## 📝 更新日志

### v1.1

- 移除放回 / 不放回双模式，统一为单模式不放回抽取
- 移除重抽触发机制（`reroll_triggers` / `max_rerolls`），抽签恢复为完全等概率
- 旧配置文件中的重抽字段会在下次加载时自动清除
- 拆分界面层与抽签核心，消除全局变量
- 界面布局调整：内容垂直居中，避免移除模式选择后卡片留大片空白
- 修复打包成单文件 exe 后开机自启失效的问题（原先指向已删除的临时解压目录）
- 新增 GitHub Actions 工作流，自动测试并打包 Windows EXE（PyInstaller + Nuitka）
- 新增配置文件字段表，删除重抽机制说明
- 测试扩充至 28 项，新增分布均匀性检验、废弃键迁移验证、打包路径验证

### v1.0

- 实现放回 / 不放回双随机模式

- 完善智能重抽机制

- 添加剩余数量实时显示、一键重置功能

- 新增关于页面、开源协议与项目链接

- 优化界面文字，更贴合用户理解逻辑