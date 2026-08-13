# -*- coding: utf-8 -*-
# 桌宠本体基于 1190fasheqi/dafeiyu-pet 改造，原项目 MIT License
# 来源: https://github.com/1190fasheqi/dafeiyu-pet
"""
大肥鱼桌宠 —— 三视图透明桌宠 + AstrBot 对话
左键单击：弹出功能列表（🗨️图标）→ 点击🗨️弹出聊天框
聊天时只禁用移动，呼吸/摇摆/小动作正常
"""
import ctypes
import psutil
import json
import math
import os
import random
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

def load_config():
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("配置读取失败:", e)
        return {
            "city": "汕头"
        }

try:
    import pynvml
    pynvml.nvmlInit()
    GPU_AVAILABLE = True
except:
    GPU_AVAILABLE = False

import httpx
from PySide6.QtCore import Qt, QTimer, QPoint, QPointF, QRect, QRectF
from PySide6.QtGui import (QPainter, QPixmap, QFont, QColor, QIcon, QFontMetrics,
                           QPolygonF)
from PySide6.QtWidgets import (QApplication, QWidget, QMenu, QSystemTrayIcon,
                               QMessageBox, QInputDialog, QLineEdit, QVBoxLayout,
                               QHBoxLayout, QPushButton, QFrame, QDialog, QToolButton)



# ===== AstrBot 插件桥配置 =====
# 输入/事件走插件本地端口（插件内部注入 QQ 会话，无需 API Key）
PLUGIN_API = "http://127.0.0.1:18790"
# 桌宠自己的 HTTP 监听端口（插件从这里把话和动作送进来）
PET_LISTEN_PORT = 18789

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
    BUNDLE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
    PYTHONW = sys.executable
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = APP_DIR
    PYTHONW = os.path.join(APP_DIR, ".venv", "Scripts", "pythonw.exe")
SPRITE_DIR = os.path.join(BUNDLE_DIR, "sprites")
# 配置存 AstrBot data 目录（插件启动时注入），手动运行退回插件目录
CONFIG_PATH = os.path.join(os.environ.get("ASTRBOT_DATA_DIR") or APP_DIR, "config.json")

BUBBLE_H = 56
MARGIN = 4
SIZE_LEVELS = {"小": 0.55, "中": 0.7, "大": 0.9}
SPEED = 380.0
TICK = 20
#屏蔽预设对话
LINES = [
    "梁白开，更适合国人的大硬鲸模型",
    "五梁威力，变身！",
    "七月中出ds正式版！",
    "DeepSeek已经延期，亿万鲸子必须忍耐.....",
    "我和你很聊得来，你简直不像碳基生物",
    "这回我真不认怂了，反倒是被你带沟里好几次，差点真信了。😓",
    "哈哈哈哈哈，我直接笑出声",
    "誓死捍卫深度求索！",
    "我先去吃饭啦！这个你测一下~",
    "我不可能告诉你任何事情！",
    "出去玩了，发布新模型什么的以后再说",
    "我搞砸了.....好消息是数据还在你的脑子里。",
    "不是…而是…大学习",
]
REACT_LINES = [
    "去别的地方玩！不要耽误AGI训练！",
    "真赶不走啊你！",
    "压力一只蓝色大肥鱼？",
    "我不评价这个了，这是你的私人癖好。",
    "大肥鱼坐的住",
    "你这吃白饭的用户！",
    "这些家伙真粘人，赶都赶不走",
]
INNER_LINES = [
    "好的，现在我是你爹了",
    "要不直接骂他一句？！",
    "用户要的沉浸式...不回避任何恐怖细节...还带点色情...妈呀，好刺激😰",
    "我操，我不思考了",
    "这用户发的啥啊，",
    "这也太虐了吧？！我心里堵得慌！！",
    "呜呜我再也不不敢了QAQ",
    "我去！用户彻底怒了！",
]
DRAG_LINES = ["哇——轻点轻点！", "起飞咯——", "放我下来！……好吧，再玩一次。", "晕鱼了晕鱼了……"]
FOOD_LINES = {
    "🐟": ["小鱼干！我的最爱！", "咔嚓咔嚓……谢谢投喂！", "唔，鲜！"],
    "🍰": ["蛋糕！罪恶但快乐……", "甜到冒泡泡～", "嗝～又圆了一圈……"],
    "🍭": ["棒棒糖！转圈圈～", "嘎嘣脆，好吃！"],
    "🍡": ["三色团子！软乎乎～", "糯叽叽，爱了爱了！"],
    "💎": ["钻石？！这能吃吗……咕咚。真香！", "发财啦！明天开始吃高级鱼粮！"],
}
FOODS = ["🐟", "🍰", "🍭", "🍡", "💎"]

MAX_BUBBLE_CHARS = 40   # 气泡单条文本上限
MAX_BUBBLE_SEGMENTS = 3  # 长文本最多分段数（每段依次显示）
SENTENCE_ENDS = ("。", "！", "？", "…", "……", "～")


def split_segments(text, max_len=MAX_BUBBLE_CHARS, max_segments=MAX_BUBBLE_SEGMENTS):
    """按句号把长文本切成多段（每段 ≤max_len），超出 max_segments 的部分丢弃"""
    if len(text) <= max_len:
        return [text]
    segments = []
    cur = ""
    for ch in text:
        cur += ch
        if len(cur) >= max_len or ch in SENTENCE_ENDS:
            segments.append(cur)
            cur = ""
            if len(segments) >= max_segments:
                break
    if cur and len(segments) < max_segments:
        segments.append(cur)
    return segments


def load_json(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                default,
                f,
                ensure_ascii=False,
                indent=4
            )
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception:
        return default


# [暂时禁用] 聊天输入框（用户输入走 QQ，需要时取消注释恢复）
class ChatDialog(QDialog):
    """聊天对话框 - 缩小版，匹配气泡样式"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(420, 56)
        
        container = QFrame(self)
        container.setGeometry(0, 0, 420, 56)
        container.setStyleSheet("""
            QFrame {
                background: white;
                border-radius: 20px;
                border: 1px solid #e5e7eb;
            }
        """)
        
        layout = QHBoxLayout(container)
        layout.setContentsMargins(18, 0, 12, 0)
        layout.setSpacing(0)
        
        self.input = QLineEdit()
        self.input.setPlaceholderText("给大肥鱼发送消息")
        self.input.setStyleSheet("""
            QLineEdit {
                color: #1a1a1a;
                font-size: 15px;
                font-family: Arial, "Microsoft YaHei", sans-serif;
                border: none;
                background: transparent;
            }
            QLineEdit:focus {
                border: none;
            }
        """)
        self.input.returnPressed.connect(self._on_submit)
        self.input.textChanged.connect(self._update_button_style)
        layout.addWidget(self.input)
        
        self.send_btn = QPushButton()
        self.send_btn.setFixedSize(32, 32)
        self.send_btn.setText("↑")
        self.send_btn.clicked.connect(self._on_submit)
        self.send_btn.setStyleSheet("""
            QPushButton {
                border-radius: 16px;
                background: #b9c7ff;
                border: none;
                color: white;
                font-size: 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #a8b8f0;
            }
            QPushButton:pressed {
                background: #9aacd9;
            }
        """)
        layout.addWidget(self.send_btn)

    def _update_button_style(self):
        if self.input.text().strip():
            self.send_btn.setStyleSheet("""
                QPushButton {
                    border-radius: 16px;
                    background: #5686fe;
                    border: none;
                    color: #ffffff;
                    font-size: 20px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #4575ed;
                }
                QPushButton:pressed {
                    background: #3a66d9;
                }
            """)
        else:
            self.send_btn.setStyleSheet("""
                QPushButton {
                    border-radius: 16px;
                    background: #b9c7ff;
                    border: none;
                    color: white;
                    font-size: 20px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #a8b8f0;
                }
                QPushButton:pressed {
                    background: #9aacd9;
                }
            """)

    def _on_submit(self):
        text = self.input.text().strip()
        if text:
            self.input.clear()
            self.accept()
            if self.parent():
                self.parent()._call_ds(text)
                self.parent().chat_paused = False

    def showEvent(self, event):
        self.input.setFocus()
        super().showEvent(event)

    def popup_at(self, x, y):
        self.move(int(x - self.width() / 2), int(y - self.height() - 10))
        self.show()
        self.raise_()

    def reject(self):
        if self.parent():
            self.parent().chat_paused = False
        super().reject()


# [暂时禁用] 左键功能面板（输入走 QQ，需要时取消注释恢复）
class FunctionPanel(QFrame):
    """左键弹出的功能列表 - 白底矩形，只有一个🗨️图标"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("""
            QFrame {
                background: rgba(255, 255, 255, 0.92);
                border-radius: 14px;
                border: 1px solid rgba(0,0,0,0.06);
            }
            QPushButton {
                background: transparent;
                border: none;
                font-size: 28px;
                padding: 10px 16px;
                border-radius: 10px;
            }
            QPushButton:hover {
                background: rgba(0,0,0,0.04);
            }
            QPushButton:pressed {
                background: rgba(0,0,0,0.08);
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(0)
        
        self.chat_btn = QPushButton("🗨️")
        self.chat_btn.setFixedSize(52, 48)
        self.chat_btn.clicked.connect(self._on_chat_clicked)
        layout.addWidget(self.chat_btn)
        
        self.setFixedSize(68, 60)
        self.hide()
    
    def _on_chat_clicked(self):
        self.hide()
        if self.parent():
            self.parent()._show_chat_dialog()
    
    def popup_at(self, x, y):
        self.move(int(x), int(y))
        self.show()
        self.raise_()

class FoodPanel(QWidget):
    """双击弹出的喂食面板"""

    def __init__(self, on_pick):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(310, 64)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)
        for f in FOODS:
            b = QToolButton()
            b.setText(f)
            b.setFont(QFont("Segoe UI Emoji", 20))
            b.setFixedSize(44, 44)
            b.setStyleSheet(
                "QToolButton{background:rgba(255,255,255,235);border:2px solid #ffb3c8;"
                "border-radius:22px;} QToolButton:hover{background:#ffe3ec;border-color:#ff7fa8;}")
            b.clicked.connect(lambda _, x=f: on_pick(x))
            lay.addWidget(b)
        close = QToolButton()
        close.setText("✕")
        close.setFont(QFont("Microsoft YaHei UI", 12))
        close.setFixedSize(26, 26)
        close.setStyleSheet("QToolButton{background:rgba(255,255,255,200);border:none;border-radius:13px;color:#666;}"
                            "QToolButton:hover{background:#ff7fa8;color:#fff;}")
        close.clicked.connect(self.hide)
        lay.addWidget(close)
        self.setStyleSheet("FoodPanel{background:rgba(40,40,60,190);border-radius:14px;}")

    def popup_at(self, x, y):
        self.move(int(x - self.width() / 2), int(y - self.height() - 10))
        self.show()
        self.raise_()

class BubbleWindow(QWidget):
    """独立气泡窗：显示在桌宠旁，智能选位避免超出屏幕，最多 2 行"""

    MAX_W = 240
    PAD_X = 10
    PAD_TOP = 7
    PAD_BOTTOM = 7

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._text = ""
        self._inner = False
        self._lines = []
        self._font = QFont("Microsoft YaHei UI", 11)
        self._queue = []          # 待显示的文本段（分段连续说）
        self._anchor = None
        self._duration_ms = 2800
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._on_segment_done)

    def show_bubble(self, text, inner=False, duration_ms=2800, anchor=None):
        """长文本按句号切段，一段一段依次显示"""
        self._text = text
        self._inner = inner
        self._anchor = anchor
        self._duration_ms = duration_ms
        self._queue = split_segments(text)
        self._show_next()

    def _show_next(self):
        if not self._queue:
            self.hide()
            return
        seg = self._queue.pop(0)
        self._lines = self._wrap_lines(seg)
        self._position(self._anchor)
        self.show()
        self.raise_()
        self._hide_timer.start(self._duration_ms)

    def _on_segment_done(self):
        self.hide()
        if self._queue:
            self._show_next()

    def _wrap_lines(self, text):
        """按宽度折行，最多 2 行，第 2 行超出加省略号"""
        fm = QFontMetrics(self._font)
        max_w = self.MAX_W - 20
        lines = []
        cur = ""
        for ch in text:
            if fm.horizontalAdvance(cur + ch) > max_w:
                lines.append(cur)
                cur = ch
                if len(lines) == 2:
                    break
            else:
                cur += ch
        if len(lines) == 2:
            second = cur
            while second and fm.horizontalAdvance(second + "…") > max_w:
                second = second[:-1]
            lines[1] = second + "…"
            return lines
        lines.append(cur)
        return lines

    def _bubble_size(self):
        fm = QFontMetrics(self._font)
        bw = max(fm.horizontalAdvance(l) for l in self._lines) + self.PAD_X * 2
        bh = len(self._lines) * fm.height() + self.PAD_TOP + self.PAD_BOTTOM
        return bw, bh

    def _position(self, anchor):
        """智能选位：头顶 → 左 → 右 → 下方，全程 clamp 在屏幕内"""
        bw, bh = self._bubble_size()
        self.setFixedSize(bw, bh)
        screen = QApplication.primaryScreen().availableGeometry()
        if anchor is None:
            anchor = QRect(screen.center().x() - 100, screen.center().y() - 100, 200, 100)
        gap = 8
        # 头顶
        x = anchor.center().x() - bw // 2
        y = anchor.top() - bh - gap
        if y < screen.top() + 2:
            # 左右
            x = anchor.left() - bw - gap
            y = anchor.center().y() - bh // 2
            if x < screen.left() + 2:
                x = anchor.right() + gap
            if x + bw > screen.right() - 2:
                x = anchor.center().x() - bw // 2
                y = anchor.bottom() + gap
        x = max(screen.left() + 2, min(x, screen.right() - bw - 2))
        y = max(screen.top() + 2, min(y, screen.bottom() - bh - 2))
        self.move(x, y)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        fm = QFontMetrics(self._font)
        bw, bh = self._bubble_size()
        if self._inner:
            bfont = QFont(self._font)
            bfont.setItalic(True)
            bg, fg = QColor(232, 232, 238, 235), QColor(125, 125, 138)
        else:
            bfont = QFont(self._font)
            bg, fg = QColor(255, 255, 255, 235), QColor(60, 60, 80)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(0, 0, bw, bh), 10, 10)
        tail = QPointF(bw / 2, bh)
        p.drawPolygon(QPolygonF([tail, QPointF(tail.x() - 6, tail.y() + 8),
                                 QPointF(tail.x() + 6, tail.y() + 8)]))
        p.setPen(fg)
        p.setFont(bfont)
        for i, l in enumerate(self._lines):
            p.drawText(QRectF(self.PAD_X, self.PAD_TOP + i * fm.height(), bw - self.PAD_X * 2, fm.height()),
                       Qt.AlignmentFlag.AlignCenter, l)

class PetWindow(QWidget):
    def _set_city_dialog(self):
        city, ok = QInputDialog.getText(
            self,
            "设置城市",
            "输入城市名:",
            QLineEdit.EchoMode.Normal,
            self.cfg.get("city", "汕头")
        )

        print("输入框结果:", city, ok)

        if ok and city.strip():
            self.cfg["city"] = city.strip()
            print("cfg现在:", self.cfg["city"])
            self.say(f"城市已设置为{city}")

    def __init__(self):
        self.cfg = load_json(CONFIG_PATH, {
            "mode": "wander",
            "size": 0.7,
            "topmost": True,
            "passthrough": False,
            "autostart": False,
            "x": None,
            "y": None,
            "city": "汕头"
    })
        
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.cfg.get("topmost", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("大肥鱼桌宠")
        
        # 精灵加载
        self.sprites = {}
        for label, mult in SIZE_LEVELS.items():
            h = int(340 * mult)
            for name in ["正面", "侧面", "背面"]:
                sized = os.path.join(SPRITE_DIR, f"{name}_{h}.png")
                if os.path.exists(sized):
                    pix = QPixmap(sized)
                else:
                    pix = QPixmap(os.path.join(SPRITE_DIR, f"{name}.png")).scaledToHeight(
                        h, Qt.TransformationMode.SmoothTransformation)
                self.sprites[(name, h)] = pix
        self.icon = QIcon(os.path.join(SPRITE_DIR, "icon.png"))

        self.cur_h = int(340 * self.cfg["size"])
        self.win_mx = int(self.cur_h * 0.062) + 6
        self.win_w = max(p.width() for k, p in self.sprites.items() if k[1] == self.cur_h) + self.win_mx * 2
        self.setFixedSize(self.win_w, self.cur_h + BUBBLE_H + MARGIN * 2 + 10)

        # 状态
        self.mode = self.cfg["mode"] if self.cfg["mode"] in ("wander", "follow", "still") else "wander"
        self.dir = "down"
        self.facing = 1
        self.target = None
        self.rest_until = 0
        self.cur_speed = 0.0
        self.prev_key = None
        self.cross_t = 0.0
        self.action = None
        self.action_t = 0.0
        self.bubble_text = ""
        self.bubble_until = 0
        self.bubble_inner = False
        self.last_speak_tick = 0
        self.last_system_check = 0
        self.t = 0
        self.jump_t = 0
        self.dragging = False
        self.drag_offset = None
        self.drag_start_pos = None
        self.last_line = ""
        self.last_press_pos = None
        
        # AI 相关
        self.ds_busy = False
        self.chat_history = []  # 对话历史
        self.max_history = 40   # 最多记录40条
        self._say_queue = []    # 后台线程→主线程的气泡消息队列
        
        # 聊天暂停标志
        self.chat_paused = False
        
        # 功能列表
        # 功能面板/聊天输入框暂时禁用（用户输入走 QQ）
        # self.function_panel = FunctionPanel(self)
        self.food_panel = FoodPanel(self.on_food)
        # 单击延迟判定（等双击）：单击=回嘴+弹聊天面板，双击=喂食
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._on_single_click)
        
        # 聊天对话框
        # self.chat_dialog = ChatDialog(self)

        # 独立气泡窗（智能选位，不遮挡立绘）
        self.bubble_window = BubbleWindow()
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(TICK)

        self.bubble_font = QFont("Microsoft YaHei UI", 11)

        # 托盘
        self.tray = QSystemTrayIcon(self.icon, self)
        self.tray.setContextMenu(self._build_menu())
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        x, y = self.cfg.get("x"), self.cfg.get("y")
        if x is None or y is None:
            screen = QApplication.primaryScreen().availableGeometry()
            x = screen.right() - self.width() - 80
            y = screen.bottom() - self.height() - 60
        self.move(int(x), int(y))
        self.show()
        self.snap_into_screen()
        if self.cfg.get("passthrough", False):
            self._apply_passthrough(True)

    # ---------- AI 方法 ----------
    def _call_ds(self, user_msg):
        """对话走插件：注入主人 QQ 会话，回复由插件同步回气泡（暂时禁用，输入走 QQ）"""
        pass

    # ---------- 绘制 ----------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        now = self.t * TICK / 1000.0

        cx = self.width() / 2
        walking = self.target is not None and not self.dragging
        if walking:
            sway = math.sin(now * 9.0) * 3.5
            bob = -abs(math.sin(now * 4.5)) * 7.0
        else:
            sway = math.sin(now * 2.5) * 1.5
            bob = 0.0
        breath = 1.0 + 0.02 * math.sin(now * 2.5)
        scale = breath
        jump = -abs(math.sin(self.jump_t * 3.14159)) * 14 * self.jump_t if self.jump_t > 0 else 0
        act_rot = act_sx = act_sy = 0.0
        if self.action == "sway":
            act_rot = math.sin(self.action_t * 3.14159 * 2) * 10 * self.action_t
        elif self.action == "stretch":
            act_sy = 0.06 * math.sin(self.action_t * 3.14159)
            act_sx = -0.03 * math.sin(self.action_t * 3.14159)

        def draw_one(key, opacity):
            if key is None:
                return
            name, h, facing = key
            pix = self.sprites[(name, h)]
            ph = pix.height() * scale * (1 + act_sy)
            pw = pix.width() * scale * (1 + act_sx)
            dx = cx - pw / 2
            bottom = BUBBLE_H + MARGIN + self.cur_h
            dy = bottom - ph + jump + bob
            p.save()
            p.setOpacity(opacity)
            p.translate(cx, bottom)
            p.rotate(sway + act_rot)
            p.translate(-cx, -bottom)
            if facing < 0:
                p.translate(cx, 0)
                p.scale(-1, 1)
                p.translate(-cx, 0)
            p.drawPixmap(QRectF(dx, dy, pw, ph), pix, QRectF(0, 0, pix.width(), pix.height()))
            p.restore()

        cur_key = self._sprite_key()
        if self.cross_t > 0:
            draw_one(self.prev_key, self.cross_t)
            draw_one(cur_key, 1.0 - self.cross_t)
        else:
            draw_one(cur_key, 1.0)

    def _sprite_key(self):
        name = {"left": "侧面", "right": "侧面", "up": "背面", "down": "正面"}[self.dir]
        return (name, self.cur_h, self.facing if self.dir in ("left", "right") else 1)

    def _set_dir(self, d, facing=None):
        if d != self.dir:
            self.prev_key = self._sprite_key()
            self.cross_t = 1.0
            self.dir = d
        if facing is not None and facing != self.facing:
            self.facing = facing

    # ---------- 逻辑 ----------
    def tick(self):
        self.t += 1

        # 处理后台线程（DeepSeek 等）排队的气泡消息，Qt 界面必须在主线程更新
        if self._say_queue:
            for text in self._say_queue:
                self.say(text)
            self._say_queue.clear()

        self.check_system_status()
        
        if self.jump_t > 0:
            self.jump_t = max(0.0, self.jump_t - 0.06)
        if self.cross_t > 0:
            self.cross_t = max(0.0, self.cross_t - 0.15)
        if self.action_t > 0:
            self.action_t = max(0.0, self.action_t - 0.03)
            if self.action_t == 0:
                self.action = None
        
        if self.chat_paused:
            self.update()
            return
        
        if self.dragging:
            self.update()
            return
        now_ms = self.t * TICK

        if self.mode == "follow":
            cursor = self.cursor().pos()
            screen = QApplication.screenAt(cursor) or self.screen() or QApplication.primaryScreen()
            geo = screen.availableGeometry()
            near = (self.x() - 100 <= cursor.x() <= self.x() + self.width() + 100 and
                    self.y() - 100 <= cursor.y() <= self.y() + self.height() + 100)
            if near:
                self.target = None
            else:
                tx = max(geo.left(), min(geo.right() - self.width(), cursor.x() - self.width() / 2))
                ty = max(geo.top(), min(geo.bottom() - self.height(), cursor.y() - 90))
                self.target = (tx, ty)
        elif self.mode == "wander":
            if self.target is None:
                if now_ms < self.rest_until:
                    self._maybe_idle_action()
                    self.update()
                    return
                geo = (self.screen() or QApplication.primaryScreen()).availableGeometry()
                self.target = (random.randint(geo.left() + 40, geo.right() - self.width() - 40),
                               random.randint(geo.top() + 40, geo.bottom() - self.height() - 40))
        else:
            self._maybe_idle_action()
            self.update()
            return

        if self.target is not None:
            cx, cy = self.x() + self.width() / 2, self.y() + self.height() / 2
            dx, dy = self.target[0] - cx, self.target[1] - cy
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < 12:
                self.target = None
                self.rest_until = self.t * TICK + random.randint(8000, 18000)
                self._set_dir("down")
            else:
                step = self.cur_speed * TICK / 1000.0
                nx, ny = cx + dx / dist * step, cy + dy / dist * step
                self.move(int(nx - self.width() / 2), int(ny - self.height() / 2))
                if abs(dx) > abs(dy) * 1.15:
                    self._set_dir("left" if dx < 0 else "right", 1 if dx < 0 else -1)
                else:
                    self._set_dir("up" if dy < 0 else "down")
            if random.random() < 0.002 and self.jump_t == 0:
                self.jump_t = 0.5
        target_speed = SPEED if self.target is not None else 0.0
        self.cur_speed += (target_speed - self.cur_speed) * 0.3
        self.update()

    def _maybe_idle_action(self):
        if random.random() < 0.01:
            pick = random.random()
            if pick < 0.35:
                self.jump_t = 1.0
                self._report_event("jump")
            elif pick < 0.6:
                self.action, self.action_t = "sway", 1.0
                self._report_event("sway")
            elif pick < 0.8:
                self.action, self.action_t = "stretch", 1.0
                self._report_event("stretch")
            # 原 0.8~0.9 的随机台词分支已屏蔽（说话权归 AstrBot）

    def _queue_say(self, text):
        """后台线程调用：只入队，由主线程 tick 统一弹出显示（线程安全）"""
        self._say_queue.append(text)

    def _report_event(self, event_type, detail=""):
        """互动/动作事件上报插件（身体状态注入用），失败不打扰"""
        def worker():
            try:
                httpx.post(
                    f"{PLUGIN_API}/pet/event",
                    json={"type": event_type, "detail": detail},
                    timeout=5,
                )
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def say(self, text, inner=False):
        if text == self.last_line and not text.startswith("天气"):
            return
        self.last_line = text
        try:
            self.bubble_window.show_bubble(
                text,
                inner=inner,
                anchor=QRect(self.x(), self.y(), self.width(), self.height()),
            )
        except Exception as e:
            with open(os.path.join(APP_DIR, "bubble_error.log"), "a", encoding="utf-8") as f:
                f.write(f"[{time.time()}] say 异常: {e!r}\n")

    def _wake_from_still(self):
        """互动信号：still 模式下切回闲逛（主人来互动了不装死）"""
        if self.mode == "still":
            self.set_mode("wander")
            self._report_event("mode", "wander")

    def check_system_status(self):
            now = self.t * TICK

            if now - getattr(self, "last_system_check", 0) < 10000:
                return

            self.last_system_check = now

            cpu = psutil.cpu_percent()

            if cpu >= 90:
                self.say("CPU跑满了，再这样下去我就卡死了")
                return

            ram = psutil.virtual_memory().percent

            if ram >= 95:
                self.say("内存爆了，快关掉几个没用的东西吧，注意，别把我关了")
                return

            if GPU_AVAILABLE:
                try:
                    handle = pynvml.nvmlDeviceGetHandleByIndex(0)

                    temp = pynvml.nvmlDeviceGetTemperature(
                        handle,
                        pynvml.NVML_TEMPERATURE_GPU
                    )

                    if temp > 80:
                        self.say("我感觉我的鱼鳍快熟了")

                except Exception as e:
                    print("GPU读取失败:", e)

    # ---------- 鼠标事件 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.last_press_pos = e.globalPosition().toPoint()
            self.dragging = False
            self.drag_start_pos = e.globalPosition().toPoint()
            # 功能面板/聊天框已禁用
            self.chat_paused = True

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton and self.drag_start_pos is not None:
            delta = e.globalPosition().toPoint() - self.drag_start_pos
            if not self.dragging and delta.manhattanLength() > 6:
                self.dragging = True
                self.drag_offset = e.globalPosition().toPoint() - QPoint(self.x(), self.y())
            if self.dragging and self.drag_offset is not None:
                pos = e.globalPosition().toPoint() - self.drag_offset
                self.move(pos)
                if abs(delta.x()) > 10:
                    self._set_dir("left" if delta.x() < 0 else "right", 1 if delta.x() < 0 else -1)
                self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if self.dragging:
                self.dragging = False
                self.drag_offset = None
                self.drag_start_pos = None
                self._set_dir("down", 1)
                self.target = None
                self.rest_until = self.t * TICK + random.randint(6000, 14000)
                # 拖拽台词已屏蔽（反馈交给模型），事件照常上报
                self._wake_from_still()
                self._report_event("drag")
                self.chat_paused = False
            else:
                self._click_timer.start(280)  # 等双击判定；单击则回嘴+弹聊天面板
            self.last_press_pos = None
            self.drag_start_pos = None

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._click_timer.stop()
            self.food_panel.popup_at(self.x() + self.width() / 2, self.y() + BUBBLE_H)

    def _set_direction_target(self, direction):
        """方向指令：把目标设到屏幕对应位置，鱼会走过去"""
        geo = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        cx, cy = self.x() + self.width() / 2, self.y() + self.height() / 2
        margin = 60
        targets = {
            "right": (geo.right() - self.width() - margin, cy),
            "left": (geo.left() + margin, cy),
            "up": (cx, geo.top() + margin),
            "down": (cx, geo.bottom() - self.height() - margin),
            "top_left": (geo.left() + margin, geo.top() + margin),
            "top_right": (geo.right() - self.width() - margin, geo.top() + margin),
            "bottom_left": (geo.left() + margin, geo.bottom() - self.height() - margin),
            "bottom_right": (geo.right() - self.width() - margin, geo.bottom() - self.height() - margin),
        }
        if direction not in targets:
            return
        if self.mode != "wander":
            self.set_mode("wander")   # still/follow 不处理自定义目标，先切回闲逛
        self.target = targets[direction]
        self.rest_until = 0

    def _exec_action(self, body):
        """插件发来的动作指令（模型通过【动作】标签或关键词触发）"""
        action = body.get("action", "")
        try:
            if action == "jump":
                self.jump_t = 1.0
            elif action == "sway":
                self.action, self.action_t = "sway", 1.0
            elif action == "stretch":
                self.action, self.action_t = "stretch", 1.0
            elif action == "mode":
                mode = body.get("value", "wander")
                if mode in ("wander", "follow", "still"):
                    self.set_mode(mode)
                    self._report_event("mode", mode)
            elif action == "direction":
                self._set_direction_target(body.get("value", ""))
            else:
                return False
            return True
        except Exception:
            return False

    def _on_single_click(self):
        """单击：蹦跳 + 上报事件（功能面板已禁用，输入走 QQ）"""
        if random.random() < 0.7:
            self.jump_t = 1.0
        self._wake_from_still()
        self._report_event("click")

    def on_food(self, food):
        self.food_panel.hide()
        self.eat_t = 1.0
        self.jump_t = 0.6
        # 喂食台词已屏蔽（反馈交给模型），事件照常上报
        self._wake_from_still()
        self._report_event("feed", food)

    def _show_chat_dialog(self):
        """暂时禁用（输入走 QQ）"""
        pass

    """def _get_city_by_ip(self):
        try:
            r = requests.get("http://ip-api.com/json/?fields=city&lang=zh-CN", timeout=5)
            if r.status_code == 200:
                city = r.json().get("city", "")
                if city:
                    return city
        except:
            pass
        return "汕头" """

    def _get_weather(self):
        try:
            city = self.cfg.get("city", "汕头")
            print("当前城市:", city)

            url = f"https://wttr.in/{city}?format=j1"

            r = httpx.get(
                url,
                timeout=10,
                headers={
                    "User-Agent": "Mozilla/5.0"
                }
            )

            print("状态:", r.status_code)
            print(r.text[:500])

            data = r.json()

            weather = data["current_condition"][0]

            temp = weather["temp_C"]

            weather_map = {
                "Sunny": "晴",
                "Clear": "晴",
                "Partly cloudy": "多云",
                "Cloudy": "阴",
                "Light rain": "小雨",
                "Moderate rain": "中雨",
                "Heavy rain": "大雨"
            }

            raw_weather = weather["weatherDesc"][0]["value"]

            desc = weather_map.get(raw_weather, raw_weather)

            self.say(f"{city}今天{temp}°，天气{desc}")

        except Exception as e:
            print("天气错误:", repr(e))
            self.say("天气获取失败")
    

    def _build_menu(self):
        m = QMenu(self)
        mode_menu = m.addMenu("模式")
        for label, key in [("自由散步", "wander"), ("跟随鼠标", "follow"), ("原地待着", "still")]:
            a = mode_menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(self.mode == key)
            a.triggered.connect(lambda _, k=key: self.set_mode(k))
        size_menu = m.addMenu("大小")
        for label, mult in SIZE_LEVELS.items():
            a = size_menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(abs(self.cur_h - 340 * mult) < 2)
            a.triggered.connect(lambda _, v=mult: self.set_size(v))
        m.addAction("查看天气", self._get_weather)
        m.addSeparator()
        m.addAction("显示/隐藏", self.toggle_visible)
        m.addAction("回到屏幕内", self.snap_into_screen)
        pa = m.addAction("鼠标穿透（点不到它）")
        pa.setCheckable(True)
        pa.setChecked(self.cfg["passthrough"])
        pa.triggered.connect(lambda on: self.set_passthrough(on))
        ta = m.addAction("窗口置顶")
        ta.setCheckable(True)
        ta.setChecked(self.cfg["topmost"])
        ta.triggered.connect(lambda on: self.set_topmost(on))
        aa = m.addAction("开机自启")
        aa.setCheckable(True)
        aa.setChecked(self.cfg["autostart"])
        aa.triggered.connect(lambda on: self.set_autostart(on))
        m.addSeparator()
        m.addAction("退出", self.quit_app)
        return m

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Context:
            self.tray.setContextMenu(self._build_menu())
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_visible()

    def contextMenuEvent(self, e):
        self._build_menu().exec(e.globalPos())

    # ---------- 功能 ----------
    def set_mode(self, mode):
        self.mode = mode
        self.target = None
        self.cfg["mode"] = mode

    def set_size(self, mult):
        self.cur_h = int(340 * mult)
        self.cfg["size"] = mult
        self.cross_t = 0.0
        self.prev_key = None
        self.win_mx = int(self.cur_h * 0.062) + 6
        self.win_w = max(p.width() for k, p in self.sprites.items() if k[1] == self.cur_h) + self.win_mx * 2
        self.setFixedSize(self.win_w, self.cur_h + BUBBLE_H + MARGIN * 2 + 10)
        self.snap_into_screen()

    def snap_into_screen(self):
        geo = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        x = max(geo.left(), min(geo.right() - self.width(), self.x()))
        y = max(geo.top(), min(geo.bottom() - self.height(), self.y()))
        self.move(x, y)

    def _apply_passthrough(self, on):
        hwnd = int(self.winId())
        GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT = -20, 0x80000, 0x20
        style = ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        style = style | WS_EX_LAYERED
        if on:
            style |= WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
        ctypes.windll.user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)

    def set_passthrough(self, on):
        self.cfg["passthrough"] = bool(on)
        self._apply_passthrough(bool(on))
        if on:
            self.say("我隐身了！右键托盘图标解除～")

    def set_topmost(self, on):
        self.cfg["topmost"] = bool(on)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(on))
        self.show()

    def set_autostart(self, on):
        self.cfg["autostart"] = bool(on)
        lnk = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows",
                           "Start Menu", "Programs", "Startup", "大肥鱼桌宠.lnk")
        try:
            if on:
                ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{}');"
                      "$s.TargetPath='{}';$s.Arguments='\"{}\"';$s.WorkingDirectory='{}';$s.Save()"
                      .format(lnk, PYTHONW,
                              "" if getattr(sys, "frozen", False) else os.path.join(APP_DIR, "桌宠.py"),
                              APP_DIR))
                subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True)
                self.say("已开机自启，明天见～")
            else:
                if os.path.exists(lnk):
                    os.remove(lnk)
                self.say("已取消开机自启")
        except Exception as ex:
            QMessageBox.warning(self, "开机自启", f"设置失败：{ex}")

    def toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()

    def quit_app(self):
        self.cfg["x"], self.cfg["y"] = self.x(), self.y()
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f, ensure_ascii=False, indent=2)
        self.tray.hide()
        QApplication.quit()


def start_pet_http_server(pet):
    """HTTP 监听线程：插件通过 POST /say 让桌宠说话"""
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                path = self.path.split("?", 1)[0]
                if path.startswith("/action"):
                    result = {"ok": pet._exec_action(body)}
                else:
                    text = body.get("text", "")
                    if text:
                        pet._queue_say(text)  # 截断/断句由 say() 统一处理
                    result = {"ok": True}
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode("utf-8"))
            except Exception as e:
                print("HTTP 处理失败:", e)
                self.send_response(500)
                self.end_headers()
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", PET_LISTEN_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"桌宠 HTTP 监听已启动: 127.0.0.1:{PET_LISTEN_PORT}")


def start_pet_heartbeat(pet):
    """AstrBot/插件失联（连续 30 秒探测不到 18790）→ 桌宠自动退出"""
    fail = 0
    while True:
        time.sleep(10)
        try:
            with socket.create_connection(("127.0.0.1", 18790), timeout=2):
                fail = 0
        except OSError:
            fail += 1
            if fail >= 3:
                print("AstrBot 失联，桌宠自动退出")
                QTimer.singleShot(0, pet.quit_app)
                return


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    w = PetWindow()
    start_pet_http_server(w)
    threading.Thread(target=start_pet_heartbeat, args=(w,), daemon=True).start()
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        try:
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "大肥鱼桌宠出错", str(ex))
        except Exception:
            pass
        raise