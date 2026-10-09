"""Task commands must not be stored as a customer's name."""
import ast
from pathlib import Path
import re
from types import SimpleNamespace
import unittest


class State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class CustomerAddressTests(unittest.TestCase):
    def capture(self, text):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8-sig"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "capture_customer_address")
        state = State(customer_name="", preferred_form_of_address="", awaiting_address_preference=True)
        namespace = {"st": SimpleNamespace(session_state=state), "re": re, "language": "English"}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "app.py", "exec"), namespace)
        namespace["capture_customer_address"](text)
        return state

    def test_task_commands_are_not_names(self):
        for text in ("Set a followup", "Show auctions", "Find a house", "Email me later", "Help me", "cancel"):
            with self.subTest(text=text):
                self.assertEqual(self.capture(text)["customer_name"], "")

    def test_voluntary_name_answers_still_work(self):
        for text in ("Alex", "My name is Alex", "Call me Alex"):
            with self.subTest(text=text):
                self.assertEqual(self.capture(text)["customer_name"], "Alex")
