"""
鼠标模拟控制模块
- 封装 pyautogui，实现：
    1) 根据坐标模拟点击选项
    2) 模拟点击"下一题"按钮
    3) 支持最多12个命名选项（A-L 或自定义名称）
    4) 单线程顺序执行，可设置延迟
"""
import time
import logging
import re
import pyautogui

logger = logging.getLogger(__name__)

# 安全设置：操作前等待（防止误操作）
pyautogui.FAILSAFE = True   # 鼠标移到左上角触发 FailSafeException
pyautogui.PAUSE = 0.05     # 每个 pyautogui 操作间隔 50ms


class MouseController:
    """
    鼠标控制器
    所有操作均为同步阻塞式，单线程顺序执行
    """

    # 默认标签映射（A-L 对应 0-11）
    DEFAULT_LABEL_MAP = {
       chr(ord("A") + i): i for i in range(12)
    }
    # 支持中文选项标签
    CHINESE_LABEL_MAP = {
        "一": 0, "二": 1, "三": 2, "四": 3,
        "五": 4, "六": 5, "七": 6, "八": 7,
        "九": 8, "十": 9, "十一": 10, "十二": 11,
    }

    def __init__(self, click_delay_ms: int = 200):
        self.click_delay_ms = click_delay_ms

    # ========== 核心点击 ==========
    def click(self, x: int, y: int, delay_ms: int | None = None):
        d = delay_ms if delay_ms is not None else self.click_delay_ms
        logger.info(f"点击坐标: ({x}, {y})")
        pyautogui.click(x, y)
        if d > 0:
            time.sleep(d / 1000.0)

    def double_click(self, x: int, y: int, delay_ms: int | None = None):
        d = delay_ms if delay_ms is not None else self.click_delay_ms
        logger.info(f"双击坐标: ({x}, {y})")
        pyautogui.doubleClick(x, y)
        if d > 0:
            time.sleep(d / 1000.0)

    def right_click(self, x: int, y: int, delay_ms: int | None = None):
        d = delay_ms if delay_ms is not None else self.click_delay_ms
        logger.info(f"右键点击: ({x}, {y})")
        pyautogui.rightClick(x, y)
        if d > 0:
            time.sleep(d / 1000.0)

    # ========== 答题动作 ==========
    def click_option(self, option_pos: dict | tuple, delay_ms: int | None = None):
        """
        点击单个选项
        option_pos: {"name": "A", "x": x, "y": y} 或 (x, y) 元组
        """
        if isinstance(option_pos, dict):
            x, y = option_pos["x"], option_pos["y"]
        else:
            x, y = option_pos
        self.click(x, y, delay_ms)

    def click_options(self, option_positions: list, delay_ms: int | None = None):
        for pos in option_positions:
            self.click_option(pos, delay_ms)

    def click_next(self, next_pos: dict | tuple | None, delay_ms: int | None = None):
        if next_pos is None:
            return
        if isinstance(next_pos, dict):
            x, y = next_pos["x"], next_pos["y"]
        elif isinstance(next_pos, (list, tuple)):
            x, y = next_pos[0], next_pos[1]
        else:
            return
        self.click(x, y, delay_ms)

    # ========== 答题主流程 ==========
    def answer_question(
        self,
        answer_labels: list[str],
        option_positions: list[dict],   # [{"name": "A", "x": x, "y": y}, ...]
        next_pos: dict | tuple | None,
        delay_ms: int | None = None,
    ) -> bool:
        """
        根据题目答案自动点击正确选项，然后点击下一题

        参数:
            answer_labels: 正确答案标签列表，如 ["A"] 或 ["A", "C"]
            option_positions: 选项配置列表，每个元素为
                              {"name": "A", "x": x, "y": y}
            next_pos: "下一题"按钮坐标
            delay_ms: 覆盖默认延迟

        返回:
            True 成功，False 失败
        """
        if not answer_labels:
            logger.warning("answer_question: 答案标签为空")
            return False

        # 构建 name→坐标 映射（忽略大小写）
        name_to_pos = {}
        for opt in option_positions:
            name = str(opt.get("name", "")).strip().upper()
            if name:
                name_to_pos[name] = opt

        # 点击正确选项
        clicked = []
        for lbl in answer_labels:
            lbl_upper = lbl.strip().upper()
            # 先尝试直接匹配
            if lbl_upper in name_to_pos:
                pos = name_to_pos[lbl_upper]
                self.click_option(pos, delay_ms)
                clicked.append(lbl_upper)
            else:
                # 尝试解析为 A-L 索引
                idx = self._label_to_index(lbl_upper)
                if idx is not None and idx < len(option_positions):
                    pos = option_positions[idx]
                    self.click_option(pos, delay_ms)
                    clicked.append(lbl_upper)
                else:
                    logger.warning(f"answer_question: 无法解析答案标签 '{lbl}'，跳过")

        if not clicked:
            logger.error("answer_question: 没有成功点击任何选项")
            return False

        # 点击下一题
        if next_pos is not None:
            time.sleep(0.3)
            self.click_next(next_pos, delay_ms)

        return True

    @staticmethod
    def _label_to_index(label: str) -> int | None:
        """将标签字符串转为索引（A→0, B→1, ... L→11）"""
        if not label:
            return None
        label = label.strip().upper()
        # 单字母 A-L
        if len(label) == 1 and "A" <= label <= "L":
            return ord(label) - ord("A")
        # 中文数字
        chinese_map = {"一": 0, "二": 1, "三": 2, "四": 3,
                       "五": 4, "六": 5, "七": 6, "八": 7,
                       "九": 8, "十": 9}
        if label in chinese_map:
            return chinese_map[label]
        return None

    # ========== 解析答案字符串 → 标签列表 ==========
    @staticmethod
    def parse_answer_labels(answer_str: str, max_options: int = 12) -> list[str]:
        """
        将 LLM 返回的答案字符串解析为标签列表
        支持: "A" / "AC" / "A,C" / "正确" / "错误" / "要点1;要点2"
        """
        if not answer_str:
            return []

        s = answer_str.strip()

        # 判断题
        if s in ("正确", "对", "TRUE", "T", "√", "是"):
            return ["正确"]
        if s in ("错误", "错", "FALSE", "F", "×", "X", "否"):
            return ["错误"]

        # 去除常见分隔符
        import re
        s = re.sub(r"[\s,，、/]+", "", s.upper())

        # 只保留 A-L（最多12个选项）
        valid_labels = set(chr(ord("A") + i) for i in range(max_options))
        labels = [c for c in s if c in valid_labels]

        # 去重保序
        seen = set()
        result = []
        for c in labels:
            if c not in seen:
                seen.add(c)
                result.append(c)
        return result

    # ========== 设置 ==========
    def set_click_delay(self, ms: int):
        self.click_delay_ms = max(0, ms)

    def get_click_delay(self) -> int:
        return self.click_delay_ms

    # ========== 坐标工具 ==========
    def get_current_mouse_pos(self) -> tuple[int, int]:
        return pyautogui.position()


# ========== 异步执行封装（供 GUI 线程调用）==========

from PyQt5.QtCore import QObject, pyqtSignal, QThread


class AnswerWorker(QThread):
    """
    后台线程执行答题动作，避免界面卡顿
    finished(success: bool): 完成信号
    error(msg: str): 错误信号
    log(msg: str): 日志信号
    """
    finished = pyqtSignal(bool)
    error = pyqtSignal(str)
    log = pyqtSignal(str)

    def __init__(
        self,
        controller: MouseController,
        answer_str: str,
        option_positions: list,   # [{"name":..., "x":..., "y":...}, ...]
        next_pos: dict | tuple | None,
        max_options: int = 12,
    ):
        super().__init__()
        self.controller = controller
        self.answer_str = answer_str
        self.option_positions = option_positions
        self.next_pos = next_pos
        self.max_options = max_options

    def run(self):
        try:
            labels = MouseController.parse_answer_labels(self.answer_str, self.max_options)
            self.log.emit(f"解析答案: {labels}")

            if not labels:
                self.error.emit(f"无法解析答案: {self.answer_str}")
                self.finished.emit(False)
                return

            ok = self.controller.answer_question(
                answer_labels=labels,
                option_positions=self.option_positions,
                next_pos=self.next_pos,
            )
            self.log.emit(f"答题动作{'成功' if ok else '失败'}")
            self.finished.emit(ok)
        except Exception as e:
            self.error.emit(str(e))
            self.finished.emit(False)
