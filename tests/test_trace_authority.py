"""Authority neutrality tests for the trace package."""
from __future__ import annotations

import ast
import pathlib



class TestTraceAuthority:
    def test_no_tool_imports(self):
        src = pathlib.Path(__file__).resolve().parent.parent / "src" / "aetheris" / "trace"
        forbidden = (
            "aetheris.safety.guard",
            "aetheris.controller.controller",
            "aetheris.controller.executive",
            "aetheris.tools.base",
            "aetheris.planner.planner",
            "aetheris.research.perimeter",
        )
        for py in src.rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            for mod in forbidden:
                assert f"from {mod}" not in text, f"forbidden import in {py}: {mod}"
                assert f"import {mod}" not in text, f"forbidden import in {py}: {mod}"

    def test_no_side_effect_calls(self):
        src = pathlib.Path(__file__).resolve().parent.parent / "src" / "aetheris" / "trace"
        side_effects = {
            "subprocess.run", "subprocess.Popen", "os.system", "os.popen",
            "socket.socket", "socket.create_connection",
            "urllib.request.urlopen", "http.client.HTTPConnection",
            "Path.write_text", "Path.write_bytes", "Path.touch", "Path.unlink",
            "Path.rename", "Path.replace", "Path.mkdir", "Path.rmdir",
            "os.remove", "os.unlink", "os.rename", "os.replace",
            "os.mkdir", "os.makedirs", "os.rmdir", "os.removedirs",
            "shutil.copy", "shutil.copy2", "shutil.copytree", "shutil.move", "shutil.rmtree",
        }
        for py in src.rglob("*.py"):
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    name = ""
                    if isinstance(func, ast.Attribute):
                        if isinstance(func.value, ast.Name):
                            name = f"{func.value.id}.{func.attr}"
                        elif isinstance(func.value, ast.Attribute):
                            chain = []
                            cur = func
                            while isinstance(cur, ast.Attribute):
                                chain.append(cur.attr)
                                cur = cur.value
                            if isinstance(cur, ast.Name):
                                chain.append(cur.id)
                            name = ".".join(reversed(chain))
                    elif isinstance(func, ast.Name):
                        name = func.id
                    assert name not in side_effects, f"side-effect call in {py}: {name}"

    def test_trace_core_has_no_network(self):
        from aetheris.trace import replay, view, canonical, model
        for mod in (replay, view, canonical, model):
            assert not hasattr(mod, "socket"), f"network reference in {mod.__name__}"
            assert not hasattr(mod, "requests"), f"network reference in {mod.__name__}"
            assert not hasattr(mod, "urllib"), f"network reference in {mod.__name__}"
