"""Panel coverage for the work-item section — MatthieuGagne/nuke-raiders-garage#5.

Imports PySide6, so this file must never be reachable by
`python -m unittest discover -s tests` -- tests/garage/ has no __init__.py,
so default discovery never descends into it. Run via `make test-garage`.

Every `gh` call goes through the runner the panel is constructed with, so
nothing here reaches GitHub. `shutil.which` is stubbed around the one call
that consults it, so the suite behaves the same on a machine that has `gh`
installed and on one that does not.
"""
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tools.garage import theme
from tools.garage.core import project, workitem
from tools.garage.panels import worktrees as worktrees_panel
from tools.garage.panels.worktrees import WorktreesPanel

_app = QApplication.instance() or QApplication([])

GAME_REPO_REMOTE_URL = "https://github.com/MatthieuGagne/gmb-nuke-raider.git"
ISSUE_URL = "https://github.com/MatthieuGagne/gmb-nuke-raider/issues/614"

CONFIG_H = "#define PLAYER_SPEED 4\n#define MAX_NPCS 8\n"

FIELDS = {
    "fields": [
        {
            "id": "PVTSSF_status",
            "name": "Status",
            "options": [{"id": "opt_todo", "name": "Todo"}],
        },
        {
            "id": "PVTSSF_type",
            "name": "Type",
            "options": [{"id": "opt_chore", "name": "Chore"}],
        },
    ]
}


def scripted_runner(create_stdout=ISSUE_URL, create_code=0):
    """A `Runner` that answers from a script. Records its calls."""
    calls = []

    def run(argv, cwd=None):
        argv = list(argv)
        calls.append(argv)
        if "field-list" in argv:
            return workitem.CommandResult(tuple(argv), 0, json.dumps(FIELDS), "")
        if "create" in argv:
            return workitem.CommandResult(
                tuple(argv), create_code, create_stdout, "gh: Not Found (HTTP 404)"
            )
        if "item-add" in argv:
            return workitem.CommandResult(
                tuple(argv), 0, json.dumps({"id": "PVTI_x"}), ""
            )
        return workitem.CommandResult(tuple(argv), 0, "", "")

    run.calls = calls
    return run


def stalling_runner(delay_s=2.0):
    """A scripted runner whose first call takes long enough that a join
    with a shortened timeout is guaranteed to expire on it.

    `entered` is set the instant the worker thread is inside the call, so a
    test can be sure the thread is really running before it joins -- a
    `quit()` that arrives before `exec()` starts makes the join succeed at
    once, which would test nothing.
    """
    scripted = scripted_runner()
    entered = threading.Event()

    def run(argv, cwd=None):
        if "field-list" in list(argv):
            entered.set()
            time.sleep(delay_s)
        return scripted(argv, cwd)

    run.calls = scripted.calls
    run.entered = entered
    return run


def partial_runner():
    """A runner that files the issue, puts it on the board, and then has
    GitHub refuse the first `item-edit`.

    That is exactly the partial state R8 is written about: a real issue
    exists, on the board, with `Type` and `Status` unset. Every test that
    needs one drives the panel through this rather than reaching into
    `_last_item`, because the guard being tested is the panel's own.
    """
    scripted = scripted_runner()

    def run(argv, cwd=None):
        argv = list(argv)
        if "item-edit" in argv:
            scripted.calls.append(argv)
            return workitem.CommandResult(
                tuple(argv), 1, "", "gh: could not resolve field (HTTP 422)"
            )
        return scripted(argv, cwd)

    run.calls = scripted.calls
    return run


def stalling_resume_runner(delay_s=2.0):
    """`partial_runner`, plus a resume that stalls.

    The resume path's first call is `gh project item-list`, so sleeping
    there holds a `finish_board_entry` in flight for as long as a test
    needs to try a second one. `entered` is set the instant the worker is
    inside it, so the test never races the thread's start.
    """
    base = partial_runner()
    entered = threading.Event()

    def run(argv, cwd=None):
        if "item-list" in list(argv):
            entered.set()
            time.sleep(delay_s)
        return base(argv, cwd)

    run.calls = base.calls
    run.entered = entered
    return run


def exploding_runner(message="the runner blew up"):
    """A runner that raises rather than answering.

    Nothing in `workitem` is written to raise, which is precisely why this
    is worth a test: the guarantee that the panel recovers cannot come
    from the code that is supposed never to need it.
    """
    calls = []

    def run(argv, cwd=None):
        calls.append(list(argv))
        raise RuntimeError(message)

    run.calls = calls
    return run


def _run_git(args, cwd):
    return subprocess.run(
        ["git"] + args, cwd=str(cwd), check=True, capture_output=True, text=True
    )


def make_worktree(root: Path) -> Path:
    repo = root / "game"
    repo.mkdir(parents=True, exist_ok=True)
    _run_git(["init", "-b", "master"], repo)
    _run_git(["config", "user.email", "t@example.com"], repo)
    _run_git(["config", "user.name", "T"], repo)
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "config.h").write_text(CONFIG_H, encoding="utf-8")
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


class WorkItemPanelTestCase(unittest.TestCase):
    """Not gated on a bound game repository: the fixture builds its own git
    repository and every `gh` call is scripted, so this runs in CI.
    """

    def setUp(self):
        theme.apply(_app)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.repo = make_worktree(self.root)
        self.binding = bind_over(self.root, self.repo)
        self.runner = scripted_runner()
        self.panel = WorktreesPanel(self.binding, None, runner=self.runner)

    def tearDown(self):
        self.panel.stop_and_wait()
        self.panel.deleteLater()
        self._tmp.cleanup()

    def rebuild_panel(self, runner):
        """Replace the fixture's panel with one on a different runner,
        tearing the old one down the way `tearDown` would.
        """
        self.panel.stop_and_wait()
        self.panel.deleteLater()
        self.runner = runner
        self.panel = WorktreesPanel(self.binding, None, runner=runner)
        return self.panel

    def dirty(self):
        (self.repo / "src" / "config.h").write_text(
            CONFIG_H.replace("PLAYER_SPEED 4", "PLAYER_SPEED 6"), encoding="utf-8"
        )
        self.panel.refresh_work_item()

    def start_filing(self):
        """`file_work_item`, with `gh` on PATH as far as the panel can see.

        The panel refuses before it starts anything when `shutil.which`
        answers None, so the stub is what makes this test say the same
        thing on a machine with `gh` installed and on one without.
        """
        with mock.patch.object(worktrees_panel.shutil, "which", return_value="gh"):
            return self.panel.file_work_item()

    def file_and_wait(self, title="tune speed"):
        self.dirty()
        self.panel.title_field.setText(title)
        self.start_filing()
        self.wait()

    def wait(self, timeout_ms=30000):
        waited = 0
        while waited < timeout_ms and self.panel.is_filing():
            QTest.qWait(20)
            waited += 20
        QApplication.processEvents()
        self.assertFalse(self.panel.is_filing(), "the filing never ended")


class TestVisibility(WorkItemPanelTestCase):
    """AC1: the action is absent until there is something to file about.

    The panel is shown here, and only here. `work_item_visible()` answers
    from `isVisible()`, which is False for every child of a widget that
    was never shown -- so on a hidden panel the "revealed" assertion would
    pass for the wrong reason and the "hidden" one would prove nothing.
    Showing the panel is what makes both answers mean what they say, and
    it is the state the panel is actually in inside the dialog.
    """

    def setUp(self):
        super().setUp()
        self.panel.show()
        self.addCleanup(self.panel.hide)

    def test_a_clean_worktree_hides_the_section(self):
        self.assertFalse(self.panel.work_item_visible())

    def test_a_changed_define_reveals_it(self):
        self.dirty()

        self.assertTrue(self.panel.work_item_visible())


class TestNoAutomaticFiling(WorkItemPanelTestCase):
    """AC2, AC3: creating a worktree and committing file nothing."""

    def test_building_the_panel_calls_no_gh(self):
        self.assertEqual(self.runner.calls, [])

    def test_creating_a_worktree_calls_no_gh(self):
        self.panel.create_worktree("tune-speed")

        self.assertEqual(self.runner.calls, [])


class TestFiling(WorkItemPanelTestCase):
    """AC4, AC7, AC8."""

    def test_the_issue_number_is_shown(self):
        self.file_and_wait()

        self.assertIn("614", self.panel.work_item_result_text())

    def test_closes_n_goes_to_the_clipboard(self):
        self.file_and_wait()

        self.assertEqual(self.panel.copied_text(), "Closes #614")

    def test_the_title_reaches_gh_with_the_chore_prefix(self):
        self.file_and_wait()

        create = next(c for c in self.runner.calls if "create" in c)
        self.assertEqual(create[create.index("--title") + 1], "chore: tune speed")


class TestFailureIsShown(WorkItemPanelTestCase):
    """AC10: GitHub's message, in the window."""

    def setUp(self):
        super().setUp()
        self.rebuild_panel(scripted_runner(create_stdout="", create_code=1))

    def test_githubs_own_message_appears(self):
        self.file_and_wait()

        self.assertIn("404", self.panel.work_item_result_text())

    def test_no_issue_number_is_claimed(self):
        self.file_and_wait()

        self.assertIsNone(self.panel.last_work_item())


class TestAnUnexpectedErrorIsStillReported(WorkItemPanelTestCase):
    """R8: a failure is reported, whatever kind of failure it is.

    `_FileWorker.run` is invoked from C++ on a worker thread, so an
    exception escaping it does not surface as a traceback anybody reads --
    it surfaces as a `done` signal that never fires, which leaves the
    button disabled and the label saying "Filing…" until Garage is
    restarted. Silence is the one outcome R8 forbids.
    """

    def setUp(self):
        super().setUp()
        self.rebuild_panel(exploding_runner("gh vanished mid-call"))

    def test_the_panel_stops_filing_rather_than_hanging(self):
        self.file_and_wait()

        self.assertFalse(self.panel.is_filing())

    def test_the_button_comes_back(self):
        self.file_and_wait()

        self.assertTrue(self.panel.file_button.isEnabled())

    def test_the_error_is_shown_instead_of_filing(self):
        self.file_and_wait()

        text = self.panel.work_item_result_text()
        self.assertNotIn("Filing…", text)
        self.assertIn("gh vanished mid-call", text)

    def test_no_issue_number_is_claimed(self):
        self.file_and_wait()

        self.assertIsNone(self.panel.last_work_item())


class TestPartialFilingBlocksTheNextOne(WorkItemPanelTestCase):
    """R8: an issue is never left on the board with `Type` or `Status`
    unset without the user being told.

    Pressing the same button again is the natural gesture after a failure,
    and it is the one that would break this: a second filing overwrites
    the panel's handle on the first, so the issue already on the board
    becomes unreachable from Garage with nothing further said.
    """

    def setUp(self):
        super().setUp()
        self.rebuild_panel(partial_runner())
        self.file_and_wait()
        self.assertIsNotNone(self.panel.last_work_item(), "no partial to guard")

    def creates(self):
        return [c for c in self.runner.calls if "create" in c]

    def test_filing_again_is_refused(self):
        refusal = self.start_filing()

        self.assertIsNotNone(refusal)
        self.assertFalse(self.panel.is_filing())

    def test_the_refusal_names_the_issue_still_on_the_board(self):
        refusal = self.start_filing()

        self.assertIn("614", refusal)
        self.assertIn("614", self.panel.work_item_result_text())

    def test_no_second_issue_is_created(self):
        self.start_filing()

        self.assertEqual(len(self.creates()), 1)

    def test_the_finish_button_and_the_way_out_are_both_offered(self):
        # Shown for the reason `TestVisibility` gives: `isVisible()` is
        # False for every child of a widget that was never shown, so on a
        # hidden panel this would fail whatever the buttons were told.
        self.panel.show()
        self.addCleanup(self.panel.hide)

        self.assertTrue(self.panel.finish_button.isVisible())
        self.assertTrue(self.panel.dismiss_button.isVisible())

    def test_dismissing_touches_no_issue(self):
        before = len(self.runner.calls)

        self.panel.dismiss_partial_work_item()

        # R9: Garage does not close or edit issues. Leaving one alone has
        # to mean leaving it alone -- no `gh` call at all.
        self.assertEqual(len(self.runner.calls), before)
        self.assertIsNone(self.panel.last_work_item())

    def test_dismissing_releases_the_guard(self):
        self.panel.dismiss_partial_work_item()

        self.assertIsNone(self.start_filing())
        self.wait()
        self.assertEqual(len(self.creates()), 2)


class TestFinishingIsGuardedWhileFiling(WorkItemPanelTestCase):
    """#8, through the entry point that had no guard of its own.

    `_start` overwrites the panel's only reference to the running QThread,
    and dropping that reference while the thread is a live Qt child is a
    qFatal and a Windows fail-fast. `file_work_item` has always refused a
    second start; `finish_board_entry` reaches the same `_start` and is
    the door that was left open.
    """

    def setUp(self):
        super().setUp()
        self.rebuild_panel(stalling_resume_runner())
        self.file_and_wait()
        self.assertIsNotNone(self.panel.last_work_item(), "no partial to resume")

    def test_a_second_finish_while_one_is_in_flight_is_refused(self):
        self.assertIsNone(self.panel.finish_board_entry())
        waited = 0
        while waited < 10000 and not self.runner.entered.is_set():
            QTest.qWait(20)
            waited += 20
        self.assertTrue(self.runner.entered.is_set(), "the resume never started")

        refusal = self.panel.finish_board_entry()

        self.assertIsNotNone(refusal)
        self.assertIn("already being filed", refusal)
        self.wait()


class TestTheFilingThreadIsReleased(WorkItemPanelTestCase):
    """Signature B of #8, on this panel: `stop_and_wait` is safe in every
    order it can be reached, and nothing is left abandoned when the join
    succeeds -- which is every ordinary case.
    """

    def test_stopping_without_ever_filing_is_safe(self):
        self.panel.stop_and_wait()

        self.assertFalse(self.panel.is_filing())
        self.assertEqual(self.panel.abandoned_thread_count(), 0)

    def test_stopping_after_a_completed_filing_is_safe(self):
        self.file_and_wait()

        self.panel.stop_and_wait()

        self.assertFalse(self.panel.is_filing())
        self.assertEqual(self.panel.abandoned_thread_count(), 0)

    def test_a_completed_filing_leaves_nothing_abandoned(self):
        self.file_and_wait()

        # `_on_filed` releases the thread itself, so the panel is already
        # clear before the window ever closes.
        self.assertEqual(self.panel.abandoned_thread_count(), 0)

    def test_a_thread_that_outlives_its_join_is_held_not_destroyed(self):
        """Qt does not report a destroyed running QThread as an error: it
        is a qFatal, qFatal calls abort(), and on Windows abort() is a
        fail-fast -- the process goes with 0xC0000409, no message and no
        traceback. The join is shortened here so the worker reliably
        outlives it, but the branch is reachable without any such help:
        one filing makes up to five `gh` calls at
        `workitem.COMMAND_TIMEOUT_S` each, a hundred seconds against a
        thirty-second join, so closing the window on a filing stalled by a
        dropped network expires the wait in real use. That constant only
        guarantees the abandoned thread ends soon afterwards rather than
        never.
        """
        panel = self.rebuild_panel(stalling_runner())
        self.dirty()
        panel.title_field.setText("tune speed")

        self.start_filing()
        waited = 0
        while waited < 10000 and not self.runner.entered.is_set():
            QTest.qWait(20)
            waited += 20
        self.assertTrue(self.runner.entered.is_set(), "the worker never started")

        with mock.patch.object(worktrees_panel, "STOP_TIMEOUT_MS", 50):
            panel.stop_and_wait()

        # Still running, and therefore still held rather than deleted.
        self.assertEqual(panel.abandoned_thread_count(), 1)

        # And released once it really has finished, so nothing accumulates.
        waited = 0
        while waited < 30000 and panel.abandoned_thread_count():
            QTest.qWait(20)
            waited += 20
        self.assertEqual(panel.abandoned_thread_count(), 0)


class TestUnbound(unittest.TestCase):
    """The CI case: no game repository, so no section and no crash."""

    def setUp(self):
        theme.apply(_app)
        self.panel = WorktreesPanel(
            None, project.BindingError("game_repo", "nothing is bound")
        )
        # Shown for the same reason as in `TestVisibility`: on a hidden
        # panel `isVisible()` is False whatever the section was told.
        self.panel.show()

    def tearDown(self):
        self.panel.hide()
        self.panel.stop_and_wait()
        self.panel.deleteLater()

    def test_the_section_is_hidden(self):
        self.assertFalse(self.panel.work_item_visible())


if __name__ == "__main__":
    unittest.main()
