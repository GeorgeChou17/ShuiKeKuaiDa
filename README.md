# 水课快答 v1.2

**把大学生从烦人的水课中解脱出来，免费、高效地完成在线作业。**

## 核心原理

水课快答通过 **OCR 文字识别 + 模拟鼠标点击** 完成自动答题。它不看网页结构、不调用任何平台 API，只做两件事：

> 📷 截取屏幕上一块区域 → 识别图片里的题目文字 → 发给大模型推理出答案 → 🖱️ 模拟鼠标点击对应选项

**这意味着它不挑平台、不挑课程。** 无论是超星学习通、智慧树、中国大学 MOOC、学堂在线，还是学校自建的教务系统——只要你的电脑屏幕上能显示题目、鼠标能点击选项，水课快答就能刷。它不是某个平台的"外挂"，而是整个屏幕的"机器人"。

## 项目目的

大学里总有那么几门"水课"——课程内容与专业无关，但作业却要一题一题手动点击。水课快答的目标就是让这些重复劳动完全自动化：

- 🆓 **完全免费**：默认集成七牛云免费模型（`z-ai/glm-4.5-air-free`），注册即可获取免费额度
- ⚡ **GPU 加速**：本地 OCR 基于 PaddlePaddle GPU，单题识别不到一秒
- 🎯 **一键答题**：截图 → OCR → 大模型推理 → 自动点击答案 → 自动下一题
- 🧠 **智能题型识别**：自动区分 A1/A2/A3/A4 型题、B 型配伍题、X 型多选题、判断题、主观题
- ⌨️ **全局快捷键**：F9 开始、F10 暂停、F11 切换模式、F12 标记主观题，全程无需切窗口

## 技术实现

```
┌─────────┐    ┌──────────┐    ┌───────────┐    ┌──────────┐
│ PyQt5   │───▶│ 截图区域  │───▶│ PaddleOCR  │───▶│ 大模型    │
│ GUI界面 │    │ 框选+标定 │    │ GPU本地识别│    │ 答案推理  │
└─────────┘    └──────────┘    └───────────┘    └───────────┘
                                                       │
                                              ┌────────▼────────┐
                                              │  pyautogui 自动 │
                                              │  点击选项+下一题 │
                                              └─────────────────┘
```

- **截图**：PyQt5 桌面抓取，支持拖拽框选、桌面预览、坐标标定
- **OCR**：PaddleOCR 3.x + PaddlePaddle GPU（CUDA 12.6），支持 A-L 最多 12 个选项，含角度分类和图片预缩放
- **大模型**：OpenAI 兼容 API 格式，支持自定义 BaseURL / API Key / 模型名称 / 思考模式 / 角色身份
- **点击**：pyautogui 模拟鼠标操作，支持延迟设置和左上角 FailSafe 紧急停止
- **存储**：JSON 文件持久化（`%LOCALAPPDATA%`），支持题型预设、快捷键、浮动窗口配置

## 快速开始

### 第一步：安装依赖

```bash
pip install -r requirements.txt
```

如果你有 NVIDIA 显卡，强烈建议安装 GPU 版加速 OCR：

```bash
pip uninstall paddlepaddle -y
pip install paddlepaddle-gpu==3.3.1 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
```

### 第二步：获取免费 API Key

访问 **[七牛云 AI 推理平台](https://portal.qiniu.com/ai-inference/model)**，注册账号后在控制台创建 API Key，选择 `z-ai/glm-4.5-air-free` 模型（学生免费额度足够日常使用）。

### 第三步：启动

```bash
python main.pyw    # 无控制台黑窗（推荐）
python main.py     # 带控制台（调试用）
```

软件默认已填写七牛云的 API 地址和模型名称，你只需要填入自己的 API Key 即可。

### 第四步：开始答题

1. 在「LLM 设置」中填入 API Key，点击保存
2. 打开答题网页，回到软件点击「框选截图区域」
3. 标定选项 A/B/C/D... 和「下一题」按钮的位置
4. 点击「开始自动答题」或按 F9

## 快捷键

| 按键 | 功能 |
|------|------|
| F9 | 开始自动答题 |
| F10 | 暂停 / 继续 |
| F11 | 切换 OCR 模式 / 多模态模式 |
| F12 | 手动标记当前题为主观题 |

可在「快捷键」Tab 中自定义。

## 题型预设

软件支持保存多种题型的页面布局，一键切换。例如医学考试中：

- **A1 型题**：5 个选项，需标定 A-E 坐标
- **B 型配伍题**：选项区与题目区分离，需不同截图区域
- **X 型多选题**：多选模式，大模型会返回多个字母组合

切换预设后，选项数量、坐标和截图区域会自动更新。

## 打包为 EXE

```bash
# 单文件 EXE
pyinstaller main.spec

# 安装包（需要 Inno Setup）
# 用 Inno Setup Compiler 打开 installer.iss 编译即可
```

## 技术栈

- Python 3.13
- PyQt5（图形界面）
- PaddleOCR 3.6 + PaddlePaddle 3.3 GPU（本地 OCR）
- httpx（大模型 API 调用）
- pyautogui（鼠标模拟）
- keyboard（全局快捷键）
- PyInstaller + Inno Setup（打包）

## 致谢

水课快答站在以下开源项目的肩膀上：

- **[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)** — 百度飞桨团队出品的 OCR 引擎，提供本地高精度文字识别
- **[PaddlePaddle](https://github.com/PaddlePaddle/Paddle)** — 百度深度学习框架，支持 GPU 加速推理
- **[PyQt5](https://www.riverbankcomputing.com/software/pyqt/)** — Riverbank Computing 的 Qt Python 绑定，构建跨平台 GUI
- **[pyautogui](https://github.com/asweigart/pyautogui)** — Al Sweigart 开发的跨平台鼠标键盘自动化库
- **[httpx](https://github.com/encode/httpx)** — Encode 团队出品的现代 HTTP 客户端
- **[keyboard](https://github.com/boppreh/keyboard)** — BoppreH 的全局键盘钩子库
- **[PyInstaller](https://github.com/pyinstaller/pyinstaller)** — 将 Python 程序打包为独立可执行文件
- **[七牛云](https://www.qiniu.com/)** — 提供免费大模型推理 API，让学生零成本使用

感谢所有为开源事业贡献代码的开发者。

## 许可证

**[GNU Affero General Public License v3.0（AGPL-3.0）](https://www.gnu.org/licenses/agpl-3.0.html)**

任何使用、修改或分发本项目的第三方，无论是否通过网络提供服务，都必须以相同协议完全开源其全部源代码。
