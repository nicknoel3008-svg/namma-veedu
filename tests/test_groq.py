import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock
import pandas as pd
from ai_config import select_ai_config
from agent_runtime import run_openai_agent, ToolResult


class GroqTests(unittest.TestCase):
    def test_default_does_not_use_old_openai_key(self):
        values = {"OPENAI_API_KEY": "old-key"}
        self.assertEqual(select_ai_config(lambda key, default="": values.get(key, default)),
                         ("groq", "", "openai/gpt-oss-20b"))

    def test_groq_tool_round_trip(self):
        call = SimpleNamespace(id="call-1", function=SimpleNamespace(name="search_saved_properties", arguments='{}'))
        responses = Mock()
        responses.create.side_effect = [
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call], content=None))]),
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[], content="Here are the saved matches."))]),
        ]
        factory = Mock(return_value=SimpleNamespace(chat=SimpleNamespace(completions=responses)))
        result = SimpleNamespace(display_kind="properties", data={"count": 1})
        with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=factory)}), patch("agent_runtime.dispatch_tool", return_value=result):
            turn = run_openai_agent(text="Find homes", history=[], properties=pd.DataFrame(), sources=pd.DataFrame(), api_key="test-key", provider="groq", model="openai/gpt-oss-20b")
        self.assertEqual(turn.text, "Here are the saved matches.")
        self.assertEqual(factory.call_args.kwargs["base_url"], "https://api.groq.com/openai/v1")
        for request in responses.create.call_args_list:
            self.assertNotIn("store", request.kwargs)
        self.assertEqual(responses.create.call_args.kwargs["messages"][-1]["role"], "tool")

    def test_limit_returns_error_for_local_fallback(self):
        error = type("RateLimitError", (Exception,), {"status_code": 429})()
        responses = Mock()
        responses.create.side_effect = error
        with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=Mock(return_value=SimpleNamespace(chat=SimpleNamespace(completions=responses))))}):
            turn = run_openai_agent(text="Hello", history=[], properties=pd.DataFrame(), sources=pd.DataFrame(), api_key="test-key", provider="groq")
        self.assertEqual(turn.error, "openai_rate_limit")
        self.assertEqual(turn.text, "")
