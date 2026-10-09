import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock
import pandas as pd
from property_search import load_properties
from ai_config import select_ai_config
from agent_runtime import run_openai_agent, ToolResult


class GroqTests(unittest.TestCase):
    def test_explicit_leasehold_listing_request_can_search(self):
        call = SimpleNamespace(id="call-1", function=SimpleNamespace(name="search_saved_properties", arguments='{}'))
        responses = Mock()
        responses.create.side_effect = [
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call], content=None))]),
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[], content="Here are the saved matches."))]),
        ]
        factory = Mock(return_value=SimpleNamespace(chat=SimpleNamespace(completions=responses)))
        result = SimpleNamespace(display_kind="properties", data={"count": 1})
        with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=factory)}), patch("agent_runtime.dispatch_tool", return_value=result) as dispatch:
            turn = run_openai_agent(text="Show me a leasehold plot", history=[], properties=load_properties().iloc[:0], sources=pd.DataFrame(), api_key="test-key", provider="groq")
        self.assertEqual(dispatch.call_count, 1, str(responses.create.call_args.kwargs["messages"][-1]))
        self.assertEqual(len(turn.tool_results), 1)

    def test_ownership_question_cannot_trigger_unsolicited_search(self):
        call = SimpleNamespace(id="call-1", function=SimpleNamespace(name="search_saved_properties", arguments='{}'))
        responses = Mock()
        responses.create.side_effect = [
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call], content=None))]),
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[], content="Renewal depends on the lease terms."))]),
        ]
        factory = Mock(return_value=SimpleNamespace(chat=SimpleNamespace(completions=responses)))
        with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=factory)}), patch("agent_runtime.dispatch_tool") as dispatch:
            turn = run_openai_agent(text="How does leasehold renewal work?", history=[], properties=load_properties().iloc[:0], sources=pd.DataFrame(), api_key="test-key", provider="groq")
        dispatch.assert_not_called()
        self.assertEqual(turn.tool_results, [])
        self.assertIn("lease terms", turn.text)

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
            turn = run_openai_agent(text="Find homes", history=[], properties=load_properties().iloc[:0], sources=pd.DataFrame(), api_key="test-key", provider="groq", model="openai/gpt-oss-20b")
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
            turn = run_openai_agent(text="Hello", history=[], properties=load_properties().iloc[:0], sources=pd.DataFrame(), api_key="test-key", provider="groq")
        self.assertEqual(turn.error, "openai_rate_limit")
        self.assertEqual(turn.text, "")
