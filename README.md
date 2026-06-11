# 水课快答 v1.3.0

**把大学生从水课作业中解救出来——自动截图、AI 答题、模拟点击，全程无需动手。**

水课快答不挑平台：超星学习通、智慧树、中国大学 MOOC、人卫、学堂在线……只要屏幕上看得到题目、鼠标点得到选项，它就能刷。

---

## 系统要求

### 最低配置

| 类别 | 要求 |
|------|------|
| **操作系统** | Windows 10（64 位，版本 1607+） |
| **Python** | 3.9+（64 位，需添加到 PATH） |
| **PowerShell** | 5.0+（Windows 10 内置） |
| **内存** | 8 GB RAM |
| **磁盘** | 5 GB 可用空间（含依赖和 OCR 模型） |
| **显卡** | 无要求（CPU 模式可运行，速度较慢） |
| **网络** | 首次启动需联网下载依赖和模型 |

### 推荐配置

| 类别 | 要求 |
|------|------|
| **操作系统** | Windows 10/11（64 位，22H2+） |
| **Python** | 3.12（64 位） |
| **PowerShell** | 5.1+（Windows 10/11 内置） |
| **内存** | 16 GB RAM |
| **磁盘** | 10 GB 可用空间 |
| **显卡** | NVIDIA GTX 1060 或更高（CUDA 12.6，GPU 加速 OCR 约 15x CPU） |
| **网络** | 国内宽带（依赖/模型均走清华镜像和百度 BOS） |

> **注意**：32 位 PowerShell 可能无法检测到 64 位 Python，请确保使用 64 位 PowerShell 运行启动器。

### 平台兼容性

水课快答的核心依赖 **PaddlePaddle** 仅官方支持 **x86_64（AMD64）** 架构，因此兼容性受限于此。

#### ✅ 完全支持

| 平台 | 说明 |
|------|------|
| **Windows 10/11 x64** | 原生支持，带 CUDA GPU 的 NVIDIA 显卡可加速 OCR |
| **Windows 10/11 x64 虚拟机** | VMware / VirtualBox / Hyper-V，建议分配 4 核 + 8 GB 内存 |

#### ⚠️ 部分可用（需折腾，不推荐普通用户尝试）

| 平台 | 现状 |
|------|------|
| **Debian / Ubuntu x64** | `pyautogui` 和 `keyboard` 需 X11 环境 + root 权限，`start.ps1` 无法运行需手动 pip install。OCR 可用但无法自动点击答题。 |
| **Apple M 系列芯片（M1-M4）** | 通过 Parallels Desktop / VMware Fusion / UTM 运行 Windows 11 ARM64 虚拟机时，PaddlePaddle 无 ARM64 版本，OCR 功能可能受限。可运行界面，OCR 能否工作需自行验证。 |

#### ❌ 暂无测试报告（理论上存在障碍，欢迎用户反馈实测结果）

| 平台 | 理论障碍 | 预计难度 |
|------|---------|---------|
| **Windows 11 on ARM64**（骁龙 X Elite / Surface Pro 11 等） | PaddlePaddle 官方不提供 ARM64 Windows wheel。可尝试从源码编译或等待官方支持。 | ⭐⭐⭐⭐⭐ |
| **华为鸿蒙电脑（OsEasy 虚拟机）** | x86 模拟层性能可能不足以运行 PaddlePaddle + OCR 推理。 | ⭐⭐⭐⭐⭐ |
| **Debian / ARM64**（树莓派 5、Rockchip 等） | PaddlePaddle 无 Linux ARM64 wheel；CPU 性能较弱，OCR 推理速度可能极慢。 | ⭐⭐⭐⭐ |
| **Android Termux + Debian 13 ARM64** | 无桌面环境，`pyautogui` 无法模拟点击；PaddlePaddle ARM64 需自行编译。 | ⭐⭐⭐⭐⭐ |
| **Android 小小电脑** ([tiny_computer](https://github.com/Cateners/tiny_computer)) | 底层为 Linux ARM64，受限于架构和 Android 沙箱。 | ⭐⭐⭐⭐⭐ |
| **Android XoDos2** ([XoDos2](https://github.com/xodiosx/XoDos2)) | DOS 模拟环境，需确认是否支持 Python 3.9+ 运行时。 | ⭐⭐⭐⭐⭐ |
| **Apple A 系列芯片**（iPad/iPhone） | 需通过 UTM 等虚拟机运行 Windows/Linux，性能高度受限。 | ⭐⭐⭐⭐⭐ |

> 以上平台均**未经开发者测试**，理论上存在障碍但并非绝对不可能。如果你在这些平台上成功运行了水课快答，欢迎提交反馈报告。

---

## 环境和文件不全（当自动下载失效时）

启动器 `start.ps1` 会自动完成所有环境配置。但如果自动安装/下载失败，请按以下步骤手动操作。

### 情况一：Python 未安装

启动器会自动打开微软商店。如果没有自动打开，手动操作：

1. 打开 **开始菜单**，搜索 **Python**
2. 选择 **Python 3.13**（微软商店版），点击安装
3. 安装完成后重新运行 `start.ps1`

> 如果不想用微软商店，也可以从 [Python 官网](https://www.python.org/downloads/) 或 [阿里镜像](https://mirrors.aliyun.com/python/) 下载安装包。安装时务必勾选 **「Add Python to PATH」**。

### 情况二：依赖安装失败（pip 报错）

启动器会依次尝试 5 个国内镜像源。如果全部失败，请手动安装：

1. 按 **Win + R**，输入 `cmd`，回车打开命令提示符
2. 复制粘贴以下命令并回车：

```
pip install PyQt5 Pillow openai httpx pyautogui keyboard paddlepaddle-gpu paddleocr paddlex -i https://mirrors.aliyun.com/pypi/simple
```

3. 如果上面的命令报错，换一个镜像源试试：

```
pip install -r requirements.txt -i https://mirrors.cloud.tencent.com/pypi/simple
```

```
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> `requirements.txt` 文件在本程序目录下，包含所有依赖的版本号。

**常用国内 PyPI 镜像源：**

| 镜像 | 地址 |
|------|------|
| 阿里云 | `https://mirrors.aliyun.com/pypi/simple` |
| 腾讯云 | `https://mirrors.cloud.tencent.com/pypi/simple` |
| 华为云 | `https://repo.huaweicloud.com/repository/pypi/simple` |
| 清华大学 | `https://pypi.tuna.tsinghua.edu.cn/simple` |
| 中科大 | `https://pypi.mirrors.ustc.edu.cn/simple` |

### 情况三：OCR 模型下载失败

OCR 模型用于识别屏幕上的题目文字，首次运行时自动下载（约 100MB）。如果自动下载失败，请手动下载：

**需要下载的 5 个文件：**

| 模型 | 作用 | 下载链接 |
|------|------|---------|
| PP-OCRv5_server_det | 文字检测 | [点击下载](https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/PP-OCRv5_server_det_infer.tar) |
| PP-OCRv5_server_rec | 文字识别 | [点击下载](https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/PP-OCRv5_server_rec_infer.tar) |
| PP-LCNet_x1_0_doc_ori | 文档方向检测 | [点击下载](https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/PP-LCNet_x1_0_doc_ori_infer.tar) |
| PP-LCNet_x1_0_textline_ori | 文本行方向检测 | [点击下载](https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/PP-LCNet_x1_0_textline_ori_infer.tar) |
| UVDoc | 文档矫正 | [点击下载](https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/UVDoc_infer.tar) |

> 以上链接托管在百度智能云 BOS，国内访问流畅，5 个文件共约 100MB。

**操作步骤：**

1. 下载上面 5 个 `.tar` 文件
2. 找到以下目录（没有就手动创建）：
   ```
   C:\Users\你的用户名\.paddlex\official_models\
   ```
   > 快速打开：按 Win+R，输入 `%USERPROFILE%\.paddlex\official_models` 回车
3. 用 [7-Zip](https://www.7-zip.org/) 或 WinRAR 解压每个 `.tar` 文件
4. 解压后会得到 5 个文件夹，直接放到 `official_models` 目录下

**最终目录结构：**

```
C:\Users\你的用户名\.paddlex\official_models\
├── PP-OCRv5_server_det\
│   ├── inference.pdiparams
│   ├── inference.pdmodel
│   └── ...
├── PP-OCRv5_server_rec\
│   └── ...
├── PP-LCNet_x1_0_doc_ori\
│   └── ...
├── PP-LCNet_x1_0_textline_ori\
│   └── ...
└── UVDoc\
    └── ...
```

> 每个文件夹里应该有 `inference.pdiparams`、`inference.pdmodel` 等文件，不是再套一层文件夹。如果解压后多了一层目录，需要把里面的文件移出来。

完成后重新运行 `start.ps1`，启动器会检测到模型已存在，跳过下载步骤。

## 使用指南

### 一、安装

1. 解压 `水课快答.zip` 到任意文件夹（D 盘、桌面均可）
2. 右键 `start.ps1` → **使用 PowerShell 运行**
3. 启动器会自动检测环境、安装依赖、下载 OCR 模型
4. 首次运行时会询问是否创建桌面快捷方式和启用管理员权限
5. 后续可通过桌面快捷方式或直接双击 `main.pyw` 启动

> 若右键没有「使用 PowerShell 运行」选项：Win+R → `powershell` → `cd 解压路径` → `.\start.ps1`

### 二、获取免费 API Key

水课快答默认使用七牛云免费大模型，学生注册即可获得额度：

1. 打开 [七牛云 AI 推理平台](https://portal.qiniu.com/ai-inference/model)
2. 注册账号（验证邮箱并实名认证） → 控制台 → 创建 API Key
3. 复制 API Key，粘贴到软件的「LLM 设置」→「API Key」输入框中
4. 点击「保存」

> 软件已预填 API 地址和模型名称，不需改动。但七牛云对新用户赠送了300万tokens的免费额度，应该足够免费使用一段时间的付费模型，具体详见**模型广场**。

### 三、首次配置（以人卫平台为例）

假设你要在人卫 APP 上刷题，每题有 A/B/C/D/E 五个选项。

#### 3.1 分类管理

1. 打开「题型预设」Tab
2. 点击「➕ 新建分类」，输入 `人卫`

#### 3.2 框选截图区域

1. 回到「主操作」Tab
2. 打开一道题目（显示在屏幕上）
3. 点击「📷 框选截图区域」→ 拖拽框选包含题目和选项的区域

#### 3.3 标定按钮位置

1. 点击「标定选项位置」→ 依次在屏幕上点击 A、B、C、D、E 五个按钮
2. 点击「标定下一题按钮位置」→ 点击屏幕上的「下一题」按钮

#### 3.4 框选辅助区域（可选，用于动态定位和自动切换）

1. 点击「📷 框选选项按钮区域」→ 框选只包含 A/B/C/D/E 五个按钮的区域
2. 点击「📷 框选题型文字区域」→ 框选显示"题型"文字的位置（如 A1 型题）
3. 开启「启用动态选项定位」→ 勾选「动态定位不足时回退到固定坐标」

#### 3.5 保存预设

1. 在「当前预设」下拉框中确认选中的是 `A1型题`
2. 点击「💾 保存当前为预设」→ 选择「覆盖更新」

#### 3.6 配置自动停止（可选）

在「答题自动停止」区域选择：

- **OCR 识别题号**：框选题号显示区域（如屏幕上的 "1/100"），答满自动停
- **手动设总题数**：输入总题数，点够次数自动停

#### 3.7 主操作界面一览

```
① 截图区域 ─── 📷 框选截图区域
② 选项配置 ─── 选项数量 + 标定选项 + 标定下一题
③ 题型预设 ─── 预设类别 + 当前预设 + 保存/删除 + 自动切换
③½ 动态定位 ─ 启用动态定位 + 框选按钮区域 + 框选题型区域 + 校准偏移
④ 答题停止 ─── 停止模式 + 总题数
⑤ 开始答题 ─── ▶ 开始 / ⏸ 暂停 / ■ 停止
```

### 四、开始刷题

1. 打开刷题 APP，进入答题页面
2. 回到软件，点击 **「▶ 开始自动答题」**（或按 F9）
3. 效果：截图 → OCR 识别题目 → AI 推理答案 → 自动点击选项 → 自动下一题 → 循环

### 五、快捷键

| 按键 | 功能 |
|------|------|
| F9 | 开始自动答题 |
| F10 | 暂停 / 继续 |
| F11 | 切换 OCR 模式 / 多模态模式 |
| F12 | 标记当前题为主观题（弹出答案窗口） |

可在「快捷键」Tab 中自定义。

### 六、多平台切换

不同平台的题目布局不同。例如人卫和超星的选项位置不一样。

1. 新建一个分类（如 `超星`）
2. 按照 3.1-3.5 重新配置一遍
3. 切换平台时，在「预设类别」下拉框中选对应的分类即可

所有配置（截图区域、按钮区域、选项坐标、下一题坐标等）会自动保存到独立的配置文件中，重启不丢失。

### 七、常见问题

**Q：按钮点击偏了怎么办？**
A：勾选「启用动态选项定位」→ 跑一题 → 点「🎯 校准坐标偏移」

**Q：题号识别不准（10/100 被当成 10/10）？**
A：OCR 数字识别偶尔会出错。建议手动设总题数模式，或把题号区域框稍大一些。

**Q：报 429 限流？**
A：免费 API 有并发限制。软件会自动弹窗询问重试，稍等几秒即可。

---

## 技术实现

> 以下内容面向开发者，普通用户无需阅读。

### 核心流程

```
PyQt5 截图 → PaddleOCR GPU 本地识别 → OpenAI 兼容 API 推理 → pyautogui 模拟点击
```

### 技术栈

- **Python 3.13** + **PyQt5** — 图形界面
- **PaddleOCR 3.6** + **PaddlePaddle GPU 3.3** — 本地 OCR（支持 CUDA 加速）
- **httpx** — 大模型 API 流式调用
- **pyautogui** — 鼠标模拟点击
- **keyboard** — 全局快捷键
- **PowerShell 启动器** — 一键环境检测、依赖安装、模型下载
- **JSON 文件存储** — 预设独立文件 + 分类级别配置

### 预设文件结构

```
%LOCALAPPDATA%\AnswerAssistant\LLMAnswerAssistant\presets\
  人卫\
    _category.json      ← 平台级设置（截图区域、按钮区域、题型区域、校准偏移）
    A1型题.json          ← 题型级设置（选项坐标 + 下一题坐标）
    B1型题.json
    X型题.json
```

### 动态选项定位原理

由于不同题目题干长度不同，选项按钮的屏幕位置会上下浮动。动态定位通过分析单次 OCR 结果的文字块空间分布，推断每道题的选项按钮实时坐标：

1. OCR 识别全屏文字块及坐标
2. 匹配按钮标签 "A" 获取按钮列 X 坐标
3. 按 Y 坐标排序内容文字块，分配给 A/B/C/D/E
4. 合成：按钮 X + 内容 Y → 精确点击坐标

支持纵向（5×1）、横向（1×5）、矩阵（2×3）等多种选项排列。

---

## 致谢

水课快答站立在以下开源项目和服务之上：

- **[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)** — 百度飞桨 OCR 引擎
- **[PaddlePaddle](https://github.com/PaddlePaddle/Paddle)** — 百度深度学习框架
- **[PyQt5](https://www.riverbankcomputing.com/software/pyqt/)** — Riverbank Computing 的 Qt Python 绑定
- **[pyautogui](https://github.com/asweigart/pyautogui)** — Al Sweigart 的跨平台自动化库
- **[httpx](https://github.com/encode/httpx)** — Encode 团队的现代 HTTP 客户端
- **[keyboard](https://github.com/boppreh/keyboard)** — BoppreH 的全局键盘钩子库
- **[七牛云](https://www.qiniu.com/)** — 提供免费大模型推理 API

感谢所有为开源事业贡献代码的开发者。

## 许可证

**[GNU Affero General Public License v3.0（AGPL-3.0）](https://www.gnu.org/licenses/agpl-3.0.html)**

任何使用、修改或分发本项目的第三方，无论是否通过网络提供服务，都必须以相同协议完全开源其全部源代码。
