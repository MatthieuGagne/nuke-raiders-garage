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

    def test_a_worktree_with_no_config_h_at_all_yields_no_changes_rather_than_raising(self):
        # `config_io.read` raises a bare FileNotFoundError for a repository
        # that has never carried the file — the tuner's own fixtures build
        # one on purpose to prove nothing here crashes on it either.
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            repo = root / "game"
            repo.mkdir(parents=True, exist_ok=True)
            _run_git(["init", "-b", "master"], repo)
            _run_git(["config", "user.email", "test@example.com"], repo)
            _run_git(["config", "user.name", "Test"], repo)
            (repo / "README.md").write_text("no config.h here\n", encoding="utf-8")
            _run_git(["add", "."], repo)
            _run_git(["commit", "-m", "init"], repo)
            _run_git(["remote", "add", "origin", GAME_REPO_REMOTE_URL], repo)
            binding = bind_over(root, repo)

            self.assertEqual(workitem.changed_defines(binding), [])

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

    def test_a_command_that_hangs_is_stopped_and_reported_as_a_result(self):
        # A stalled `gh` -- a dropped VPN, a DNS hang, a prompt with no
        # TTY -- used to mean a worker thread that never finished, which
        # is what left a live QThread for Qt to destroy at window close
        # (#8). The timeout is passed explicitly so the suite does not
        # wait out the production value.
        result = workitem.run_capture(
            [sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.exit_code, workitem.EXIT_TIMED_OUT)
        self.assertIn("0.5 seconds", result.stderr)
        self.assertIn(result.stderr.strip(), result.message)

    def test_the_default_timeout_is_well_inside_the_panels_join(self):
        # The panel waits 30 s for its filing thread at window close; a
        # per-call timeout at or above that would make the wait expire
        # legitimately, which is the case the abandon path exists for.
        self.assertLess(workitem.COMMAND_TIMEOUT_S, 30)
        self.assertGreater(workitem.COMMAND_TIMEOUT_S, 0)


ISSUE_URL = "https://github.com/MatthieuGagne/gmb-nuke-raider/issues/614"
ITEM_ADD_JSON = json.dumps({"id": "PVTI_item614", "title": "chore: tune speed"})


class FakeRunner:
    """A `Runner` that answers from a script rather than from GitHub.

    Keyed on the first two argv words (`gh issue`, `gh project`) plus the
    subcommand, because that is the granularity the sequence branches on.
    Records every call so a test can assert what was and was not run — R9
    is a requirement about calls that must not happen.
    """

    def __init__(self, **overrides):
        self.calls = []
        self.responses = {
            "field-list": CommandOK(FIELD_LIST_JSON),
            "create": CommandOK(ISSUE_URL + "\n"),
            "item-add": CommandOK(ITEM_ADD_JSON),
            "item-edit": CommandOK(""),
        }
        self.responses.update(overrides)

    def __call__(self, argv, cwd=None):
        argv = list(argv)
        self.calls.append(argv)
        for key, response in self.responses.items():
            if key in argv:
                return workitem.CommandResult(
                    argv=tuple(argv),
                    exit_code=response.exit_code,
                    stdout=response.stdout,
                    stderr=response.stderr,
                )
        raise AssertionError(f"the fake runner has no answer for {argv}")

    def ran(self, needle) -> bool:
        return any(needle in call for call in self.calls)

    def edited_fields(self):
        """The (field-id, option-id) pairs the sequence actually set."""
        pairs = []
        for call in self.calls:
            if "item-edit" not in call:
                continue
            pairs.append(
                (
                    call[call.index("--field-id") + 1],
                    call[call.index("--single-select-option-id") + 1],
                )
            )
        return pairs


class CommandOK:
    def __init__(self, stdout="", stderr="", exit_code=0):
        self.stdout, self.stderr, self.exit_code = stdout, stderr, exit_code


def CommandFail(stderr, exit_code=1):
    return CommandOK(stdout="", stderr=stderr, exit_code=exit_code)


class WorkItemSequenceTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = tmp_root(self._tmp.name)
        self.repo = make_game_repo(self.root / "game")
        self.binding = bind_over(self.root, self.repo)

    def tearDown(self):
        self._tmp.cleanup()

    def file_it(self, runner, **kwargs):
        return workitem.file_work_item(
            self.binding,
            "tune speed",
            "The car turns too late.",
            changes=[workitem.ChangedDefine("PLAYER_SPEED", "4", "6")],
            commits=[],
            run=runner,
            **kwargs,
        )


class TestHappyPath(WorkItemSequenceTestCase):
    """AC6, AC7: the issue lands on the board, typed and statused."""

    def test_the_issue_number_comes_back(self):
        result = self.file_it(FakeRunner())

        self.assertIsInstance(result, workitem.WorkItem)
        self.assertEqual(result.number, 614)
        self.assertTrue(result.complete)

    def test_both_fields_are_set_from_the_resolved_ids(self):
        runner = FakeRunner()

        self.file_it(runner)

        self.assertEqual(
            sorted(runner.edited_fields()),
            sorted([("PVTSSF_type", "opt_chore"), ("PVTSSF_status", "opt_todo")]),
        )

    def test_the_fields_are_resolved_before_anything_is_created(self):
        # R8: a name that cannot be resolved must fail while nothing exists.
        runner = FakeRunner()

        self.file_it(runner)

        first = runner.calls[0]
        self.assertIn("field-list", first)

    def test_the_title_is_prefixed_on_the_way_to_gh(self):
        runner = FakeRunner()

        self.file_it(runner)

        create = next(c for c in runner.calls if "create" in c)
        self.assertEqual(create[create.index("--title") + 1], "chore: tune speed")

    def test_the_body_travels_as_a_file_that_does_not_outlive_the_call(self):
        runner = FakeRunner()

        self.file_it(runner)

        create = next(c for c in runner.calls if "create" in c)
        body_path = Path(create[create.index("--body-file") + 1])
        self.assertFalse(body_path.exists(), "the body file was left behind")

    def test_the_issue_is_filed_against_the_game_repository(self):
        runner = FakeRunner()

        self.file_it(runner)

        create = next(c for c in runner.calls if "create" in c)
        self.assertEqual(
            create[create.index("--repo") + 1], "MatthieuGagne/gmb-nuke-raider"
        )

    def test_nothing_pushes_closes_or_opens_a_pull_request(self):
        # R9/AC11, asserted rather than assumed.
        runner = FakeRunner()

        self.file_it(runner)

        for banned in ("push", "close", "pr", "delete", "edit"):
            self.assertFalse(
                runner.ran(banned), f"the sequence ran a `{banned}` subcommand"
            )


class TestFailures(WorkItemSequenceTestCase):
    """AC10: GitHub's own message, and never a half-typed board entry left
    without anyone being told.
    """

    def test_an_unresolvable_option_fails_before_the_issue_is_created(self):
        runner = FakeRunner(**{"field-list": CommandOK(json.dumps({"fields": []}))})

        result = self.file_it(runner)

        self.assertIsInstance(result, workitem.WorkItemFailure)
        self.assertEqual(result.step, workitem.STEP_FIELDS)
        self.assertIsNone(result.item)
        self.assertFalse(runner.ran("create"))

    def test_a_field_list_that_gh_refuses_reports_ghs_message(self):
        runner = FakeRunner(
            **{"field-list": CommandFail("gh: Your token has not been granted 'project'")}
        )

        result = self.file_it(runner)

        self.assertIsInstance(result, workitem.WorkItemFailure)
        self.assertIn("'project'", result.message)

    def test_a_refused_create_leaves_no_issue_and_says_why(self):
        runner = FakeRunner(**{"create": CommandFail("gh: Not Found (HTTP 404)")})

        result = self.file_it(runner)

        self.assertEqual(result.step, workitem.STEP_CREATE)
        self.assertIsNone(result.item)
        self.assertIn("404", result.message)

    def test_a_failed_board_add_names_the_issue_that_now_exists(self):
        runner = FakeRunner(**{"item-add": CommandFail("gh: could not add item")})

        result = self.file_it(runner)

        self.assertEqual(result.step, workitem.STEP_BOARD)
        self.assertIsNotNone(result.item)
        self.assertEqual(result.item.number, 614)
        self.assertFalse(result.item.on_board)
        self.assertFalse(result.item.complete)

    def test_a_failed_status_edit_reports_type_as_set_and_status_as_not(self):
        calls = {"n": 0}
        base = FakeRunner()

        def flaky(argv, cwd=None):
            argv = list(argv)
            if "item-edit" in argv:
                calls["n"] += 1
                if calls["n"] == 2:
                    return workitem.CommandResult(
                        argv=tuple(argv), exit_code=1, stdout="", stderr="gh: 502"
                    )
            return base(argv, cwd)

        result = self.file_it(flaky)

        self.assertEqual(result.step, workitem.STEP_STATUS)
        self.assertTrue(result.item.on_board)
        self.assertTrue(result.item.type_set)
        self.assertFalse(result.item.status_set)
        self.assertIn("502", result.message)

    def test_resuming_from_a_partial_result_files_no_second_issue(self):
        # The panel's "Finish the board entry" path (R9: nothing new is filed).
        runner = FakeRunner()
        partial = workitem.WorkItem(
            number=614, url=ISSUE_URL, on_board=False, type_set=False, status_set=False
        )

        result = self.file_it(runner, existing=partial)

        self.assertIsInstance(result, workitem.WorkItem)
        self.assertTrue(result.complete)
        self.assertFalse(runner.ran("create"))

    def test_resuming_with_no_binding_fails_rather_than_raising(self):
        # The `binding is None` guard on the resume path: `refuse_reason`
        # is skipped whenever `existing` is passed, so this branch is the
        # only thing standing between an unbound resume call and an
        # AssertionError crossing the worker thread.
        runner = FakeRunner()
        partial = workitem.WorkItem(
            number=614, url=ISSUE_URL, on_board=False, type_set=False, status_set=False
        )

        result = workitem.file_work_item(
            None,
            "tune speed",
            "",
            changes=[],
            commits=[],
            existing=partial,
            run=runner,
        )

        self.assertIsInstance(result, workitem.WorkItemFailure)
        self.assertEqual(runner.calls, [])

    def test_resuming_with_a_bare_prefix_title_returns_rather_than_raising(self):
        # The title is not recomputed on the resume path: `title_for` would
        # raise on "chore:" alone, and the resumed issue already has its
        # title, so nothing here should touch it at all.
        runner = FakeRunner()
        partial = workitem.WorkItem(
            number=614, url=ISSUE_URL, on_board=False, type_set=False, status_set=False
        )

        result = workitem.file_work_item(
            self.binding,
            "chore:",
            "The car turns too late.",
            changes=[workitem.ChangedDefine("PLAYER_SPEED", "4", "6")],
            commits=[],
            existing=partial,
            run=runner,
        )

        self.assertIsInstance(result, workitem.WorkItem)
        self.assertTrue(result.complete)


class TestRefusalsBeforeAnyCall(WorkItemSequenceTestCase):
    def test_an_empty_title_never_reaches_gh(self):
        runner = FakeRunner()

        result = workitem.file_work_item(
            self.binding, "   ", "", changes=[], commits=["abc1234 x"], run=runner
        )

        self.assertIsInstance(result, workitem.WorkItemFailure)
        self.assertEqual(runner.calls, [])

    def test_a_worktree_with_nothing_in_it_never_reaches_gh(self):
        runner = FakeRunner()

        result = workitem.file_work_item(
            self.binding, "tune speed", "", changes=[], commits=[], run=runner
        )

        self.assertIsInstance(result, workitem.WorkItemFailure)
        self.assertEqual(runner.calls, [])
