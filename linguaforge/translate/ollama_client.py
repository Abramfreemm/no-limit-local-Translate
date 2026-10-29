"""Ollama HTTP 客户端（仅依赖 httpx，无 UI 依赖）。"""

from __future__ import annotations

from typing import Any

import httpx


class OllamaError(RuntimeError):
    """Ollama 调用失败。"""


class OllamaUnavailable(OllamaError):
    """服务不可达 / 未启动。"""


class OllamaClient:
    """极薄封装：只做 HTTP + 错误归一。"""

    def __init__(self, host: str = "http://127.0.0.1:11434", timeout: float = 300.0) -> None:
        self.host = host.rstrip("/")
        self.timeout = timeout
        # trust_env=False：忽略 HTTP(S)_PROXY 等环境变量。
        # Ollama 跑在本机回环地址，本就不该走代理；而用户在公司网络/科学上网
        # 环境下常设了全局代理，一旦生效，请求会被发往代理服务器 —— 既连不上
        # （表现为"Ollama 没启动"的假故障），又把本机请求特征暴露给代理方。
        # 见 17 号 §7 / 19 号 LF-E11。
        self._client = httpx.Client(timeout=timeout, trust_env=False)

    # ---------- 基础 ----------
    def version(self) -> str:
        try:
            r = self._client.get(f"{self.host}/api/version")
            r.raise_for_status()
            return str(r.json().get("version", ""))
        except Exception as e:  # noqa: BLE001
            raise OllamaUnavailable(f"无法连接 Ollama（{self.host}）：{e}") from e

    def list_models(self) -> list[str]:
        try:
            r = self._client.get(f"{self.host}/api/tags", timeout=15)
            r.raise_for_status()
            return [m.get("name", "") for m in r.json().get("models", []) if m.get("name")]
        except Exception as e:  # noqa: BLE001
            raise OllamaUnavailable(f"无法列出模型：{e}") from e

    def has_model(self, name: str) -> bool:
        try:
            return name in self.list_models()
        except Exception:  # noqa: BLE001
            return False

    def ensure_model(self, name: str) -> bool:
        """模型是否存在；不存在时返回 False（不自动 pull，避免静默下载 8GB）。"""
        return self.has_model(name)

    # ---------- 对话 ----------
    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        fmt: str | None = None,
        options: dict[str, Any] | None = None,
        keep_alive: str = "10m",
        timeout: float | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": keep_alive,
        }
        if fmt:
            body["format"] = fmt
        if options:
            body["options"] = options
        try:
            r = self._client.post(
                f"{self.host}/api/chat", json=body, timeout=timeout or self.timeout
            )
        except Exception as e:  # noqa: BLE001
            raise OllamaUnavailable(f"请求 Ollama 失败：{e}") from e
        if r.status_code >= 400:
            raise OllamaError(f"Ollama 返回 {r.status_code}: {r.text[:300]}")
        try:
            return r.json()
        except Exception as e:  # noqa: BLE001
            raise OllamaError(f"Ollama 返回非 JSON：{e}") from e

    def chat_text(self, *args, **kwargs) -> str:
        d = self.chat(*args, **kwargs)
        msg = d.get("message") or {}
        return str(msg.get("content", ""))

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> OllamaClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
