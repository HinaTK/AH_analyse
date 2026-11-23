"""DSH scheduled push can send a Feishu rich-text post with md nodes (Hermes path)."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

MODULE = Path(__file__).resolve().parent.parent / 'deploy_scripts' / 'feishu_post.py'


def _load():
    spec = importlib.util.spec_from_file_location('feishu_post_under_test', MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FeishuPostTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.is_file(), 'feishu_post.py is missing')
        self.mod = _load()

    def test_build_post_content_uses_md_node(self):
        body = '| 哨 | 状态 |\n| --- | --- |\n| 哨① | 未到 |'
        payload = self.mod.build_post_content(body)
        self.assertEqual(payload, {'zh_cn': {'content': [[{'tag': 'md', 'text': body}]]}})

    def test_build_post_content_isolates_fenced_code_blocks(self):
        body = '前文\n```text\n代码块\n```\n后文'
        rows = self.mod.build_post_content(body)['zh_cn']['content']
        self.assertEqual([row[0]['tag'] for row in rows], ['md', 'md', 'md'])
        self.assertEqual(rows[1][0]['text'], '```text\n代码块\n```')

    def test_send_post_uses_interactive_card_and_markdown(self):
        """2026-11-23 Master 再次收到灰底 post：IM 卡片超时后回退到 post 通道。

        回退通道也必须发白底卡片（schema 2.0 + markdown），否则样式会打回原形。
        """
        calls = []

        def opener(request, timeout=0):
            calls.append(request)
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            if 'tenant_access_token' in request.full_url:
                response.read.return_value = json.dumps({'code': 0, 'tenant_access_token': 't-fake'}).encode()
            else:
                response.read.return_value = json.dumps({'code': 0, 'data': {'message_id': 'om-fake'}}).encode()
            return response

        ok = self.mod.send_post(
            '| A | B |\n| - | - |',
            bot_id='bot_fake', target_id='tgt_fake', opener=opener,
            config_path=self._write('cfg.json', {'bots': [{'id': 'bot_fake', 'appId': 'cli_fake', 'secretRef': 'REF_FAKE'}]}),
            credentials_path=self._write('credentials.yaml', 'refs:\n  REF_FAKE: s3cr3t-value\n'),
            workspaces_path=self._write('workspaces.json', {'deliveryTargets': {'bot_fake': {'tgt_fake': {'route': {'openId': 'ou_fake'}}}}}),
        )
        self.assertTrue(ok)
        self.assertEqual(len(calls), 2)
        sent = json.loads(calls[1].data)
        self.assertEqual(sent['msg_type'], 'interactive')
        self.assertEqual(sent['receive_id'], 'ou_fake')
        self.assertIn('open_id', calls[1].full_url)
        card = json.loads(sent['content'])
        self.assertEqual(card['schema'], '2.0')
        self.assertEqual(card['body']['elements'][0]['tag'], 'markdown')
        self.assertIn('| A | B |', card['body']['elements'][0]['content'])
        self.assertNotIn('s3cr3t-value', json.dumps(sent))

    def test_run_and_push_prefers_im_card_and_falls_back_safely(self):
        """2026-11-20 Master 拍板：定时推送统一用 DSH-IM 卡片（白底样式）。

        顺序改为 im → post（灰底富文本，降级通道）→ webhook。
        """
        wrapper = Path(__file__).resolve().parent.parent / 'deploy_scripts' / 'run_and_push.py'
        spec = importlib.util.spec_from_file_location('run_and_push_under_test', wrapper)
        push = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(push)
        seen = []
        push._push_feishu_post = lambda text: seen.append('post') or True
        push._push_im = lambda text: seen.append('im') or True
        push._push_webhook = lambda text: seen.append('webhook') or True
        self.assertTrue(push._push('正文'))
        self.assertEqual(seen, ['im'])
        seen.clear()
        push._push_im = lambda text: seen.append('im') or False
        self.assertTrue(push._push('正文'))
        self.assertEqual(seen, ['im', 'post'])
        seen.clear()
        push._push_feishu_post = lambda text: seen.append('post') or False
        self.assertTrue(push._push('正文'))
        self.assertEqual(seen, ['im', 'post', 'webhook'])

    def test_im_request_timeout_exceeds_plugin_feishu_wait(self):
        """客户端等待须长于插件转发飞书的 15 秒，否则超时误判后会换通道重发造成两条。"""
        wrapper = Path(__file__).resolve().parent.parent / 'deploy_scripts' / 'run_and_push.py'
        spec = importlib.util.spec_from_file_location('run_and_push_under_test', wrapper)
        push = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(push)
        self.assertIsInstance(push.IM_REQUEST_TIMEOUT, int)
        self.assertGreater(push.IM_REQUEST_TIMEOUT, 15)


    def _write(self, name, value):
        import tempfile
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(folder, ignore_errors=True))
        path = folder / name
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding='utf-8')
        return path


if __name__ == '__main__':
    unittest.main()
