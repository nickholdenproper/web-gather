import os
import unittest
from unittest import mock

from web_gather.llm import LLMClient, LLMError, resolve_client


class _Resp:
    def __init__(self, status, json_obj=None, text=""):
        self.status_code = status
        self._json = json_obj or {}
        self.text = text
        self.ok = status < 400

    def json(self):
        return self._json


class LlmTest(unittest.TestCase):
    def test_is_cloud(self):
        self.assertFalse(LLMClient("http://localhost:11434", "m").is_cloud)
        self.assertTrue(LLMClient("https://ollama.com", "m", "k").is_cloud)

    def test_resolve_client_prefers_cloud_with_key(self):
        with mock.patch.dict(os.environ, {"OLLAMA_API_KEY": "k"}, clear=False):
            c = resolve_client()
            self.assertTrue(c.is_cloud)
            self.assertEqual(c.api_key, "k")
        with mock.patch.dict(os.environ, {}, clear=True):
            c = resolve_client()
            self.assertFalse(c.is_cloud)
            self.assertIsNone(c.api_key)

    def test_local_complete_extracts_message(self):
        client = LLMClient("http://localhost:11434", "llama3.2")
        with mock.patch("requests.post", return_value=_Resp(200, {"message": {"content": "hello world"}})) as post:
            self.assertEqual(client.complete([{"role": "user", "content": "hi"}]), "hello world")
            post.assert_called_once()
            args = post.call_args
            self.assertEqual(args.kwargs["json"]["model"], "llama3.2")

    def test_cloud_auth_error(self):
        client = LLMClient("https://ollama.com", "gpt-oss:20b-cloud", "bad")
        with mock.patch("requests.post", return_value=_Resp(401)):
            with self.assertRaises(LLMError):
                client.complete([{"role": "user", "content": "hi"}])

    def test_local_missing_model(self):
        client = LLMClient("http://localhost:11434", "nope")
        with mock.patch("requests.post", return_value=_Resp(404, {}, "no such model")):
            with self.assertRaises(LLMError):
                client.complete([{"role": "user", "content": "hi"}])


if __name__ == "__main__":
    unittest.main()