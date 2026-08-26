"""Coverage for tools/garage/core/workitem.py — MatthieuGagne/nuke-raiders-garage#5.

No Qt import anywhere in this file, and no network. Must pass with PySide6
absent: `make test` discovers it, and that target installs no Qt.

Every `gh` call goes through the injected `run` seam, so the sequence is
exercised end to end against recorded output rather than against GitHub.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.garage.core import project, workitem  # noqa: E402

GAME_REPO_REMOTE_URL = "https://github.com/MatthieuGagne/gmb-nuke-raider.git"

CONFIG_H = """\
#ifndef CONFIG_H
#define CONFIG_H

#define PLAYER_SPEED 4
#define PLAYER_HANDLING 3u
#define TILE_BASE 0xDF80U
#define MAX_NPCS 8

#endif
"""


def tmp_root(tmp: str) -> Path:
    """A temporary directory, spelled the way Garage spells it. On Windows
    the system temp path is a short name; `resolve()` gives the long form
    git and Garage both report, so path comparisons hold.
    """
    return Path(tmp).resolve()


def _run_git(args, cwd):
    return subprocess.run(
        ["git"] + args, cwd=str(cwd), check=True, capture_output=True, text=True
    )


def make_game_repo(path: Path, config_h: str = CONFIG_H) -> Path:
    """A real git repository with `src/config.h` committed at HEAD."""
    path.mkdir(parents=True, exist_ok=True)
    _run_git(["init", "-b", "master"], path)
    _run_git(["config", "user.email", "test@example.com"], path)
    _run_git(["config", "user.name", "Test"], path)
    (path / "src").mkdir(exist_ok=True)
    (path / "src" / "config.h").write_text(config_h, encoding="utf-8")
    _run_git(["add", "."], path)
    _run_git(["commit", "-m", "init"], path)
    _run_git(["remote", "add", "origin", GAME_REPO_REMOTE_URL], path)
    return path


def bind_over(root: Path, repo: Path) -> project.Binding:
    """A binding onto `repo`, recorded rather than detected — the fixture
    repository is not a sibling named `nuke-raider`.
    """
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


def edit_config(binding: project.Binding, replacements) -> None:
    text = binding.config_h.read_text(encoding="utf-8")
    for old, new in replacements:
        text = text.replace(old, new)
    binding.config_h.write_text(text, encoding="utf-8")


class TestChangedDefines(unittest.TestCase):
    """R4/AC5: each changed `#define`, with its value at HEAD and its new value."""

    def test_a_clean_worktree_has_no_changed_defines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            binding = bind_over(root, make_game_repo(root / "game"))

            self.assertEqual(workitem.changed_defines(binding), [])

    def test_an_edited_define_reports_head_and_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            binding = bind_over(root, make_game_repo(root / "game"))
            edit_config(binding, [("#define PLAYER_SPEED 4", "#define PLAYER_SPEED 6")])

            changes = workitem.changed_defines(binding)

            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0].name, "PLAYER_SPEED")
            self.assertEqual(changes[0].head_text, "4")
            self.assertEqual(changes[0].new_text, "6")

    def test_the_value_is_reported_as_written_not_as_parsed(self):
        # `0xDF80U` must not come back as `57216`: the issue body is read by
        # someone who will look the value up in config.h.
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            binding = bind_over(root, make_game_repo(root / "game"))
            edit_config(binding, [("#define TILE_BASE 0xDF80U", "#define TILE_BASE 0xDF00U")])

            changes = workitem.changed_defines(binding)

            self.assertEqual(changes[0].head_text, "0xDF80U")
            self.assertEqual(changes[0].new_text, "0xDF00U")

    def test_changes_are_ordered_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            binding = bind_over(root, make_game_repo(root / "game"))
            edit_config(
                binding,
                [
                    ("#define PLAYER_SPEED 4", "#define PLAYER_SPEED 6"),
                    ("#define MAX_NPCS 8", "#define MAX_NPCS 9"),
                ],
            )

            names = [c.name for c in workitem.changed_defines(binding)]

            self.assertEqual(names, ["MAX_NPCS", "PLAYER_SPEED"])

    def test_a_define_added_since_head_is_not_a_change(self):
        # It has no value at HEAD, so there is no "from" to state. R4 asks
        # for a comparison, and a comparison needs two sides.
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            binding = bind_over(root, make_game_repo(root / "game"))
            text = binding.config_h.read_text(encoding="utf-8")
            binding.config_h.write_text(
                text.replace("#endif", "#define BRAND_NEW 1\n\n#endif"), encoding="utf-8"
            )

            self.assertEqual(workitem.changed_defines(binding), [])


class TestBranchCommits(unittest.TestCase):
    """AC1's other half: a worktree can have earned a work item through a
    commit rather than through an uncommitted edit.
    """

    def test_a_branch_at_master_has_no_commits_of_its_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            repo = make_game_repo(root / "game")

            self.assertEqual(workitem.branch_commits(repo), [])

    def test_a_commit_on_a_branch_is_listed_subject_and_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            repo = make_game_repo(root / "game")
            _run_git(["checkout", "-b", "tune-speed"], repo)
            (repo / "src" / "config.h").write_text(
                CONFIG_H.replace("PLAYER_SPEED 4", "PLAYER_SPEED 6"), encoding="utf-8"
            )
            _run_git(["commit", "-am", "tune player speed"], repo)

            commits = workitem.branch_commits(repo)

            self.assertEqual(len(commits), 1)
            self.assertTrue(commits[0].endswith("tune player speed"))

    def test_an_unreadable_worktree_yields_no_commits_rather_than_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)

            self.assertEqual(workitem.branch_commits(root / "nowhere"), [])


class TestRefuseReason(unittest.TestCase):
    """AC1: the action is absent until there is something to file about."""

    def test_no_binding_is_refused(self):
        reason = workitem.refuse_reason(None, [], [])

        self.assertIsNotNone(reason)
        self.assertIn("No repository is bound", reason)

    def test_a_clean_worktree_with_no_commits_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            binding = bind_over(root, make_game_repo(root / "game"))

            reason = workitem.refuse_reason(binding, [], [])

            self.assertIsNotNone(reason)
            self.assertIn("nothing to file", reason)

    def test_one_changed_define_is_enough(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            binding = bind_over(root, make_game_repo(root / "game"))
            change = workitem.ChangedDefine("PLAYER_SPEED", "4", "6")

            self.assertIsNone(workitem.refuse_reason(binding, [change], []))

    def test_one_commit_is_enough(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            binding = bind_over(root, make_game_repo(root / "game"))

            self.assertIsNone(workitem.refuse_reason(binding, [], ["abc1234 tune"]))


class TestTitle(unittest.TestCase):
    """R3/AC4: the title starts with `chore:`, which is what gives the
    board `Type = Chore` when a human reads it back.
    """

    def test_a_bare_title_gains_the_prefix(self):
        self.assertEqual(workitem.title_for("tune player speed"), "chore: tune player speed")

    def test_a_title_that_already_has_the_prefix_does_not_gain_a_second(self):
        self.assertEqual(
            workitem.title_for("chore: tune player speed"), "chore: tune player speed"
        )

    def test_the_prefix_is_recognised_whatever_its_case_and_spacing(self):
        self.assertEqual(workitem.title_for("Chore:tune speed"), "chore: tune speed")

    def test_surrounding_whitespace_is_dropped(self):
        self.assertEqual(workitem.title_for("  tune speed  "), "chore: tune speed")

    def test_an_empty_title_is_refused_rather_than_prefixed(self):
        with self.assertRaises(workitem.WorkItemError):
            workitem.title_for("   ")


class TestBody(unittest.TestCase):
    """R4/AC5: the body lists each changed `#define` with both values."""

    CHANGES = [
        workitem.ChangedDefine("MAX_NPCS", "8", "9"),
        workitem.ChangedDefine("PLAYER_SPEED", "4", "6"),
    ]

    def test_every_changed_define_appears_with_both_values(self):
        body = workitem.compose_body(self.CHANGES, "", "tune-speed", [])

        self.assertIn("PLAYER_SPEED", body)
        self.assertIn("`4`", body)
        self.assertIn("`6`", body)
        self.assertIn("MAX_NPCS", body)
        self.assertIn("`8`", body)
        self.assertIn("`9`", body)

    def test_the_description_leads_the_body(self):
        body = workitem.compose_body(self.CHANGES, "The car turns too late.", "b", [])

        self.assertTrue(body.startswith("The car turns too late."))

    def test_a_body_with_no_description_still_lists_the_changes(self):
        body = workitem.compose_body(self.CHANGES, "", "tune-speed", [])

        self.assertIn("PLAYER_SPEED", body)
        self.assertNotIn("\n\n\n", body)

    def test_no_changed_define_says_so_rather_than_showing_an_empty_table(self):
        body = workitem.compose_body([], "", "tune-speed", ["abc1234 tune"])

        self.assertIn("No `#define` differs from HEAD", body)
        self.assertNotIn("| HEAD |", body)

    def test_commits_are_listed_when_there_are_any(self):
        body = workitem.compose_body([], "", "tune-speed", ["abc1234 tune player speed"])

        self.assertIn("abc1234 tune player speed", body)

    def test_the_branch_is_named_so_the_issue_can_be_traced_back(self):
        body = workitem.compose_body(self.CHANGES, "", "tune-speed", [])

        self.assertIn("tune-speed", body)

    def test_the_body_says_garage_filed_it(self):
        body = workitem.compose_body(self.CHANGES, "", "tune-speed", [])

        self.assertIn("Garage", body)


class TestClosesLine(unittest.TestCase):
    """R6/AC8: what goes on the clipboard is what the workflow greps for."""

    def test_the_line_is_the_form_the_workflow_matches(self):
        self.assertEqual(workitem.closes_line(614), "Closes #614")


# The shape `gh project field-list 3 --owner MatthieuGagne --format json`
# returns, trimmed to the two single-select fields this spec sets. Recorded
# from gh 2.96.0 on 2026-08-25. The ids below are deliberately not the real
# ones: nothing may pass by matching a literal a future edit will change.
FIELD_LIST_JSON = json.dumps(
    {
        "fields": [
            {"id": "PVTF_title", "name": "Title", "type": "ProjectV2Field"},
            {
                "id": "PVTSSF_status",
                "name": "Status",
                "type": "ProjectV2SingleSelectField",
                "options": [
                    {"id": "opt_todo", "name": "Todo"},
                    {"id": "opt_wip", "name": "In Progress"},
                    {"id": "opt_done", "name": "Done"},
                ],
            },
            {
                "id": "PVTSSF_type",
                "name": "Type",
                "type": "ProjectV2SingleSelectField",
                "options": [
                    {"id": "opt_epic", "name": "Epic"},
                    {"id": "opt_prd", "name": "PRD"},
                    {"id": "opt_chore", "name": "Chore"},
                ],
            },
        ],
        "totalCount": 3,
    }
)


class TestRepoSlug(unittest.TestCase):
    """The issue is filed in the game repository, resolved from its remote."""

    def test_an_https_remote_yields_owner_and_name(self):
        self.assertEqual(
            workitem.repo_slug("https://github.com/MatthieuGagne/gmb-nuke-raider.git"),
            "MatthieuGagne/gmb-nuke-raider",
        )

    def test_a_remote_without_the_git_suffix_still_yields_the_slug(self):
        self.assertEqual(
            workitem.repo_slug("https://github.com/MatthieuGagne/gmb-nuke-raider"),
            "MatthieuGagne/gmb-nuke-raider",
        )

    def test_an_ssh_remote_yields_the_same_slug(self):
        self.assertEqual(
            workitem.repo_slug("git@github.com:MatthieuGagne/gmb-nuke-raider.git"),
            "MatthieuGagne/gmb-nuke-raider",
        )

    def test_something_that_is_not_a_github_remote_yields_nothing(self):
        self.assertIsNone(workitem.repo_slug("https://example.com/whatever"))

    def test_no_remote_yields_nothing(self):
        self.assertIsNone(workitem.repo_slug(None))


class TestResolveOption(unittest.TestCase):
    """R5: field ids and option ids are resolved by name, never recorded."""

    def setUp(self):
        self.fields = json.loads(FIELD_LIST_JSON)["fields"]

    def test_type_chore_resolves_to_its_field_and_option(self):
        field_id, option_id = workitem.resolve_option(self.fields, "Type", "Chore")

        self.assertEqual(field_id, "PVTSSF_type")
        self.assertEqual(option_id, "opt_chore")

    def test_status_todo_resolves_to_its_field_and_option(self):
        field_id, option_id = workitem.resolve_option(self.fields, "Status", "Todo")

        self.assertEqual(field_id, "PVTSSF_status")
        self.assertEqual(option_id, "opt_todo")

    def test_an_unknown_field_names_the_field_in_the_refusal(self):
        with self.assertRaises(workitem.WorkItemError) as caught:
            workitem.resolve_option(self.fields, "Priority", "High")

        self.assertIn("Priority", str(caught.exception))

    def test_an_unknown_option_names_both_the_field_and_the_option(self):
        with self.assertRaises(workitem.WorkItemError) as caught:
            workitem.resolve_option(self.fields, "Type", "Sonnet")

        self.assertIn("Type", str(caught.exception))
        self.assertIn("Sonnet", str(caught.exception))

    def test_a_field_with_no_options_is_refused_rather_than_crashing(self):
        with self.assertRaises(workitem.WorkItemError):
            workitem.resolve_option(self.fields, "Title", "Anything")


class TestIssueNumber(unittest.TestCase):
    """`gh issue create` answers with a URL; AC7 shows a number."""

    def test_the_number_is_read_off_the_url_gh_prints(self):
        self.assertEqual(
            workitem.issue_number(
                "https://github.com/MatthieuGagne/gmb-nuke-raider/issues/614"
            ),
            614,
        )

    def test_trailing_whitespace_and_noise_do_not_defeat_it(self):
        self.assertEqual(
            workitem.issue_number(
                "Creating issue\nhttps://github.com/MatthieuGagne/gmb-nuke-raider/issues/7\n"
            ),
            7,
        )

    def test_output_with_no_url_is_refused(self):
        with self.assertRaises(workitem.WorkItemError):
            workitem.issue_number("something went sideways")


class TestRunCapture(unittest.TestCase):
    """The seam itself: a real subprocess, since a mock would prove nothing
    about the shape the rest of the module depends on.
    """

    def test_stdout_exit_code_and_argv_come_back(self):
        result = workitem.run_capture([sys.executable, "-c", "print('hi')"])

        self.assertTrue(result.ok)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout.strip(), "hi")

    def test_a_failing_command_is_not_ok_and_keeps_its_stderr(self):
        result = workitem.run_capture(
            [sys.executable, "-c", "import sys; sys.stderr.write('nope'); sys.exit(3)"]
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.exit_code, 3)
        self.assertIn("nope", result.stderr)

    def test_a_command_that_cannot_start_is_a_result_not_an_exception(self):
        # A button press must not raise out of a worker thread.
        result = workitem.run_capture(["no-such-tool-anywhere-at-all"])

        self.assertFalse(result.ok)
        self.assertNotEqual(result.exit_code, 0)
