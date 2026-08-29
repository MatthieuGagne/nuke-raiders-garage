"""Coverage for tools/garage/core/editor.py — MatthieuGagne/nuke-raiders-garage#43.

No Qt import anywhere in this file, and no editor is ever started: both
sides of the launch go through the module's two named seams (R9), which
these tests replace.

`make test` discovers this file, and that target installs no PySide6.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.garage.core import editor  # noqa: E402


def tmp_root(tmp: str) -> Path:
    """A temporary directory, spelled the way Garage spells it -- see the
    same helper in tests/test_garage_core.py for why `resolve()` matters
    on Windows."""
    return Path(tmp).resolve()


class TestOpenDirectory(unittest.TestCase):
    """R3/AC1: the directory is handed to the `code` PATH resolves."""

    def test_it_spawns_the_resolved_editor_with_the_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = tmp_root(tmp) / "dialog"
            target.mkdir()
            with mock.patch.object(editor, "_find_editor",
                                   return_value="C:/vs/code.CMD"):
                with mock.patch.object(editor, "_spawn") as spawn:
                    editor.open_directory(target)
            spawn.assert_called_once_with(["C:/vs/code.CMD", str(target)])

    def test_the_editor_is_resolved_by_name_on_path(self):
        """R3, and the Notes: `code`, never an absolute path to Code.exe."""
        with mock.patch("shutil.which", return_value="C:/vs/code.CMD") as which:
            self.assertEqual(editor._find_editor(), "C:/vs/code.CMD")
        which.assert_called_once_with("code")

    def test_a_missing_directory_is_a_named_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = tmp_root(tmp) / "gone"
            with self.assertRaises(editor.EditorError) as caught:
                editor.open_directory(target)
            self.assertIn("gone", caught.exception.message)


class TestEditorNotFound(unittest.TestCase):
    """R4/AC2: no `code` on PATH is a message naming VS Code and PATH."""

    def test_nothing_is_spawned(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = tmp_root(tmp)
            with mock.patch.object(editor, "_find_editor", return_value=None):
                with mock.patch.object(editor, "_spawn") as spawn:
                    with self.assertRaises(editor.EditorError):
                        editor.open_directory(target)
            spawn.assert_not_called()

    def test_the_message_names_vs_code_and_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = tmp_root(tmp)
            with mock.patch.object(editor, "_find_editor", return_value=None):
                with self.assertRaises(editor.EditorError) as caught:
                    editor.open_directory(target)
            message = caught.exception.message
            self.assertIn("VS Code", message)
            self.assertIn("PATH", message)

    def test_a_spawn_failure_is_a_named_failure_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = tmp_root(tmp)
            with mock.patch.object(editor, "_find_editor",
                                   return_value="C:/vs/code.CMD"):
                with mock.patch.object(editor, "_spawn",
                                       side_effect=OSError("denied")):
                    with self.assertRaises(editor.EditorError) as caught:
                        editor.open_directory(target)
            self.assertIn("denied", caught.exception.message)


class TestFireAndForget(unittest.TestCase):
    """R5: Garage starts the editor and never waits on it."""

    def test_the_seam_uses_popen_and_does_not_wait(self):
        with mock.patch.object(subprocess, "Popen") as popen:
            editor._spawn(["C:/vs/code.CMD", "C:/repo/assets/dialog"])
        popen.assert_called_once()
        self.assertEqual(
            popen.call_args.args[0],
            ["C:/vs/code.CMD", "C:/repo/assets/dialog"],
        )
        started = popen.return_value
        started.wait.assert_not_called()
        started.communicate.assert_not_called()

    def test_open_directory_never_calls_run(self):
        """`subprocess.run` blocks until the editor is closed, which is
        the whole failure R5 forbids. Asserted rather than reasoned
        about."""
        with tempfile.TemporaryDirectory() as tmp:
            target = tmp_root(tmp)
            with mock.patch.object(editor, "_find_editor",
                                   return_value="C:/vs/code.CMD"):
                with mock.patch.object(subprocess, "Popen"):
                    with mock.patch.object(subprocess, "run") as run:
                        editor.open_directory(target)
        run.assert_not_called()


class TestTheExceptionIsScoped(unittest.TestCase):
    """R3: `core/editor.py` is the only module allowed to name an editor.

    The sibling tripwire in tests/test_garage_assets.py guards
    assets/pipeline/preview against three other editors' names; this one
    guards every core module against VS Code's, exempting the one module
    the spec makes an exception for. Same shape and same limits: it walks
    the AST for literal string constants outside docstrings, so a name
    assembled at runtime would slip past it.
    """

    def test_no_other_core_module_names_vs_code(self):
        import ast

        core_dir = REPO_ROOT / "tools" / "garage" / "core"
        editor_path = core_dir / "editor.py"
        for path in sorted(core_dir.rglob("*.py")):
            if path == editor_path:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docstrings = set()
            for node in ast.walk(tree):
                body = getattr(node, "body", None)
                if not isinstance(body, list) or not body:
                    continue
                first = body[0]
                if (
                    isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                      ast.AsyncFunctionDef))
                    and isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    docstrings.add(id(first.value))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in docstrings
                ):
                    lowered = node.value.lower()
                    for name in ("vs code", "vscode", "visual studio code",
                                 "code.exe"):
                        self.assertNotIn(
                            name, lowered,
                            f"{path.name} names {name} in code; only "
                            f"core/editor.py may (#43 R3)",
                        )


if __name__ == "__main__":
    unittest.main()
