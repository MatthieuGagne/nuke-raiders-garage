"""Core coverage for the dialog panel (spec P3, issue #4).

No PySide6 import belongs in this file, directly or transitively: it is
reached by `make test`, which AC13 requires to pass on a machine with no
Qt installed. Panel coverage lives in tests/garage/test_panels_dialog.py.

Fixtures build real git repositories in a temp directory. Nothing here
hardcodes a path into a checkout.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.garage.core import dialog_model, project

GAME_REPO_REMOTE_URL = "https://github.com/MatthieuGagne/gmb-nuke-raider.git"

CONFIG_H = """\
#define MAX_NPCS     8
#define DIALOG_TEXT_BUF_LEN   64u
#define MAX_HUB_NPCS           3u
"""

NPCS = {
    "npcs": [
        {
            "id": 0,
            "name": "STEEVE",
            "vendor_field": "ARMOR",
            "nodes": [
                {"idx": 0, "text": "Roads. Parts.", "choices": [], "next": [1]},
                {"idx": 1, "text": "Da FUQ ?", "choices": ["Races", "Shop"],
                 "next": [2, "SHOP"]},
                {"idx": 2, "text": "Stay sharp.", "choices": [], "next": ["END"]},
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

HUBS = {
    "hubs": [
        {"id": 0, "name": "RUST TOWN", "npc_ids": [0, 1]},
        {"id": 1, "name": "JANKY CITY", "npc_ids": []},
    ]
}


def tmp_root(tmp: str) -> Path:
    """A temporary directory, spelled the way Garage spells it -- see the
    same helper in tests/test_garage_core.py for why `resolve()` matters
    on Windows."""
    return Path(tmp).resolve()


def _run_git(args, cwd):
    return subprocess.run(
        ["git"] + args, cwd=str(cwd), check=True, capture_output=True, text=True
    )


def make_game_repo(path: Path, npcs=None, hubs=None, config_h=CONFIG_H) -> Path:
    """A real git repository holding the two dialog files, a config.h and
    a stub generator, with the game repository's origin remote so
    `project.bind` accepts it."""
    (path / "assets" / "dialog").mkdir(parents=True, exist_ok=True)
    (path / "src").mkdir(parents=True, exist_ok=True)
    (path / "tools").mkdir(parents=True, exist_ok=True)
    write_json(path / "assets" / "dialog" / "npcs.json",
               NPCS if npcs is None else npcs)
    write_json(path / "assets" / "dialog" / "hubs.json",
               HUBS if hubs is None else hubs)
    (path / "src" / "config.h").write_text(config_h, encoding="utf-8")
    (path / "tools" / "dialog_to_c.py").write_text("# stub\n", encoding="utf-8")
    _run_git(["init", "-b", "master"], path)
    _run_git(["config", "user.email", "test@example.com"], path)
    _run_git(["config", "user.name", "Test"], path)
    _run_git(["add", "."], path)
    _run_git(["commit", "-m", "init"], path)
    _run_git(["remote", "add", "origin", GAME_REPO_REMOTE_URL], path)
    return path


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


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


class DialogModelTestCase(unittest.TestCase):
    """A bound throwaway game repository, rebuilt per test."""

    npcs = None
    hubs = None
    config_h = CONFIG_H

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = tmp_root(self._tmp.name)
        self.repo = make_game_repo(
            self.root / "nuke-raider",
            npcs=self.npcs, hubs=self.hubs, config_h=self.config_h,
        )
        self.binding = bind_over(self.root, self.repo)

    def tearDown(self):
        self._tmp.cleanup()

    def reload(self):
        return dialog_model.load(self.binding)


class TestLoad(DialogModelTestCase):
    """R1/R14: both files read from the active worktree, through the
    binding."""

    def test_load_reads_both_files(self):
        data = self.reload()
        self.assertEqual([n["name"] for n in data.npcs], ["STEEVE", "TRADER"])
        self.assertEqual([h["name"] for h in data.hubs],
                         ["RUST TOWN", "JANKY CITY"])

    def test_load_records_the_paths_it_read(self):
        data = self.reload()
        self.assertEqual(
            data.npcs_path,
            self.binding.resolve("assets", "dialog", "npcs.json"),
        )
        self.assertEqual(
            data.hubs_path,
            self.binding.resolve("assets", "dialog", "hubs.json"),
        )

    def test_a_missing_npcs_file_is_a_dialog_error_naming_it(self):
        (self.repo / "assets" / "dialog" / "npcs.json").unlink()
        with self.assertRaises(dialog_model.DialogError) as cm:
            self.reload()
        self.assertIn("npcs.json", cm.exception.message)

    def test_malformed_json_is_a_dialog_error_naming_the_file(self):
        (self.repo / "assets" / "dialog" / "hubs.json").write_text(
            "{not json", encoding="utf-8")
        with self.assertRaises(dialog_model.DialogError) as cm:
            self.reload()
        self.assertIn("hubs.json", cm.exception.message)


class TestSave(DialogModelTestCase):
    """AC2: what Garage edited is what the file holds afterwards."""

    def test_save_writes_edited_text_back(self):
        data = self.reload()
        data.npcs[0]["nodes"][0]["text"] = "New line."
        dialog_model.save(data)

        written = json.loads(
            (self.repo / "assets" / "dialog" / "npcs.json").read_text(
                encoding="utf-8"))
        self.assertEqual(written["npcs"][0]["nodes"][0]["text"], "New line.")

    def test_save_writes_the_hubs_file_too(self):
        data = self.reload()
        data.hubs[1]["name"] = "STEEL CITY"
        dialog_model.save(data)

        written = json.loads(
            (self.repo / "assets" / "dialog" / "hubs.json").read_text(
                encoding="utf-8"))
        self.assertEqual(written["hubs"][1]["name"], "STEEL CITY")

    def test_save_keeps_the_two_space_indent_and_trailing_newline(self):
        # The game repository's files are written by dialog_to_c.py's
        # sibling with indent=2 and a trailing newline. Garage must not
        # rewrite every line of a file it only edited one field of.
        data = self.reload()
        dialog_model.save(data)
        text = (self.repo / "assets" / "dialog" / "npcs.json").read_text(
            encoding="utf-8")
        self.assertTrue(text.endswith("}\n"))
        self.assertIn('\n  "npcs": [', text)

    def test_save_writes_lf_line_endings_on_every_platform(self):
        data = self.reload()
        dialog_model.save(data)
        raw = (self.repo / "assets" / "dialog" / "npcs.json").read_bytes()
        self.assertNotIn(b"\r\n", raw)


class TestWrapPreview(unittest.TestCase):
    """AC7/R8: the Game Boy dialog box wraps at 12 characters."""

    def test_short_text_is_one_line(self):
        self.assertEqual(dialog_model.wrap_preview("Da FUQ ?"), ["Da FUQ ?"])

    def test_no_line_exceeds_twelve_characters(self):
        lines = dialog_model.wrap_preview(
            "Roads. Parts. Sharp. Racer. Grease.")
        self.assertTrue(lines)
        for line in lines:
            self.assertLessEqual(len(line), 12, line)

    def test_wrapping_happens_at_word_boundaries(self):
        self.assertEqual(
            dialog_model.wrap_preview("Stay sharp out there"),
            ["Stay sharp", "out there"],
        )

    def test_a_word_longer_than_the_width_is_hard_wrapped(self):
        self.assertEqual(
            dialog_model.wrap_preview("Supercalifragilistic"),
            ["Supercalifra"],  # the first 12 characters; the rest is cut
        )

    def test_at_most_five_rows_come_back(self):
        lines = dialog_model.wrap_preview(" ".join(["word"] * 40))
        self.assertLessEqual(len(lines), 5)

    def test_empty_text_is_no_lines(self):
        self.assertEqual(dialog_model.wrap_preview(""), [])


class TestLengthLimit(unittest.TestCase):
    """AC6/AC8. Garage refuses at 63 characters or more -- one stricter
    than dialog_to_c.py's `> 63`. See the plan's note on the off-by-one."""

    def test_a_short_node_is_not_over(self):
        self.assertFalse(dialog_model.is_over_limit("A" * 62))

    def test_exactly_sixty_three_is_over(self):
        self.assertTrue(dialog_model.is_over_limit("A" * 63))

    def test_longer_than_sixty_three_is_over(self):
        self.assertTrue(dialog_model.is_over_limit("A" * 80))

    def test_the_count_label_reads_used_over_limit(self):
        self.assertEqual(dialog_model.count_label("A" * 41), "41/63")


class TestReadMaxNpcs(DialogModelTestCase):
    """R10/AC9: the ceiling is the game's, read from its config.h at
    runtime -- never a constant in Garage."""

    def test_the_ceiling_comes_from_the_bound_config_h(self):
        self.assertEqual(dialog_model.read_max_npcs(self.binding), 8)

    def test_a_different_value_in_the_header_is_the_one_reported(self):
        self.binding.config_h.write_text(
            "#define MAX_NPCS     3\n", encoding="utf-8")
        self.assertEqual(dialog_model.read_max_npcs(self.binding), 3)

    def test_a_header_without_the_define_is_a_dialog_error(self):
        self.binding.config_h.write_text("/* nothing */\n", encoding="utf-8")
        with self.assertRaises(dialog_model.DialogError) as cm:
            dialog_model.read_max_npcs(self.binding)
        self.assertIn("MAX_NPCS", cm.exception.message)


def narration(idx, text="hi", nxt="END"):
    return {"idx": idx, "text": text, "choices": [], "next": [nxt]}


def branching(idx, labels, nexts, text="pick"):
    return {"idx": idx, "text": text, "choices": list(labels),
            "next": list(nexts)}


class TestAddNode(unittest.TestCase):
    """R3: add a node."""

    def test_a_new_node_lands_at_the_end_with_the_next_index(self):
        nodes = [narration(0)]
        added = dialog_model.add_node(nodes)
        self.assertEqual(len(nodes), 2)
        self.assertIs(nodes[1], added)
        self.assertEqual(added["idx"], 1)

    def test_a_new_node_is_a_narration_node_ending_the_tree(self):
        nodes = []
        added = dialog_model.add_node(nodes)
        self.assertEqual(added["choices"], [])
        self.assertEqual(added["next"], ["END"])

    def test_a_new_nodes_text_is_within_the_limit(self):
        added = dialog_model.add_node([])
        self.assertFalse(dialog_model.is_over_limit(added["text"]))


class TestDeleteNodeRenumbers(unittest.TestCase):
    """R4/AC3: after a delete, no next pointer and no choice points at a
    wrong node."""

    def test_the_node_is_gone(self):
        nodes = [narration(0, nxt=1), narration(1, nxt=2), narration(2)]
        dialog_model.delete_node(nodes, 1)
        self.assertEqual(len(nodes), 2)

    def test_idx_fields_are_resequenced(self):
        nodes = [narration(0, nxt=1), narration(1, nxt=2), narration(2)]
        dialog_model.delete_node(nodes, 1)
        self.assertEqual([n["idx"] for n in nodes], [0, 1])

    def test_a_reference_to_the_deleted_node_becomes_end(self):
        nodes = [narration(0, nxt=1), narration(1)]
        dialog_model.delete_node(nodes, 1)
        self.assertEqual(nodes[0]["next"], ["END"])

    def test_a_reference_above_the_deleted_node_is_decremented(self):
        nodes = [narration(0, nxt=2), narration(1), narration(2)]
        dialog_model.delete_node(nodes, 1)
        self.assertEqual(nodes[0]["next"], [1])

    def test_a_reference_below_the_deleted_node_is_untouched(self):
        nodes = [narration(0, nxt=0), narration(1), narration(2)]
        dialog_model.delete_node(nodes, 2)
        self.assertEqual(nodes[0]["next"], [0])

    def test_end_and_shop_survive_a_delete(self):
        nodes = [branching(0, ["a", "b"], ["END", "SHOP"]), narration(1)]
        dialog_model.delete_node(nodes, 1)
        self.assertEqual(nodes[0]["next"], ["END", "SHOP"])

    def test_every_choice_slot_is_renumbered_not_only_the_first(self):
        nodes = [branching(0, ["a", "b", "c"], [1, 2, 3]),
                 narration(1), narration(2), narration(3)]
        dialog_model.delete_node(nodes, 2)
        self.assertEqual(nodes[0]["next"], [1, "END", 2])

    def test_deleting_the_only_node_leaves_a_stub_rather_than_nothing(self):
        # An NPC with no nodes is a slot dialog_to_c.py cannot generate a
        # tree for; the TUI keeps a one-node stub for the same reason.
        nodes = [narration(0)]
        dialog_model.delete_node(nodes, 0)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["idx"], 0)
        self.assertEqual(nodes[0]["next"], ["END"])

    def test_deleting_out_of_range_is_a_dialog_error(self):
        nodes = [narration(0)]
        with self.assertRaises(dialog_model.DialogError):
            dialog_model.delete_node(nodes, 7)


class TestSetNext(unittest.TestCase):
    """R5/AC4: point a node at another node, or at the end of the tree."""

    def test_setting_a_node_index(self):
        node = narration(0)
        dialog_model.set_next(node, 0, 2)
        self.assertEqual(node["next"], [2])

    def test_setting_end(self):
        node = narration(0, nxt=3)
        dialog_model.set_next(node, 0, "END")
        self.assertEqual(node["next"], ["END"])

    def test_setting_shop(self):
        node = narration(0)
        dialog_model.set_next(node, 0, "SHOP")
        self.assertEqual(node["next"], ["SHOP"])

    def test_setting_one_choice_slot_leaves_the_others_alone(self):
        node = branching(0, ["a", "b"], [1, 2])
        dialog_model.set_next(node, 1, "END")
        self.assertEqual(node["next"], [1, "END"])

    def test_a_slot_that_does_not_exist_is_a_dialog_error(self):
        node = narration(0)
        with self.assertRaises(dialog_model.DialogError):
            dialog_model.set_next(node, 2, "END")

    def test_a_target_that_is_neither_an_index_nor_a_sentinel_is_refused(self):
        node = narration(0)
        with self.assertRaises(dialog_model.DialogError):
            dialog_model.set_next(node, 0, "ELSEWHERE")


class TestNextTargets(unittest.TestCase):
    """What the panel's next combo offers."""

    def test_every_other_node_then_the_sentinels(self):
        nodes = [narration(0), narration(1), narration(2)]
        self.assertEqual(
            dialog_model.next_targets(nodes, 1), [0, 2, "END", "SHOP"])

    def test_a_node_is_never_offered_itself(self):
        nodes = [narration(0)]
        self.assertEqual(dialog_model.next_targets(nodes, 0), ["END", "SHOP"])


class TestChoices(unittest.TestCase):
    """R6/AC5: between zero and three choices, and the parallel `next`
    list stays parallel."""

    def test_the_first_choice_takes_over_the_narration_next(self):
        # The TUI appends here and leaves the narration `next` behind,
        # which produces one choice and two nexts -- a shape
        # dialog_to_c.py::validate rejects. Written fresh (R13), so this
        # is the corrected behaviour.
        node = narration(0, nxt=4)
        dialog_model.add_choice(node, "The races")
        self.assertEqual(node["choices"], ["The races"])
        self.assertEqual(node["next"], [4])

    def test_a_further_choice_appends_an_end_slot(self):
        node = narration(0, nxt=4)
        dialog_model.add_choice(node, "a")
        dialog_model.add_choice(node, "b")
        self.assertEqual(node["choices"], ["a", "b"])
        self.assertEqual(node["next"], [4, "END"])

    def test_a_fourth_choice_is_refused_and_the_node_is_unchanged(self):
        node = branching(0, ["a", "b", "c"], [1, 2, 3])
        with self.assertRaises(dialog_model.DialogError) as cm:
            dialog_model.add_choice(node, "d")
        self.assertIn("3", cm.exception.message)
        self.assertEqual(node["choices"], ["a", "b", "c"])
        self.assertEqual(node["next"], [1, 2, 3])

    def test_an_empty_label_is_refused(self):
        node = narration(0)
        with self.assertRaises(dialog_model.DialogError):
            dialog_model.add_choice(node, "   ")

    def test_removing_a_choice_removes_its_next_slot(self):
        node = branching(0, ["a", "b", "c"], [1, 2, 3])
        dialog_model.remove_choice(node, 1)
        self.assertEqual(node["choices"], ["a", "c"])
        self.assertEqual(node["next"], [1, 3])

    def test_removing_the_last_choice_leaves_one_next_slot(self):
        node = branching(0, ["a"], [5])
        dialog_model.remove_choice(node, 0)
        self.assertEqual(node["choices"], [])
        self.assertEqual(node["next"], [5])

    def test_removing_a_choice_that_is_not_there_is_a_dialog_error(self):
        node = branching(0, ["a"], [5])
        with self.assertRaises(dialog_model.DialogError):
            dialog_model.remove_choice(node, 3)


class TestSetText(unittest.TestCase):
    """R3: editing a node's text. The limit is not enforced here -- AC6
    wants the count to move as the user types, which means an over-long
    value must be storable and shown; AC8's refusal happens at save."""

    def test_the_text_is_stored(self):
        node = narration(0)
        dialog_model.set_text(node, "Watch the east corner.")
        self.assertEqual(node["text"], "Watch the east corner.")

    def test_an_over_long_value_is_stored_so_the_count_can_report_it(self):
        node = narration(0)
        dialog_model.set_text(node, "A" * 80)
        self.assertEqual(len(node["text"]), 80)
        self.assertTrue(dialog_model.is_over_limit(node["text"]))


if __name__ == "__main__":
    unittest.main()
