# -*- coding: utf-8 -*-
"""
大肥鱼桌宠插件 —— AstrBot 大脑 + 桌宠前端一体

架构:
    QQ 对话 → AstrBot 智能体 → 本插件 on_decorating_result 钩子
         → POST 桌宠 /say → 桌宠气泡（QQ 回复同步到桌宠）
    桌宠输入框 → 直接 POST AstrBot open API /api/v1/chat（webchat 会话）
         → SSE 回复 → 桌宠气泡（不经插件）
    插件负责: 桌宠进程管理 + QQ 回复同步 + 手动让桌宠说话
"""
import os
import socket
import subprocess
import sys

import httpx
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star, register

PET_HOST = "127.0.0.1"
PET_PORT = 18789
PET_URL = f"http://{PET_HOST}:{PET_PORT}"
PET_PY = "桌宠.py"
PET_DIR = os.path.dirname(os.path.abspath(__file__))
PET_SCRIPT = os.path.join(PET_DIR, PET_PY)
# 桌宠会话标识：桌宠调 open API 时用的 session_id/username
PET_SESSION_ID = "dafeiyu_pet"


def pet_alive() -> bool:
    """探测桌宠的 HTTP 监听是否活着。"""
    try:
        with socket.create_connection((PET_HOST, PET_PORT), timeout=1):
            return True
    except OSError:
        return False


@register("dafeiyu_pet", "Moebius", "大肥鱼桌宠：AstrBot 大脑 + 桌宠前端一体插件", "0.3.0")
class DafeiyuPetPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self._http = None
        self._pet_proc: subprocess.Popen | None = None

    async def initialize(self):
        self._http = httpx.AsyncClient(timeout=10)
        logger.info("大肥鱼插件已激活，桌宠目录: %s", PET_DIR)

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

    # ---------- QQ 回复同步到桌宠 ----------

    @filter.on_decorating_result()
    async def sync_to_pet(self, event: AstrMessageEvent):
        """智能体回复 → 同步到桌宠气泡（桌宠会话自身的回复跳过，避免重复）"""
        if not pet_alive():
            return
        umo = event.unified_msg_origin or ""
        if umo.startswith("webchat:") and umo.endswith(f"!{PET_SESSION_ID}"):
            return
        result = event.get_result()
        if result is None or not result.is_llm_result():
            return
        texts = [
            comp.text for comp in result.chain
            if isinstance(comp, Plain) and comp.text
        ]
        if not texts:
            return
        text = " ".join(texts)
        try:
            await self._http.post(f"{PET_URL}/say", json={"text": text})
        except Exception as e:
            logger.error(f"同步桌宠失败: {e}")

    async def terminate(self):
        if self._http:
            await self._http.aclose()
        self._stop_pet()
