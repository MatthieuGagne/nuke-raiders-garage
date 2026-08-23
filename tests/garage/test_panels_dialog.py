"""Panel coverage for the dialog panel (spec P3, issue #4).

Imports PySide6, so this file must never be reachable by
`python -m unittest discover -s tests` -- tests/garage/ has no
__init__.py, so default discovery never descends into it (AC13). Run via
`make test-garage` (AC14).
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtWidgets import QApplication

from tools.garage import theme
from tools.garage.core import dialog_model, project
from tools.garage.panels.dialog import DialogPanel

GAME_REPO_REMOTE_URL = "https://github.com/MatthieuGagne/gmb-nuke-raider.git"

_app = QApplication.instance() or QApplication([])

CONFIG_H = """\
#define MAX_NPCS     2
#define MAX_HUB_NPCS           3u
"""

NPCS = {
    "npcs": [
        {
            "id": 0,
            "name": "STEEVE",
            "vendor_field": "ARMOR",
            "nodes": [
                {"idx": 0, "text": "Roads. Parts. Sharp. Racer.",
                 "choices": [], "next": [1]},
                {"idx": 1, "text": "Da FUQ ?", "choices": ["Races", "Shop"],
                 "next": [2, "SHOP"]},
                {"idx": 2, "text": "Stay sharp.", "choices": [],
                 "next": ["END"]},
            ],
        },
        {
            "id": 1,
            "name": "TRADER",
            "vendor_field": "WEAPON1",
            "nodes": [
                {"idx": 0, "text": "Got caps?", "choices": [], "next": ["END"]},
            ],
        },
    ]
}

HUBS = {"hubs": [{"id": 0, "name": "RUST TOWN", "npc_ids": [0, 1]}]}


def _run_git(args, cwd):
    return subprocess.run(
        ["git"] + args, cwd=str(cwd), check=True, capture_output=True, text=True
    )


def _real_generator():
    """The game repository's own dialog_to_c.py, when one is bound. The
    fixture copies it in so AC11 is checked against the real generator
    rather than a stub; every test that needs it skips when no game
    repository is bound, which is the CI case."""
    try:
        path = project.bind().resolve("tools", "dialog_to_c.py")
    except project.BindingError:
        return None
    return path if path.is_file() else None


REAL_GENERATOR = _real_generator()
NO_GAME_REPO = REAL_GENERATOR is None
NO_GAME_REPO_REASON = "no game repository is bound beside this checkout"


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def make_fixture_worktree(root: Path, npcs=None, config_h=CONFIG_H) -> Path:
    repo = root / "nuke-raider"
    (repo / "src").mkdir(parents=True, exist_ok=True)
    (repo / "tools").mkdir(parents=True, exist_ok=True)
    write_json(repo / "assets" / "dialog" / "npcs.json",
               NPCS if npcs is None else npcs)
    write_json(repo / "assets" / "dialog" / "hubs.json", HUBS)
    (repo / "src" / "config.h").write_text(config_h, encoding="utf-8")
    if REAL_GENERATOR is not None:
        (repo / "tools" / "dialog_to_c.py").write_bytes(
            REAL_GENERATOR.read_bytes())
    _run_git(["init", "-b", "master"], repo)
    _run_git(["config", "user.email", "test@example.com"], repo)
    _run_git(["config", "user.name", "Test"], repo)
    _run_git(["add", "."], repo)
    _run_git(["commit", "-m", "init"], repo)
    _run_git(["remote", "add", "origin", GAME_REPO_REMOTE_URL], repo)
    return repo


def bind_over(root: Path, repo: Path) -> project.Binding:
    garage_root = root / "nuke-raider-garage"
    garage_root.mkdir(exist_ok=True)
    project.save_settings(
        garage_root,
        {
            "game_repo": repo.as_posix(),
            "worktree_root": (root / "worktrees").as_posix(),
            "active": None,
        },
    )
    return project.bind(garage_root)


@unittest.skipIf(NO_GAME_REPO, NO_GAME_REPO_REASON)
class DialogPanelTestCase(unittest.TestCase):
    npcs = None
    config_h = CONFIG_H

    def setUp(self):
        theme.apply(_app)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.repo = make_fixture_worktree(
            self.root, npcs=self.npcs, config_h=self.config_h)
        self.binding = bind_over(self.root, self.repo)
        self.panel = DialogPanel(self.binding, None)

    def tearDown(self):
        self.panel.stop_and_wait()
        self.panel.deleteLater()
        self._tmp.cleanup()

    def saved_npcs(self):
        return json.loads(
            (self.repo / "assets" / "dialog" / "npcs.json").read_text(
                encoding="utf-8"))


class TestNpcList(DialogPanelTestCase):
    """AC1: the panel lists the NPCs in npcs.json."""

    def test_every_npc_is_listed(self):
        self.assertEqual(self.panel.npc_names(), ["STEEVE", "TRADER"])

    def test_the_first_npc_is_selected_on_open(self):
        self.assertEqual(self.panel.selected_npc_index(), 0)


class TestNodeCards(DialogPanelTestCase):
    """AC1: the nodes of the selected NPC."""

    def test_a_card_per_node_of_the_selected_npc(self):
        self.assertEqual(len(self.panel.node_cards()), 3)

    def test_selecting_another_npc_shows_its_nodes(self):
        self.panel.select_npc(1)
        cards = self.panel.node_cards()
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].text_field.text(), "Got caps?")

    def test_a_card_shows_the_node_index(self):
        self.assertEqual(
            [c.id_label.text() for c in self.panel.node_cards()],
            ["[0]", "[1]", "[2]"],
        )

    def test_a_card_shows_the_node_text(self):
        self.assertEqual(
            self.panel.node_cards()[2].text_field.text(), "Stay sharp.")


class TestCharacterCount(DialogPanelTestCase):
    """AC6/R7: the count is shown against 63 and moves as the user
    types."""

    def test_the_count_is_shown_against_the_limit(self):
        card = self.panel.node_cards()[1]
        self.assertEqual(card.count_label.text(), "8/63")

    def test_typing_updates_the_count_without_a_save(self):
        card = self.panel.node_cards()[1]
        card.text_field.setText("Da FUQ ?!!")
        self.assertEqual(card.count_label.text(), "10/63")

    def test_an_over_long_value_marks_the_card_over(self):
        card = self.panel.node_cards()[0]
        card.text_field.setText("A" * 70)
        self.assertTrue(card.is_over())
        self.assertEqual(card.property("over"), "true")

    def test_shortening_it_again_clears_the_mark(self):
        card = self.panel.node_cards()[0]
        card.text_field.setText("A" * 70)
        card.text_field.setText("short")
        self.assertFalse(card.is_over())
        self.assertEqual(card.property("over"), "false")


class TestPreview(DialogPanelTestCase):
    """AC7/R8: the preview wraps at 12 characters."""

    def test_the_preview_is_the_wrapped_text(self):
        card = self.panel.node_cards()[0]
        self.assertEqual(
            card.preview_label.text(),
            "\n".join(dialog_model.wrap_preview("Roads. Parts. Sharp. Racer.")),
        )

    def test_no_preview_line_is_longer_than_twelve_characters(self):
        card = self.panel.node_cards()[0]
        for line in card.preview_label.text().splitlines():
            self.assertLessEqual(len(line), 12, line)

    def test_the_preview_follows_the_text_as_it_is_typed(self):
        card = self.panel.node_cards()[2]
        card.text_field.setText("Watch the east corner")
        self.assertEqual(
            card.preview_label.text(),
            "\n".join(dialog_model.wrap_preview("Watch the east corner")),
        )


class TestLinkChips(DialogPanelTestCase):
    """The prototype's `next → [1]` and `[Races] → [2]` chips."""

    def test_a_narration_node_shows_its_next(self):
        self.assertEqual(
            self.panel.node_cards()[0].link_texts(), ["next → [1]"])

    def test_a_choice_node_shows_one_chip_per_choice(self):
        self.assertEqual(
            self.panel.node_cards()[1].link_texts(),
            ["[Races] → [2]", "[Shop] → SHOP"],
        )

    def test_a_node_ending_the_tree_says_so(self):
        self.assertEqual(
            self.panel.node_cards()[2].link_texts(), ["next → END"])


@unittest.skipIf(NO_GAME_REPO, NO_GAME_REPO_REASON)
class TestUnreadableFiles(unittest.TestCase):
    """A worktree with no dialog assets must state that, not crash."""

    def setUp(self):
        theme.apply(_app)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.repo = make_fixture_worktree(self.root)
        (self.repo / "assets" / "dialog" / "npcs.json").unlink()
        self.binding = bind_over(self.root, self.repo)
        self.panel = DialogPanel(self.binding, None)

    def tearDown(self):
        self.panel.stop_and_wait()
        self.panel.deleteLater()
        self._tmp.cleanup()

    def test_the_status_names_the_missing_file(self):
        self.assertIn("npcs.json", self.panel.status_text())

    def test_no_cards_are_shown(self):
        self.assertEqual(self.panel.node_cards(), [])


class TestNoBinding(unittest.TestCase):
    """No game repository bound: the panel states it and offers nothing.
    Not skipped -- this is the CI case, and it must be covered there."""

    def setUp(self):
        theme.apply(_app)
        self.error = project.BindingError("game_repo", "nothing is bound")
        self.panel = DialogPanel(None, self.error)

    def tearDown(self):
        self.panel.stop_and_wait()
        self.panel.deleteLater()

    def test_the_status_carries_the_binding_failure(self):
        self.assertIn("nothing is bound", self.panel.status_text())

    def test_no_npcs_and_no_cards(self):
        self.assertEqual(self.panel.npc_names(), [])
        self.assertEqual(self.panel.node_cards(), [])


if __name__ == "__main__":
    unittest.main()
