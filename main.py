# -*- coding: utf-8 -*-
"""
大肥鱼桌宠插件 —— 桌宠是 QQ 智能体的身体

链路:
    桌宠输入框 → POST 插件本地端口 /pet/input → handle_msg 注入主人 QQ 会话
        → AstrBot 完整管线（人格/记忆/历史）→ 回复 → QQ + 桌宠气泡同步
    桌宠互动（点击/喂食/拖拽/动作）→ POST /pet/event → 存内存
        → on_llm_request 作为身体状态注入每次对话
    模型回复带【动作：X】→ on_decorating_result 解析 → POST 桌宠 /action 执行

    插件自己监听 127.0.0.1:18790（loopback，无鉴权），桌宠不再需要 API Key。
"""
import asyncio
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star, register
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
from astrbot.core.platform.message_type import MessageType
from astrbot.core.star.filter.platform_adapter_type import PlatformAdapterType

PET_HOST = "127.0.0.1"
PET_PORT = 18789          # 桌宠的 HTTP 监听（插件 → 桌宠）
PET_URL = f"http://{PET_HOST}:{PET_PORT}"
LISTEN_PORT = 18790       # 插件的 HTTP 监听（桌宠 → 插件）
PET_PY = "桌宠.py"
PET_DIR = os.path.dirname(os.path.abspath(__file__))
PET_SCRIPT = os.path.join(PET_DIR, PET_PY)

ACTION_MAP = {
    "跳跃": "jump", "跳": "jump",
    "摇晃": "sway", "摇摆": "sway",
    "伸懒腰": "stretch", "伸腰": "stretch",
    "散步": "mode", "自由活动": "mode", "走走": "mode",
    "跟随": "mode", "跟着我": "mode",
    "待着": "mode", "不动": "mode", "原地": "mode",
}
ACTION_MODE_VALUE = {"散步": "wander", "自由活动": "wander", "走走": "wander",
                     "跟随": "follow", "跟着我": "follow",
                     "待着": "still", "不动": "still", "原地": "still"}
# 模型回复里的动作标签：【动作：跳跃】/【动作：散步】
ACTION_TAG_RE = re.compile(r"【动作[:：]([^】]+)】")

# 身体状态注入的提示词（注入到每次对话的 system_prompt）
BODY_STATE_PREFIX = "\n\n【身体状态】你是桌面上的一只大肥鱼桌宠："


def pet_alive() -> bool:
    try:
        with socket.create_connection((PET_HOST, PET_PORT), timeout=1):
            return True
    except OSError:
        return False


@register("dafeiyu_pet", "Moebius", "大肥鱼桌宠：桌宠是 QQ 智能体的身体", "0.4.0")
class DafeiyuPetPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context, config)
        self.config = config or {}
        self._http = None
        self._pet_proc: subprocess.Popen | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: ThreadingHTTPServer | None = None
        self._pet_events: list[dict] = []   # 最近互动事件（身体状态注入用）
        self._event_ts: dict[str, float] = {}  # 同类事件去重
        self._last_mode = "wander"

    async def initialize(self):
        self._http = httpx.AsyncClient(timeout=10)
        self._loop = asyncio.get_running_loop()
        self._start_listener()
        logger.info("大肥鱼插件已激活，监听 127.0.0.1:%d", LISTEN_PORT)

    # ---------- 本地 HTTP 监听（桌宠 → 插件） ----------

    def _start_listener(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length) or b"{}")
                    coro = self.server._plugin._handle_request(self.path, body)
                    fut = asyncio.run_coroutine_threadsafe(coro, self.server._loop)
                    result = fut.result(timeout=30)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(result).encode("utf-8"))
                except Exception as e:
                    logger.error(f"插件 HTTP 处理失败: {e}")
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b'{"ok": false}')
            def log_message(self, *args):
                pass
        self._server = ThreadingHTTPServer((PET_HOST, LISTEN_PORT), Handler)
        self._server._plugin = self
        self._server._loop = self._loop
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    async def _handle_request(self, path: str, body: dict) -> dict:
        if path.startswith("/pet/input"):
            return await self._inject_input(body)
        if path.startswith("/pet/event"):
            return self._collect_event(body)
        return {"ok": False, "error": "unknown path"}

    async def _inject_input(self, body: dict) -> dict:
        """桌宠输入 → 注入主人 QQ 会话 → AstrBot 管线正常处理"""
        text = str(body.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "empty text"}
        qq = str(self.config.get("master_qq") or "").strip()
        if not qq:
            return {"ok": False, "error": "master_qq 未配置（插件配置里填主人 QQ 号）"}
        platform = self.context.get_platform(PlatformAdapterType.AIOCQHTTP)
        if platform is None:
            return {"ok": False, "error": "aiocqhttp 平台未启用"}
        msg = AstrBotMessage()
        msg.type = MessageType.FRIEND_MESSAGE
        msg.self_id = qq
        msg.session_id = qq
        msg.message_id = f"pet_{int(time.time() * 1000)}"
        msg.sender = MessageMember(qq, "主人")
        msg.message = [Plain(text)]
        msg.message_str = text
        msg.raw_message = None
        await platform.handle_msg(msg)
        logger.info(f"桌宠输入已注入 QQ 会话: {text[:30]}")
        return {"ok": True}

    def _collect_event(self, body: dict) -> dict:
        """互动事件入内存（身体状态注入用），同类 30 秒去重"""
        etype = str(body.get("type") or "").strip()
        detail = str(body.get("detail") or "").strip()
        if not etype:
            return {"ok": False, "error": "empty type"}
        now = time.time()
        if etype in ("sway", "jump", "stretch"):
            if now - self._event_ts.get(etype, 0) < 30:
                return {"ok": True, "deduped": True}
            self._event_ts[etype] = now
        if etype == "mode" and detail:
            self._last_mode = detail
        self._pet_events.append({"type": etype, "detail": detail, "at": now})
        self._pet_events = self._pet_events[-5:]
        return {"ok": True}

    # ---------- 身体状态注入 ----------

    def _body_state_text(self) -> str:
        """最近互动事件 → 一句身体状态描述"""
        parts = [f"你正在{self._last_mode}"]
        for ev in self._pet_events:
            if time.time() - ev["at"] > 300:
                continue
            t = ev["type"]
            d = ev.get("detail") or ""
            if t == "click":
                parts.append("主人刚才戳了你一下")
            elif t == "feed":
                parts.append(f"主人刚才喂了你{d}")
            elif t == "drag":
                parts.append("主人刚才拖着你玩")
            elif t == "sway":
                parts.append("你刚才摇晃了一下")
            elif t == "jump":
                parts.append("你刚才跳了一下")
            elif t == "stretch":
                parts.append("你刚才伸了个懒腰")
        return "，".join(parts)

    @filter.on_llm_request(priority=5)
    async def inject_body_state(self, event: AstrMessageEvent, req):
        """每次对话前把桌宠身体状态注入提示词"""
        state = self._body_state_text()
        if state:
            req.system_prompt = (req.system_prompt or "") + BODY_STATE_PREFIX + state
        # 提示模型可以输出动作标签
        req.prompt = (req.prompt or "") + (
            "\n（如需让桌宠做动作，在回复末尾加【动作：跳跃/摇晃/伸懒腰/散步/跟随/待着】）"
        )

    # ---------- 回复处理：同步桌宠 + 动作执行 ----------

    @filter.on_decorating_result()
    async def sync_to_pet(self, event: AstrMessageEvent):
        """智能体回复 → 同步桌宠气泡 + 解析动作标签执行"""
        result = event.get_result()
        if result is None or not result.is_llm_result():
            return
        texts = [comp.text for comp in result.chain if isinstance(comp, Plain) and comp.text]
        full = " ".join(texts)
        # 动作标签：先执行，再从显示文本里去掉
        action = None
        m = ACTION_TAG_RE.search(full)
        if m:
            action = m.group(1).strip()
            full = ACTION_TAG_RE.sub("", full).strip()
        if action and pet_alive():
            await self._execute_action(action)
        if full and pet_alive():
            try:
                await self._http.post(f"{PET_URL}/say", json={"text": full})
            except Exception as e:
                logger.error(f"同步桌宠失败: {e}")

    async def _execute_action(self, action_text: str):
        action = ACTION_MAP.get(action_text)
        if not action:
            return
        if action == "mode":
            value = ACTION_MODE_VALUE.get(action_text, "wander")
            await self._send_pet_action({"action": "mode", "value": value})
        else:
            await self._send_pet_action({"action": action})

    async def _send_pet_action(self, payload: dict):
        try:
            await self._http.post(f"{PET_URL}/action", json=payload)
        except Exception as e:
            logger.error(f"桌宠动作执行失败: {e}")

    # ---------- 桌宠进程管理 ----------

    def _start_pet(self) -> bool:
        if pet_alive():
            return True
        if not os.path.exists(PET_SCRIPT):
            logger.error(f"桌宠脚本不存在: {PET_SCRIPT}")
            return False
        exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(exe):
            exe = sys.executable
        try:
            self._pet_proc = subprocess.Popen(
                [exe, PET_PY],
                cwd=PET_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info(f"桌宠进程已启动 (pid={self._pet_proc.pid})")
            return True
        except Exception as e:
            logger.error(f"启动桌宠失败: {e}")
            return False

    def _stop_pet(self) -> None:
        if self._pet_proc and self._pet_proc.poll() is None:
            self._pet_proc.terminate()
            self._pet_proc = None
            logger.info("桌宠进程已停止")

    @filter.command("pet")
    async def pet_control(self, event: AstrMessageEvent, action: str = "status"):
        """桌宠控制：/pet start 启动 | /pet stop 停止 | /pet status 状态"""
        action = action.strip().lower()
        if action == "start":
            ok = self._start_pet()
            yield event.plain_result(
                "桌宠已在运行" if ok and pet_alive() else
                "桌宠启动失败，查看 AstrBot 日志" if not ok else
                "桌宠启动中，稍后它会自己出现"
            )
        elif action == "stop":
            self._stop_pet()
            yield event.plain_result("已停止桌宠")
        else:
            alive = pet_alive()
            yield event.plain_result(f"桌宠状态：{'运行中' if alive else '未运行'}")

    @filter.command("say")
    async def say_to_pet(self, event: AstrMessageEvent, text: str):
        """让桌宠说一句话：/say 你好 → 桌宠气泡显示"""
        if not pet_alive() and not self._start_pet():
            yield event.plain_result("桌宠未在运行且启动失败，检查日志")
            return
        try:
            await self._http.post(f"{PET_URL}/say", json={"text": text})
            yield event.plain_result(f"已让大肥鱼说：{text}")
        except Exception as e:
            logger.error(f"桌宠通信失败: {e}")
            yield event.plain_result(f"桌宠通信失败：{e}")

    async def terminate(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._http:
            await self._http.aclose()
        self._stop_pet()
