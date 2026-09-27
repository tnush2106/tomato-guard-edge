import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class Message:
    def __init__(self, content):
        self.content = content


class SystemMessage(Message):
    pass


class HumanMessage(Message):
    pass


class AIMessage(Message):
    pass


class StationContextTests(unittest.TestCase):
    def test_latest_sensor_snapshot_replaces_previous_context_without_mutating_caller(self):
        calls = []
        graph = types.SimpleNamespace(invoke=lambda state: calls.append(state) or {"final_answer": "ok"})
        builder = types.ModuleType("core.build_graph")
        builder.build_graph = lambda: graph
        messages_module = types.ModuleType("langchain_core.messages")
        messages_module.HumanMessage = HumanMessage
        messages_module.AIMessage = AIMessage
        messages_module.SystemMessage = SystemMessage
        source = Path(__file__).resolve().parents[1] / "core" / "run_graph.py"
        spec = importlib.util.spec_from_file_location("run_graph_under_test", source)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"core.build_graph": builder, "langchain_core.messages": messages_module}):
            spec.loader.exec_module(module)
        previous = [SystemMessage("humidity=20"), HumanMessage("previous question"), AIMessage("previous answer")]
        answer, updated = module.run_graph("now?", previous, "humidity=70")
        self.assertEqual(answer, "ok")
        self.assertEqual(previous[0].content, "humidity=20")
        self.assertEqual(len(previous), 3)
        self.assertEqual([m.content for m in calls[0]["messages"] if isinstance(m, SystemMessage)], ["humidity=70"])
        self.assertEqual(updated[-1].content, "ok")


if __name__ == "__main__":
    unittest.main()
