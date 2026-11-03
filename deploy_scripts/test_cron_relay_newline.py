# -*- coding: utf-8 -*-
"""TDD：cron wrapper 中转输出换行倍增修复（2026-11-03 用户反馈"这都不是表格"）。

事故链（字节级证据，cron/output/0740a34e4711 2026-11-03_15-51）：
  子进程 stdout 文本模式输出 "\r\n"
  → wrapper print(out) 在 Windows 文本模式 stdout 上再次翻译 → "\r\r\n"
  → Hermes 按通用换行读取 → 每行之间多一个空行
  → 飞书 markdown 表格的表头与 |---| 分隔行被空行隔开 → 表格不渲染。

要求：中转输出必须字节级保真（LF 规范化），表格任意相邻两行不得被空行隔开。
"""
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rate_ignition_monitor_wrapper as ri
import watchtower_wrapper as wt


SAMPLE_MARKDOWN = "\r\n".join([
    "### 🗼 观察哨（历史类比四哨）",
    "",
    "| 哨 | 状态 | 读数 |",
    "| --- | --- | --- |",
    "| 哨①量能地量 | 未到 | 量能比0.456 |",
    "",
    "读法：哨①+哨②同时达成=出清末段。",
])


def _relay_bytes(wrapper, raw: bytes) -> bytes:
    """把 wrapper 的中转函数当纯函数用：喂子进程原始 stdout 字节，收管道字节。"""
    import io
    old = sys.stdout
    sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="")
    try:
        wrapper.relay(raw)
        sys.stdout.flush()
        return sys.stdout.buffer.getvalue()
    finally:
        sys.stdout = old


class RelayNewlineTests(unittest.TestCase):
    def test_relay_normalizes_crlf_to_single_lf(self):
        """中转后不得出现 \\r\\r\\n（换行倍增的直接字节证据）。"""
        for wrapper in (wt, ri):
            out = _relay_bytes(wrapper, SAMPLE_MARKDOWN.encode("utf-8"))
            self.assertNotIn(b"\r\r\n", out, f"{wrapper.__name__} 中转倍增了换行")

    def test_relay_keeps_table_rows_adjacent(self):
        """表头与 |---| 分隔行必须相邻——飞书表格渲染的硬要求。"""
        for wrapper in (wt, ri):
            out = _relay_bytes(wrapper, SAMPLE_MARKDOWN.encode("utf-8")).decode("utf-8")
            lines = out.splitlines()
            idx = [i for i, l in enumerate(lines) if l.strip().startswith("|")]
            gaps = [b - a for a, b in zip(idx, idx[1:])]
            self.assertTrue(all(g == 1 for g in gaps),
                            f"{wrapper.__name__} 表格行间出现空行: {gaps}")

    def test_relay_empty_in_empty_out(self):
        """空输入静默（watchdog 语义不变）。"""
        for wrapper in (wt, ri):
            out = _relay_bytes(wrapper, b"")
            self.assertEqual(out, b"")


if __name__ == "__main__":
    unittest.main()
