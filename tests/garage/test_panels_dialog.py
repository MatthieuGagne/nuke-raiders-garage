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
import time
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


class DialogPanelTestCase(unittest.TestCase):
    """Not gated on a bound game repository (finding 4, Task 7): the
    fixture works from `NPCS`/`HUBS`/`CONFIG_H` above and needs no real
    `dialog_to_c.py`, so every subclass runs in CI, where no game
    repository is bound. `make_fixture_worktree` embeds the real
    generator only when one happens to be available and it is harmless
    either way -- nothing below invokes it. Only the two classes that
    actually run the generator or read the real game repository's data
    (`TestGeneratorRuns`, `TestAgainstRealGameData`) carry their own
    `@unittest.skipIf(NO_GAME_REPO, ...)`.
    """

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


class TestUnreadableFiles(unittest.TestCase):
    """A worktree with no dialog assets must state that, not crash. Runs
    against a temp fixture, not the real generator, so it is not gated
    (finding 4)."""

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

    def test_the_save_button_is_disabled_after_a_load_error(self):
        # Finding 8: the other early return in refresh() (a DialogError)
        # must leave Save disabled too, not at Qt's default enabled state.
        self.assertFalse(self.panel.save_button.isEnabled())


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

    def test_the_save_button_is_disabled_with_nothing_to_save(self):
        # Finding 8: refresh() returned before _refresh_refusal() ran in
        # exactly this case, leaving Save at Qt's default enabled state.
        self.assertFalse(self.panel.save_button.isEnabled())


class TestEditingText(DialogPanelTestCase):
    """AC2: text edited in Garage appears in the JSON after a save."""

    def test_saving_writes_the_edited_text(self):
        card = self.panel.node_cards()[0]
        card.text_field.setText("Fresh line.")

        self.assertTrue(self.panel.save())

        self.assertEqual(
            self.saved_npcs()["npcs"][0]["nodes"][0]["text"], "Fresh line.")

    def test_saving_emits_saved(self):
        seen = []
        self.panel.saved.connect(lambda: seen.append(True))
        self.panel.save()
        self.assertEqual(seen, [True])


class TestAddAndDeleteNode(DialogPanelTestCase):
    """R3/AC3: add a node, delete a node, and leave no reference wrong."""

    def test_adding_a_node_shows_a_new_card(self):
        self.panel.add_node()
        self.assertEqual(len(self.panel.node_cards()), 4)
        self.assertEqual(self.panel.node_cards()[3].id_label.text(), "[3]")

    def test_an_added_node_is_saved(self):
        self.panel.add_node()
        self.panel.save()
        self.assertEqual(len(self.saved_npcs()["npcs"][0]["nodes"]), 4)

    def test_deleting_a_node_removes_its_card(self):
        self.panel.delete_node(self.panel.node_cards()[1])
        self.assertEqual(
            [c.id_label.text() for c in self.panel.node_cards()],
            ["[0]", "[1]"],
        )

    def test_a_deleted_nodes_referrers_are_renumbered_in_the_saved_json(self):
        # Node [0] points at [1]; deleting [1] must leave [0] at END, and
        # the old [2] must have become [1].
        self.panel.delete_node(self.panel.node_cards()[1])
        self.panel.save()

        nodes = self.saved_npcs()["npcs"][0]["nodes"]
        self.assertEqual([n["idx"] for n in nodes], [0, 1])
        self.assertEqual(nodes[0]["next"], ["END"])

    def test_deleting_updates_the_npc_lists_node_count(self):
        self.panel.delete_node(self.panel.node_cards()[1])
        self.assertIn("2", self.panel.npc_list.item(0).text())


class TestSetNext(DialogPanelTestCase):
    """R5/AC4: a next pointer set in Garage appears in the saved JSON."""

    def test_setting_a_narration_next_to_a_node(self):
        self.panel.set_next(self.panel.node_cards()[0], 0, 2)
        self.panel.save()
        self.assertEqual(
            self.saved_npcs()["npcs"][0]["nodes"][0]["next"], [2])

    def test_setting_a_narration_next_to_end(self):
        self.panel.set_next(self.panel.node_cards()[0], 0, "END")
        self.panel.save()
        self.assertEqual(
            self.saved_npcs()["npcs"][0]["nodes"][0]["next"], ["END"])

    def test_setting_one_choice_slot_leaves_the_other_alone(self):
        self.panel.set_next(self.panel.node_cards()[1], 0, "END")
        self.panel.save()
        self.assertEqual(
            self.saved_npcs()["npcs"][0]["nodes"][1]["next"], ["END", "SHOP"])

    def test_the_chip_redraws_after_the_change(self):
        self.panel.set_next(self.panel.node_cards()[0], 0, "END")
        self.assertEqual(
            self.panel.node_cards()[0].link_texts(), ["next → END"])


class TestChoices(DialogPanelTestCase):
    """R6/AC5: between zero and three choices, and no fourth."""

    def test_adding_a_choice_shows_a_chip_for_it(self):
        card = self.panel.node_cards()[0]
        self.panel.add_choice(card, "Yes")
        self.assertEqual(card.link_texts(), ["[Yes] → [1]"])

    def test_a_choice_is_saved(self):
        self.panel.add_choice(self.panel.node_cards()[0], "Yes")
        self.panel.save()
        node = self.saved_npcs()["npcs"][0]["nodes"][0]
        self.assertEqual(node["choices"], ["Yes"])
        self.assertEqual(node["next"], [1])

    def test_a_fourth_choice_is_refused_and_said_in_the_log(self):
        card = self.panel.node_cards()[1]
        self.panel.add_choice(card, "Third")
        self.panel.add_choice(card, "Fourth")
        self.assertEqual(len(card.node["choices"]), 3)
        self.assertIn("3", self.panel.log_text())

    def test_removing_a_choice_removes_its_chip(self):
        card = self.panel.node_cards()[1]
        self.panel.remove_choice(card, 0)
        self.assertEqual(card.link_texts(), ["[Shop] → SHOP"])


class TestEditingControlsAreReachable(DialogPanelTestCase):
    """Finding 1: the edit operations `dialog_model` already offers
    (delete a node, set a next, add/remove a choice) must be reachable
    through a widget a user can actually click or type into -- not only
    through a test calling the panel's method directly, which is exactly
    the gap that let this ship without them.
    """

    def test_clicking_delete_node_removes_the_card(self):
        card = self.panel.node_cards()[1]
        card.delete_button.click()
        self.assertEqual(
            [c.id_label.text() for c in self.panel.node_cards()],
            ["[0]", "[1]"],
        )

    def test_a_deleted_nodes_referrers_are_renumbered_after_a_button_click(self):
        self.panel.node_cards()[1].delete_button.click()
        self.panel.save()
        nodes = self.saved_npcs()["npcs"][0]["nodes"]
        self.assertEqual([n["idx"] for n in nodes], [0, 1])
        self.assertEqual(nodes[0]["next"], ["END"])

    def test_a_next_combo_is_offered_per_next_slot(self):
        narration_card = self.panel.node_cards()[0]
        self.assertEqual(len(narration_card.next_combos()), 1)
        choice_card = self.panel.node_cards()[1]
        self.assertEqual(len(choice_card.next_combos()), 2)

    def test_a_next_combos_entries_are_the_model_and_the_target_reads(self):
        card = self.panel.node_cards()[0]
        combo = card.next_combos()[0]
        texts = [combo.itemText(i) for i in range(combo.count())]
        # next_targets(nodes, 0) is [1, 2, "END", "SHOP"] for this
        # three-node tree; each reads as the link chips already do.
        self.assertEqual(
            dialog_model.next_targets(self.panel.selected_nodes(), 0),
            [1, 2, "END", "SHOP"],
        )
        self.assertEqual(texts, ["[1]", "[2]", "END", "SHOP"])

    def test_changing_a_next_combo_sets_the_slot(self):
        card = self.panel.node_cards()[0]
        combo = card.next_combos()[0]
        combo.setCurrentIndex(combo.findText("[2]"))
        self.assertEqual(card.node["next"], [2])

    def test_a_next_combo_change_is_saved(self):
        card = self.panel.node_cards()[0]
        combo = card.next_combos()[0]
        combo.setCurrentIndex(combo.findText("END"))
        self.panel.save()
        self.assertEqual(
            self.saved_npcs()["npcs"][0]["nodes"][0]["next"], ["END"])

    def test_a_second_next_combo_sets_only_its_own_slot(self):
        card = self.panel.node_cards()[1]
        combo = card.next_combos()[1]
        self.assertEqual(_combo_current_target(combo), "SHOP")
        combo.setCurrentIndex(combo.findText("END"))
        self.assertEqual(card.node["next"], [2, "END"])

    def test_rebuild_cards_does_not_modify_any_nodes_next(self):
        # The classic bug this finding calls out: populating a combo
        # fires currentIndexChanged, which must not be wired up yet when
        # that happens, or a plain rebuild would silently rewrite every
        # node's next to whatever the first item in each combo is.
        nodes = self.panel.selected_nodes()
        before = [list(n["next"]) for n in nodes]
        self.panel.rebuild_cards()
        after = [list(n["next"]) for n in self.panel.selected_nodes()]
        self.assertEqual(before, after)

    def test_typing_a_label_and_clicking_add_choice_adds_it(self):
        card = self.panel.node_cards()[0]
        card.choice_label_field.setText("Yes")
        card.add_choice_button.click()
        self.assertEqual(card.node["choices"], ["Yes"])
        self.assertEqual(card.link_texts(), ["[Yes] → [1]"])

    def test_add_choice_clears_the_label_field(self):
        card = self.panel.node_cards()[0]
        card.choice_label_field.setText("Yes")
        card.add_choice_button.click()
        self.assertEqual(card.choice_label_field.text(), "")

    def test_a_remove_choice_button_exists_per_choice(self):
        card = self.panel.node_cards()[1]
        self.assertEqual(len(card.remove_choice_buttons()), 2)

    def test_clicking_remove_choice_removes_it(self):
        card = self.panel.node_cards()[1]
        card.remove_choice_buttons()[0].click()
        self.assertEqual(card.node["choices"], ["Shop"])
        self.assertEqual(card.link_texts(), ["[Shop] → SHOP"])


def _combo_current_target(combo):
    return combo.itemData(combo.currentIndex())


class TestRenameNpc(DialogPanelTestCase):
    """R3: rename an NPC."""

    def test_the_list_shows_the_new_name(self):
        self.panel.rename_selected_npc("grease")
        self.assertEqual(self.panel.npc_names(), ["GREASE", "TRADER"])

    def test_the_new_name_is_saved(self):
        self.panel.rename_selected_npc("grease")
        self.panel.save()
        self.assertEqual(self.saved_npcs()["npcs"][0]["name"], "GREASE")


class TestNpcCeiling(DialogPanelTestCase):
    """AC9: Garage refuses to add an NPC beyond the maximum the game
    supports. The fixture's config.h says MAX_NPCS 2, and the fixture has
    two NPCs. Reads only the fixture's own config.h, never the generator,
    so it is not gated (finding 4)."""

    def test_adding_a_third_npc_is_refused(self):
        self.panel.add_npc("SCOUT")
        self.assertEqual(self.panel.npc_names(), ["STEEVE", "TRADER"])

    def test_the_refusal_names_the_limit(self):
        self.panel.add_npc("SCOUT")
        self.assertIn("2", self.panel.log_text())

    def test_a_raised_ceiling_lets_the_npc_in(self):
        self.binding.config_h.write_text(
            "#define MAX_NPCS     3\n", encoding="utf-8")
        self.panel.refresh()
        self.panel.add_npc("SCOUT")
        self.assertEqual(self.panel.npc_names(), ["STEEVE", "TRADER", "SCOUT"])


class TestSaveRefusal(DialogPanelTestCase):
    """AC8: Garage refuses to save when a node holds 63 characters or
    more, and names that node."""

    def test_an_over_long_node_blocks_the_save(self):
        self.panel.node_cards()[1].text_field.setText("A" * 70)
        self.assertFalse(self.panel.save())

    def test_the_file_is_untouched_by_a_refused_save(self):
        before = (self.repo / "assets" / "dialog" / "npcs.json").read_bytes()
        self.panel.node_cards()[1].text_field.setText("A" * 70)
        self.panel.save()
        after = (self.repo / "assets" / "dialog" / "npcs.json").read_bytes()
        self.assertEqual(before, after)

    def test_the_refusal_names_the_npc_and_the_node(self):
        self.panel.node_cards()[1].text_field.setText("A" * 70)
        self.panel.save()
        self.assertIn("STEEVE", self.panel.refusal_text())
        self.assertIn("[1]", self.panel.refusal_text())

    def test_exactly_sixty_three_characters_is_refused(self):
        self.panel.node_cards()[1].text_field.setText("A" * 63)
        self.assertFalse(self.panel.save())

    def test_sixty_two_characters_saves(self):
        self.panel.node_cards()[1].text_field.setText("A" * 62)
        self.assertTrue(self.panel.save())

    def test_the_save_button_is_disabled_while_a_node_is_over(self):
        self.panel.node_cards()[1].text_field.setText("A" * 70)
        self.assertFalse(self.panel.save_button.isEnabled())

    def test_it_is_enabled_again_once_the_node_fits(self):
        card = self.panel.node_cards()[1]
        card.text_field.setText("A" * 70)
        card.text_field.setText("fits")
        self.assertTrue(self.panel.save_button.isEnabled())

    def test_the_refusal_clears_once_the_node_fits(self):
        card = self.panel.node_cards()[1]
        card.text_field.setText("A" * 70)
        card.text_field.setText("fits")
        self.assertEqual(self.panel.refusal_text(), "")


@unittest.skipIf(NO_GAME_REPO, NO_GAME_REPO_REASON)
class TestGeneratorRuns(DialogPanelTestCase):
    """AC10/AC11: dialog_to_c.py runs after a save, its output appears in
    the window, and what it writes is what a terminal writes.

    The fixture holds the game repository's real dialog_to_c.py, and the
    run is a real subprocess -- a stub would prove the wiring and nothing
    about AC11.
    """

    npcs = NPCS

    def _save_and_wait(self):
        self.assertTrue(self.panel.save())
        deadline = 30.0
        step = 0.05
        waited = 0.0
        while self.panel.is_running() and waited < deadline:
            QApplication.processEvents()
            time.sleep(step)
            waited += step
        QApplication.processEvents()
        self.assertFalse(self.panel.is_running(), "the generator never ended")

    def test_the_generator_writes_the_dialog_source(self):
        self._save_and_wait()
        self.assertTrue((self.repo / "src" / "dialog_data.c").is_file())

    def test_the_generator_writes_the_hub_source(self):
        self._save_and_wait()
        self.assertTrue((self.repo / "src" / "hub_data.c").is_file())

    def test_its_output_appears_in_the_window(self):
        self._save_and_wait()
        self.assertIn("dialog_data.c", self.panel.log_text())

    def test_the_command_is_echoed_before_it_runs(self):
        self._save_and_wait()
        self.assertIn("$ python -u tools/dialog_to_c.py", self.panel.log_text())

    def test_the_sources_match_what_a_terminal_produces(self):
        """AC11, checked rather than asserted: the same generator, run the
        way the Makefile runs it, must produce byte-identical output."""
        self._save_and_wait()
        from_garage = (self.repo / "src" / "dialog_data.c").read_bytes()
        hub_from_garage = (self.repo / "src" / "hub_data.c").read_bytes()

        (self.repo / "src" / "dialog_data.c").unlink()
        (self.repo / "src" / "hub_data.c").unlink()
        subprocess.run(
            [sys.executable, "tools/dialog_to_c.py",
             "assets/dialog/npcs.json", "src/dialog_data.c",
             "--hubs-json", "assets/dialog/hubs.json",
             "--hub-out", "src/hub_data.c",
             "--config-h", "src/config.h"],
            cwd=str(self.repo), check=True, capture_output=True, text=True,
        )

        self.assertEqual(from_garage,
                         (self.repo / "src" / "dialog_data.c").read_bytes())
        self.assertEqual(hub_from_garage,
                         (self.repo / "src" / "hub_data.c").read_bytes())

    def test_a_refused_save_runs_no_generator(self):
        self.panel.node_cards()[1].text_field.setText("A" * 70)
        self.assertFalse(self.panel.save())
        self.assertFalse(self.panel.is_running())
        self.assertFalse((self.repo / "src" / "dialog_data.c").exists())


@unittest.skipIf(NO_GAME_REPO, NO_GAME_REPO_REASON)
class TestAgainstRealGameData(unittest.TestCase):
    """Task 7's acceptance pass: the real DialogPanel, driven against the
    real game repository's own eight-NPC production data -- copied into a
    throwaway temp git repo, never the bound checkout itself, which stays
    untouched.
    """

    def setUp(self):
        theme.apply(_app)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.repo = self.root / "nuke-raider"
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "tools").mkdir(parents=True)
        (self.repo / "assets" / "dialog").mkdir(parents=True)

        real_repo = project.bind().active_worktree.path
        for rel in (
            "assets/dialog/npcs.json",
            "assets/dialog/hubs.json",
            "src/config.h",
            "tools/dialog_to_c.py",
        ):
            src = real_repo / rel
            dst = self.repo / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())

        _run_git(["init", "-b", "master"], self.repo)
        _run_git(["config", "user.email", "test@example.com"], self.repo)
        _run_git(["config", "user.name", "Test"], self.repo)
        _run_git(["add", "."], self.repo)
        _run_git(["commit", "-m", "init"], self.repo)
        _run_git(["remote", "add", "origin", GAME_REPO_REMOTE_URL], self.repo)

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

    def _save_and_wait(self):
        # Same waiting pattern as TestGeneratorRuns._save_and_wait, above.
        self.assertTrue(self.panel.save())
        deadline = 30.0
        step = 0.05
        waited = 0.0
        while self.panel.is_running() and waited < deadline:
            QApplication.processEvents()
            time.sleep(step)
            waited += step
        QApplication.processEvents()
        self.assertFalse(self.panel.is_running(), "the generator never ended")

    def test_every_npc_is_listed(self):
        self.assertEqual(len(self.panel.npc_names()), 8)

    def test_the_selected_npcs_nodes_each_get_a_card(self):
        npc = self.panel.selected_npc()
        self.assertEqual(len(self.panel.node_cards()), len(npc["nodes"]))

    def test_an_edit_to_a_nodes_text_survives_a_save(self):
        card = self.panel.node_cards()[0]
        card.text_field.setText("A fresh line from the acceptance pass.")

        self._save_and_wait()

        npc = self.panel.selected_npc()
        self.assertEqual(
            self.saved_npcs()["npcs"][npc["id"]]["nodes"][0]["text"],
            "A fresh line from the acceptance pass.",
        )

    def test_a_node_pushed_to_63_characters_blocks_the_save(self):
        npc = self.panel.selected_npc()
        card = self.panel.node_cards()[0]
        card.text_field.setText("A" * 63)

        self.assertFalse(self.panel.save())
        self.assertIn(npc["name"], self.panel.refusal_text())
        self.assertIn("[0]", self.panel.refusal_text())

    def test_adding_a_ninth_npc_is_refused_naming_the_real_ceiling(self):
        self.panel.add_npc("NINTH")

        self.assertEqual(len(self.panel.npc_names()), 8)
        self.assertIn("8", self.panel.log_text())

    def test_the_generated_sources_match_a_terminal_run_byte_for_byte(self):
        self._save_and_wait()
        from_garage = (self.repo / "src" / "dialog_data.c").read_bytes()
        hub_from_garage = (self.repo / "src" / "hub_data.c").read_bytes()

        (self.repo / "src" / "dialog_data.c").unlink()
        (self.repo / "src" / "hub_data.c").unlink()
        subprocess.run(
            [sys.executable, "tools/dialog_to_c.py",
             "assets/dialog/npcs.json", "src/dialog_data.c",
             "--hubs-json", "assets/dialog/hubs.json",
             "--hub-out", "src/hub_data.c",
             "--config-h", "src/config.h"],
            cwd=str(self.repo), check=True, capture_output=True, text=True,
        )

        self.assertEqual(
            from_garage, (self.repo / "src" / "dialog_data.c").read_bytes())
        self.assertEqual(
            hub_from_garage, (self.repo / "src" / "hub_data.c").read_bytes())


if __name__ == "__main__":
    unittest.main()
