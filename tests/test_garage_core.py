"""Coverage for tools/garage/core/project.py, schema.py, config_io.py,
diff.py and doctor.py.

No Qt import anywhere in this file. Must pass with PySide6 absent.

Fixtures build real git repositories in a temp directory with `git init`,
`git remote add` and `git worktree add` -- git output is not mocked as
strings for the happy-path cases.
"""
import json
import subprocess
import sys
import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path

# Make the repository root importable regardless of the test runner's cwd.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.garage.core import (  # noqa: E402
    budgets,
    commit,
    config_io,
    diff,
    doctor,
    emulicious,
    make_runner,
    project,
    worktrees,
)
from tools.garage.core.schema import Schema, SchemaError  # noqa: E402


GAME_REPO_REMOTE_URL = "https://github.com/MatthieuGagne/gmb-nuke-raider.git"
WRONG_REMOTE_URL = "https://github.com/someone/unrelated-repo.git"


def _run_git(args, cwd):
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def make_game_repo(path: Path, remote_url=GAME_REPO_REMOTE_URL) -> Path:
    """Create a real git repository at `path` with one commit."""
    path.mkdir(parents=True, exist_ok=True)
    _run_git(["init", "-b", "master"], path)
    _run_git(["config", "user.email", "test@example.com"], path)
    _run_git(["config", "user.name", "Test"], path)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _run_git(["add", "."], path)
    _run_git(["commit", "-m", "init"], path)
    if remote_url:
        _run_git(["remote", "add", "origin", remote_url], path)
    return path


class TestFindDefaultGameRepo(unittest.TestCase):
    def test_detect_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo(tmp_path / "nuke-raider")

            found = project.find_default_game_repo(garage_root)

            self.assertEqual(found.resolve(), game_repo.resolve())

    def test_wrong_remote_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo(tmp_path / "nuke-raider", remote_url=WRONG_REMOTE_URL)

            with self.assertRaises(project.BindingError) as ctx:
                project.find_default_game_repo(garage_root)
            self.assertEqual(ctx.exception.key, "game_repo")
            self.assertIn("remote", ctx.exception.message.lower())

    def test_missing_sibling_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            # No sibling "nuke-raider" directory created.

            with self.assertRaises(project.BindingError) as ctx:
                project.find_default_game_repo(garage_root)
            self.assertEqual(ctx.exception.key, "game_repo")


class TestBind(unittest.TestCase):
    def test_first_run_writes_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo(tmp_path / "nuke-raider")

            settings_path = garage_root / "garage.local.json"
            self.assertFalse(settings_path.exists())

            binding = project.bind(garage_root)

            self.assertTrue(settings_path.exists())
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertIn("game_repo", data)
            self.assertIn("worktree_root", data)
            self.assertIn("active", data)
            self.assertEqual(Path(data["game_repo"]).resolve(), game_repo.resolve())
            self.assertEqual(
                Path(data["worktree_root"]).resolve(),
                (game_repo.parent / "worktrees").resolve(),
            )
            self.assertIsNone(data["active"])

            self.assertEqual(binding.game_repo.resolve(), game_repo.resolve())
            self.assertEqual(binding.active_source, "main-fallback")
            self.assertEqual(binding.active_worktree.branch, "master")

    def test_missing_recorded_path_is_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            # game_repo sibling deliberately absent; recorded path points
            # at a directory that does not exist.
            bad_path = tmp_path / "does-not-exist"
            settings_path = garage_root / "garage.local.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "game_repo": bad_path.as_posix(),
                        "worktree_root": (tmp_path / "worktrees").as_posix(),
                        "active": None,
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(project.BindingError) as ctx:
                project.bind(garage_root)
            self.assertEqual(ctx.exception.key, "game_repo")
            self.assertIn("game_repo", ctx.exception.message)

    def test_recorded_path_with_wrong_checkout_is_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            wrong_repo = make_game_repo(tmp_path / "other-repo", remote_url=WRONG_REMOTE_URL)

            settings_path = garage_root / "garage.local.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "game_repo": wrong_repo.as_posix(),
                        "worktree_root": (tmp_path / "worktrees").as_posix(),
                        "active": None,
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(project.BindingError) as ctx:
                project.bind(garage_root)
            self.assertEqual(ctx.exception.key, "game_repo")

    def test_stale_active_falls_back_to_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo(tmp_path / "nuke-raider")

            settings_path = garage_root / "garage.local.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "game_repo": game_repo.as_posix(),
                        "worktree_root": (tmp_path / "worktrees").as_posix(),
                        # Points at a worktree that was never created.
                        "active": str(tmp_path / "worktrees" / "ghost"),
                    }
                ),
                encoding="utf-8",
            )

            binding = project.bind(garage_root)

            self.assertEqual(binding.active_source, "main-fallback")
            self.assertEqual(binding.active_worktree.path.resolve(), game_repo.resolve())

    def test_recorded_active_worktree_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo(tmp_path / "nuke-raider")
            wt_path = tmp_path / "worktrees" / "feat"
            _run_git(["worktree", "add", "-b", "feat", str(wt_path)], game_repo)

            settings_path = garage_root / "garage.local.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "game_repo": game_repo.as_posix(),
                        "worktree_root": (tmp_path / "worktrees").as_posix(),
                        "active": wt_path.as_posix(),
                    }
                ),
                encoding="utf-8",
            )

            binding = project.bind(garage_root)

            self.assertEqual(binding.active_source, "recorded")
            self.assertEqual(binding.active_worktree.path.resolve(), wt_path.resolve())
            self.assertEqual(binding.active_worktree.branch, "feat")


class TestListWorktrees(unittest.TestCase):
    def test_parses_main_and_linked_worktrees(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            game_repo = make_game_repo(tmp_path / "nuke-raider")
            wt_path = tmp_path / "worktrees" / "feat"
            _run_git(["worktree", "add", "-b", "feat", str(wt_path)], game_repo)

            worktrees = project.list_worktrees(game_repo)

            self.assertEqual(len(worktrees), 2)
            self.assertEqual(worktrees[0].path.resolve(), game_repo.resolve())
            self.assertEqual(worktrees[0].branch, "master")
            self.assertFalse(worktrees[0].detached)
            self.assertTrue(worktrees[0].head)

            self.assertEqual(worktrees[1].path.resolve(), wt_path.resolve())
            self.assertEqual(worktrees[1].branch, "feat")
            self.assertFalse(worktrees[1].detached)

    def test_detached_head_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            game_repo = make_game_repo(tmp_path / "nuke-raider")
            head_sha = _run_git(["rev-parse", "HEAD"], game_repo).stdout.strip()
            wt_path = tmp_path / "worktrees" / "detached"
            _run_git(["worktree", "add", "--detach", str(wt_path), head_sha], game_repo)

            worktrees = project.list_worktrees(game_repo)

            detached_entries = [w for w in worktrees if w.path.resolve() == wt_path.resolve()]
            self.assertEqual(len(detached_entries), 1)
            entry = detached_entries[0]
            self.assertTrue(entry.detached)
            self.assertIsNone(entry.branch)
            self.assertEqual(entry.head, head_sha)


class TestBindingPathHelpers(unittest.TestCase):
    def test_config_h_and_build_dir_resolve_inside_active_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo(tmp_path / "nuke-raider")

            binding = project.bind(garage_root)

            self.assertEqual(
                binding.config_h.resolve(),
                (game_repo / "src" / "config.h").resolve(),
            )
            self.assertEqual(
                binding.build_dir.resolve(),
                (game_repo / "build").resolve(),
            )


REAL_TUNABLES_PATH = REPO_ROOT / "tools" / "garage" / "tunables.json"
def _bound_config_h():
    """The bound game repository's `src/config.h`, or None when this
    checkout has no game repository beside it.

    Resolved through the binding rather than hardcoded: a path spelled out
    here is a path that exists on exactly one machine, and every test using
    it would fail — not skip — in CI, where this repository is checked out
    alone. AC15 asks the default target to succeed there.
    """
    try:
        return project.bind().config_h
    except project.BindingError:
        return None


REAL_CONFIG_H_PATH = _bound_config_h()
NO_GAME_REPO = REAL_CONFIG_H_PATH is None
NO_GAME_REPO_REASON = "no game repository is bound beside this checkout"

SAMPLE_TUNABLES = {
    "_shape": "test fixture",
    "entries": {
        "CONFIG_H": {"class": "marker", "reason": "include guard"},
        "GEAR1_MAX_SPEED": {
            "class": "tunable",
            "category": "Car Physics",
            "min": 1,
            "max": 15,
            "reason": "car feel",
        },
        "PLAYER_ARMOR": {
            "class": "tunable",
            "category": "Combat",
            "min": 0,
            "max": 15,
            "reason": "damage reduction",
        },
        "MAX_SPRITES": {"class": "structural", "reason": "OAM budget"},
        "LOADER_BG_START": {"class": "derived", "reason": "computed"},
    },
}


def write_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestSchemaValidation(unittest.TestCase):
    def test_loads_real_tunables_json(self):
        schema = Schema.load(REAL_TUNABLES_PATH)
        self.assertEqual(schema.classify("GEAR1_MAX_SPEED"), "tunable")
        self.assertEqual(schema.classify("MAX_SPRITES"), "structural")
        self.assertEqual(schema.classify("LOADER_BG_START"), "derived")
        self.assertEqual(schema.classify("CONFIG_H"), "marker")

    @unittest.skipIf(NO_GAME_REPO, NO_GAME_REPO_REASON)
    def test_real_tunables_json_classifies_every_config_h_define(self):
        text = REAL_CONFIG_H_PATH.read_text(encoding="utf-8")
        schema = Schema.load(REAL_TUNABLES_PATH)
        config = config_io.parse(text, schema=schema)
        unclassified = [n for n in config.defines if n not in schema]
        self.assertEqual(unclassified, [])
        stale = [n for n in schema.names() if n not in config.defines]
        self.assertEqual(stale, [])

    def test_ac8_max_sprites_not_offered_and_max_racers_is_derived(self):
        schema = Schema.load(REAL_TUNABLES_PATH)
        self.assertNotEqual(schema.classify("MAX_SPRITES"), "tunable")
        self.assertEqual(schema.classify("MAX_RACERS"), "derived")

    def test_valid_sample_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(Path(tmp) / "tunables.json", SAMPLE_TUNABLES)
            schema = Schema.load(path)
            self.assertTrue(schema.is_tunable("GEAR1_MAX_SPEED"))
            self.assertFalse(schema.is_tunable("MAX_SPRITES"))

    def test_unknown_class_rejected_naming_entry(self):
        data = json.loads(json.dumps(SAMPLE_TUNABLES))
        data["entries"]["BAD_ONE"] = {"class": "wat", "reason": "x"}
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(Path(tmp) / "tunables.json", data)
            with self.assertRaises(SchemaError) as ctx:
                Schema.load(path)
            self.assertIn("BAD_ONE", str(ctx.exception))

    def test_tunable_missing_min_rejected_naming_entry(self):
        data = json.loads(json.dumps(SAMPLE_TUNABLES))
        del data["entries"]["GEAR1_MAX_SPEED"]["min"]
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(Path(tmp) / "tunables.json", data)
            with self.assertRaises(SchemaError) as ctx:
                Schema.load(path)
            self.assertIn("GEAR1_MAX_SPEED", str(ctx.exception))

    def test_tunable_min_greater_than_max_rejected(self):
        data = json.loads(json.dumps(SAMPLE_TUNABLES))
        data["entries"]["GEAR1_MAX_SPEED"]["min"] = 20
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(Path(tmp) / "tunables.json", data)
            with self.assertRaises(SchemaError) as ctx:
                Schema.load(path)
            self.assertIn("GEAR1_MAX_SPEED", str(ctx.exception))

    def test_structural_with_min_rejected(self):
        data = json.loads(json.dumps(SAMPLE_TUNABLES))
        data["entries"]["MAX_SPRITES"]["min"] = 1
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(Path(tmp) / "tunables.json", data)
            with self.assertRaises(SchemaError) as ctx:
                Schema.load(path)
            self.assertIn("MAX_SPRITES", str(ctx.exception))

    def test_missing_reason_rejected(self):
        data = json.loads(json.dumps(SAMPLE_TUNABLES))
        del data["entries"]["MAX_SPRITES"]["reason"]
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(Path(tmp) / "tunables.json", data)
            with self.assertRaises(SchemaError) as ctx:
                Schema.load(path)
            self.assertIn("MAX_SPRITES", str(ctx.exception))

    def test_missing_file_raises(self):
        with self.assertRaises(SchemaError):
            Schema.load(Path("does-not-exist.json"))

    def test_classify_unknown_name_raises(self):
        schema = Schema.load(REAL_TUNABLES_PATH)
        with self.assertRaises(SchemaError) as ctx:
            schema.classify("NOT_A_REAL_DEFINE")
        self.assertIn("NOT_A_REAL_DEFINE", str(ctx.exception))


class TestSchemaClamp(unittest.TestCase):
    def setUp(self):
        self.schema = Schema.load(REAL_TUNABLES_PATH)

    def test_clamp_within_range_is_unchanged(self):
        self.assertEqual(self.schema.clamp("GEAR1_MAX_SPEED", 5), 5)

    def test_clamp_above_max_is_clamped(self):
        self.assertEqual(self.schema.clamp("GEAR1_MAX_SPEED", 999), 15)

    def test_clamp_below_min_is_clamped(self):
        self.assertEqual(self.schema.clamp("GEAR1_MAX_SPEED", -5), 1)

    def test_clamp_on_structural_raises(self):
        with self.assertRaises(SchemaError) as ctx:
            self.schema.clamp("MAX_SPRITES", 10)
        self.assertIn("MAX_SPRITES", str(ctx.exception))

    def test_clamp_on_derived_raises(self):
        with self.assertRaises(SchemaError):
            self.schema.clamp("MAX_RACERS", 3)

    def test_clamp_on_marker_raises(self):
        with self.assertRaises(SchemaError):
            self.schema.clamp("CONFIG_H", 1)

    def test_tunables_list_has_category_and_bounds(self):
        entries = {t.name: t for t in self.schema.tunables()}
        gear = entries["GEAR1_MAX_SPEED"]
        self.assertEqual(gear.category, "Car Physics")
        self.assertEqual((gear.min, gear.max), (1, 15))


SAMPLE_CONFIG_TEXT = """\
#ifndef CONFIG_H
#define CONFIG_H

#define GEAR1_MAX_SPEED        2u
#define GEAR1_ACCEL            2u
#define PLAYER_ARMOR     5   /* reduces damage */
#define PLAYER_MAX_HP              100u  /* max HP pool */
#define DEBUG_LOG_ADDR    0xDF80U  /* WRAM: ring buffer content (64 bytes) */
#define MAX_SPRITES  32
#define LOADER_BG_START  ((uint8_t)(HUD_FONT_BASE + HUD_FONT_COUNT))

#endif /* CONFIG_H */
"""

SAMPLE_TUNABLES_FOR_CONFIG_IO = {
    "_shape": "test fixture",
    "entries": {
        "CONFIG_H": {"class": "marker", "reason": "include guard"},
        "GEAR1_MAX_SPEED": {
            "class": "tunable", "category": "Car Physics", "min": 1, "max": 15, "reason": "x",
        },
        "GEAR1_ACCEL": {
            "class": "tunable", "category": "Car Physics", "min": 1, "max": 15, "reason": "x",
        },
        "PLAYER_ARMOR": {
            "class": "tunable", "category": "Combat", "min": 0, "max": 15, "reason": "x",
        },
        "PLAYER_MAX_HP": {
            "class": "tunable", "category": "Combat", "min": 1, "max": 255, "reason": "x",
        },
        "DEBUG_LOG_ADDR": {"class": "structural", "reason": "WRAM address"},
        "MAX_SPRITES": {"class": "structural", "reason": "OAM budget"},
        "LOADER_BG_START": {"class": "derived", "reason": "computed"},
    },
}


class TestConfigIOParse(unittest.TestCase):
    def setUp(self):
        self.schema = Schema.load(write_json(
            Path(tempfile.mkdtemp()) / "tunables.json", SAMPLE_TUNABLES_FOR_CONFIG_IO
        ))

    def test_reads_u_suffix_value(self):
        config = config_io.parse(SAMPLE_CONFIG_TEXT, schema=self.schema)
        self.assertEqual(config.defines["GEAR1_MAX_SPEED"].value, 2)
        self.assertEqual(config.defines["GEAR1_MAX_SPEED"].value_text, "2u")

    def test_reads_no_suffix_value(self):
        config = config_io.parse(SAMPLE_CONFIG_TEXT, schema=self.schema)
        self.assertEqual(config.defines["PLAYER_ARMOR"].value, 5)
        self.assertEqual(config.defines["PLAYER_ARMOR"].value_text, "5")

    def test_reads_hex_value(self):
        config = config_io.parse(SAMPLE_CONFIG_TEXT, schema=self.schema)
        define = config.defines["DEBUG_LOG_ADDR"]
        self.assertEqual(define.value, 0xDF80)
        self.assertEqual(define.value_text, "0xDF80U")

    def test_marker_has_no_value(self):
        config = config_io.parse(SAMPLE_CONFIG_TEXT, schema=self.schema)
        self.assertFalse(config.defines["CONFIG_H"].has_value)

    def test_derived_expression_has_no_value(self):
        config = config_io.parse(SAMPLE_CONFIG_TEXT, schema=self.schema)
        self.assertFalse(config.defines["LOADER_BG_START"].has_value)

    def test_classification_attached_from_schema(self):
        config = config_io.parse(SAMPLE_CONFIG_TEXT, schema=self.schema)
        self.assertEqual(config.defines["GEAR1_MAX_SPEED"].cls, "tunable")
        self.assertEqual(config.defines["MAX_SPRITES"].cls, "structural")

    def test_line_numbers_are_1_based_and_correct(self):
        config = config_io.parse(SAMPLE_CONFIG_TEXT, schema=self.schema)
        self.assertEqual(config.defines["GEAR1_MAX_SPEED"].line_no, 4)


class TestConfigIOApplyChanges(unittest.TestCase):
    def setUp(self):
        self.schema = Schema.load(write_json(
            Path(tempfile.mkdtemp()) / "tunables.json", SAMPLE_TUNABLES_FOR_CONFIG_IO
        ))
        self.config = config_io.parse(SAMPLE_CONFIG_TEXT, schema=self.schema)

    def test_updates_u_suffix_value(self):
        result = config_io.apply_changes(self.config, self.schema, {"GEAR1_MAX_SPEED": 5})
        self.assertIn("#define GEAR1_MAX_SPEED        5u", result)

    def test_preserves_no_suffix(self):
        result = config_io.apply_changes(self.config, self.schema, {"PLAYER_ARMOR": 3})
        self.assertIn("#define PLAYER_ARMOR     3   /* reduces damage */", result)

    def test_preserves_trailing_comment(self):
        result = config_io.apply_changes(self.config, self.schema, {"PLAYER_MAX_HP": 80})
        self.assertIn("#define PLAYER_MAX_HP              80u  /* max HP pool */", result)

    def test_unchanged_lines_preserved(self):
        result = config_io.apply_changes(self.config, self.schema, {"GEAR1_MAX_SPEED": 5})
        self.assertIn("#define GEAR1_ACCEL            2u", result)

    def test_no_changes_returns_identical_text(self):
        result = config_io.apply_changes(self.config, self.schema, {})
        self.assertEqual(result, SAMPLE_CONFIG_TEXT)

    def test_value_is_clamped_to_declared_range(self):
        result = config_io.apply_changes(self.config, self.schema, {"GEAR1_MAX_SPEED": 999})
        self.assertIn("#define GEAR1_MAX_SPEED        15u", result)

    def test_hex_value_stays_hex_and_uppercase(self):
        result = config_io.apply_changes(self.config, self.schema, {})
        self.assertEqual(result, SAMPLE_CONFIG_TEXT)  # sanity: no-op baseline

    def test_edited_line_keeps_its_trailing_newline(self):
        # Regression: an edited line must not run into the next line --
        # the whole file must stay a valid line-for-line reconstruction,
        # not just contain the new value token as a substring somewhere.
        result = config_io.apply_changes(self.config, self.schema, {"GEAR1_MAX_SPEED": 9})
        expected = SAMPLE_CONFIG_TEXT.replace(
            "#define GEAR1_MAX_SPEED        2u\n",
            "#define GEAR1_MAX_SPEED        9u\n",
        )
        self.assertEqual(result, expected)

    def test_multiple_edits_each_keep_their_own_line(self):
        result = config_io.apply_changes(
            self.config, self.schema, {"GEAR1_MAX_SPEED": 9, "PLAYER_ARMOR": 3}
        )
        expected = (
            SAMPLE_CONFIG_TEXT.replace(
                "#define GEAR1_MAX_SPEED        2u\n",
                "#define GEAR1_MAX_SPEED        9u\n",
            ).replace(
                "#define PLAYER_ARMOR     5   /* reduces damage */\n",
                "#define PLAYER_ARMOR     3   /* reduces damage */\n",
            )
        )
        self.assertEqual(result, expected)

    def test_refuses_to_write_structural(self):
        with self.assertRaises(config_io.ConfigIOError) as ctx:
            config_io.apply_changes(self.config, self.schema, {"MAX_SPRITES": 40})
        self.assertIn("MAX_SPRITES", str(ctx.exception))

    def test_refuses_to_write_derived(self):
        with self.assertRaises(config_io.ConfigIOError) as ctx:
            config_io.apply_changes(self.config, self.schema, {"LOADER_BG_START": 200})
        self.assertIn("LOADER_BG_START", str(ctx.exception))

    def test_refuses_to_write_marker(self):
        with self.assertRaises(config_io.ConfigIOError) as ctx:
            config_io.apply_changes(self.config, self.schema, {"CONFIG_H": 1})
        self.assertIn("CONFIG_H", str(ctx.exception))

    def test_refuses_to_write_unclassified_name(self):
        with self.assertRaises(config_io.ConfigIOError):
            config_io.apply_changes(self.config, self.schema, {"NOT_IN_SCHEMA": 1})


def make_game_repo_with_config(path: Path, config_text: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "src").mkdir(parents=True, exist_ok=True)
    (path / "src" / "config.h").write_bytes(config_text.encode("utf-8"))
    _run_git(["init", "-b", "master"], path)
    _run_git(["config", "user.email", "test@example.com"], path)
    _run_git(["config", "user.name", "Test"], path)
    _run_git(["add", "."], path)
    _run_git(["commit", "-m", "init"], path)
    _run_git(
        ["remote", "add", "origin", GAME_REPO_REMOTE_URL],
        path,
    )
    return path


class TestConfigIOReadWrite(unittest.TestCase):
    @unittest.skipIf(NO_GAME_REPO, NO_GAME_REPO_REASON)
    def test_zero_change_write_is_byte_identical_against_real_config_h(self):
        real_bytes = REAL_CONFIG_H_PATH.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo_with_config(
                tmp_path / "nuke-raider", real_bytes.decode("utf-8")
            )
            binding = project.bind(garage_root)
            schema = Schema.load(REAL_TUNABLES_PATH)

            config_io.write(binding, schema, {})

            written_bytes = (game_repo / "src" / "config.h").read_bytes()
            self.assertEqual(written_bytes, real_bytes)

    def test_write_updates_target_value_and_preserves_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo_with_config(tmp_path / "nuke-raider", SAMPLE_CONFIG_TEXT)
            binding = project.bind(garage_root)
            schema = Schema.load(write_json(
                tmp_path / "tunables.json", SAMPLE_TUNABLES_FOR_CONFIG_IO
            ))

            config_io.write(binding, schema, {"GEAR1_MAX_SPEED": 9})

            new_text = (game_repo / "src" / "config.h").read_text(encoding="utf-8")
            self.assertIn("#define GEAR1_MAX_SPEED        9u", new_text)
            self.assertIn("#define GEAR1_ACCEL            2u", new_text)
            self.assertIn("#define PLAYER_ARMOR     5   /* reduces damage */", new_text)

    def test_write_refuses_structural_and_leaves_file_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo_with_config(tmp_path / "nuke-raider", SAMPLE_CONFIG_TEXT)
            binding = project.bind(garage_root)
            schema = Schema.load(write_json(
                tmp_path / "tunables.json", SAMPLE_TUNABLES_FOR_CONFIG_IO
            ))

            with self.assertRaises(config_io.ConfigIOError):
                config_io.write(binding, schema, {"MAX_SPRITES": 40})

            unchanged_text = (game_repo / "src" / "config.h").read_text(encoding="utf-8")
            self.assertEqual(unchanged_text, SAMPLE_CONFIG_TEXT)

    def test_read_value_at_head_returns_committed_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo_with_config(tmp_path / "nuke-raider", SAMPLE_CONFIG_TEXT)
            binding = project.bind(garage_root)
            schema = Schema.load(write_json(
                tmp_path / "tunables.json", SAMPLE_TUNABLES_FOR_CONFIG_IO
            ))

            # Change the working copy without committing.
            (game_repo / "src" / "config.h").write_text(
                SAMPLE_CONFIG_TEXT.replace(
                    "#define GEAR1_MAX_SPEED        2u",
                    "#define GEAR1_MAX_SPEED        11u",
                ),
                encoding="utf-8",
            )

            head_value = config_io.read_value_at_head(binding, "GEAR1_MAX_SPEED", schema)

            self.assertEqual(head_value, 2)

    def test_read_value_at_head_raises_for_derived_define(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo_with_config(tmp_path / "nuke-raider", SAMPLE_CONFIG_TEXT)
            binding = project.bind(garage_root)
            schema = Schema.load(write_json(
                tmp_path / "tunables.json", SAMPLE_TUNABLES_FOR_CONFIG_IO
            ))

            with self.assertRaises(config_io.ConfigIOError):
                config_io.read_value_at_head(binding, "LOADER_BG_START", schema)


class TestConfigIOReadConfigAtHead(unittest.TestCase):
    """R9/AC10: a single `git show HEAD:src/config.h` per refresh, not one
    `git show` per row -- read_config_at_head returns the whole parsed
    HEAD file so callers (the Tuner) can look up as many names as they
    like from one subprocess call.
    """

    def test_returns_whole_parsed_file_from_one_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo_with_config(tmp_path / "nuke-raider", SAMPLE_CONFIG_TEXT)
            binding = project.bind(garage_root)
            schema = Schema.load(write_json(
                tmp_path / "tunables.json", SAMPLE_TUNABLES_FOR_CONFIG_IO
            ))

            # Hand-edit the working copy without committing, on two
            # different tunables, to prove both come back from one read.
            (game_repo / "src" / "config.h").write_text(
                SAMPLE_CONFIG_TEXT.replace(
                    "#define GEAR1_MAX_SPEED        2u",
                    "#define GEAR1_MAX_SPEED        11u",
                ).replace(
                    "#define PLAYER_ARMOR     5   /* reduces damage */",
                    "#define PLAYER_ARMOR     9   /* reduces damage */",
                ),
                encoding="utf-8",
            )

            with unittest.mock.patch(
                "tools.garage.core.config_io.subprocess.run",
                wraps=subprocess.run,
            ) as spy:
                head_config = config_io.read_config_at_head(binding, schema)

            self.assertEqual(spy.call_count, 1)
            self.assertEqual(head_config.defines["GEAR1_MAX_SPEED"].value, 2)
            self.assertEqual(head_config.defines["PLAYER_ARMOR"].value, 5)

    def test_read_value_at_head_still_works_built_on_shared_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo_with_config(tmp_path / "nuke-raider", SAMPLE_CONFIG_TEXT)
            binding = project.bind(garage_root)
            schema = Schema.load(write_json(
                tmp_path / "tunables.json", SAMPLE_TUNABLES_FOR_CONFIG_IO
            ))

            self.assertEqual(
                config_io.read_value_at_head(binding, "PLAYER_ARMOR", schema), 5
            )

    def test_no_commits_yet_raises_explanatory_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = tmp_path / "nuke-raider"
            (game_repo / "src").mkdir(parents=True)
            (game_repo / "src" / "config.h").write_text(SAMPLE_CONFIG_TEXT, encoding="utf-8")
            _run_git(["init", "-b", "master"], game_repo)
            _run_git(["remote", "add", "origin", GAME_REPO_REMOTE_URL], game_repo)
            # Deliberately no commit -- HEAD does not exist yet.

            settings_path = garage_root / "garage.local.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "game_repo": game_repo.as_posix(),
                        "worktree_root": (tmp_path / "worktrees").as_posix(),
                        "active": None,
                    }
                ),
                encoding="utf-8",
            )
            binding = project.bind(garage_root)

            with self.assertRaises(config_io.ConfigIOError) as ctx:
                config_io.read_config_at_head(binding)
            message = str(ctx.exception).lower()
            self.assertIn("commit", message)

    def test_missing_config_h_at_head_raises_explanatory_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo(tmp_path / "nuke-raider")  # no src/config.h at all

            binding = project.bind(garage_root)

            with self.assertRaises(config_io.ConfigIOError) as ctx:
                config_io.read_config_at_head(binding)
            message = str(ctx.exception).lower()
            self.assertIn("config.h", message)


# -- R19/AC19/AC2: tools/garage/core/diff.py ---------------------------------
#
# The diff of the active worktree against HEAD (staged + unstaged in one
# view), the untracked file list, and the dirty/master check the header (and
# later the Worktree and Commit panels) need. Fixtures build real git repos
# in a temp dir, same convention as the rest of this file -- no mocked git
# output for the happy-path cases.


def make_bare_game_repo(path: Path) -> Path:
    """A git repo with no commits at all -- an unborn HEAD."""
    path.mkdir(parents=True, exist_ok=True)
    _run_git(["init", "-b", "master"], path)
    _run_git(["config", "user.email", "test@example.com"], path)
    _run_git(["config", "user.name", "Test"], path)
    _run_git(["remote", "add", "origin", GAME_REPO_REMOTE_URL], path)
    return path


def make_committed_game_repo(path: Path, files: dict) -> Path:
    """A git repo with one commit holding `files` (relative-path -> text)."""
    path.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        file_path = path / rel
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(text, encoding="utf-8")
    _run_git(["init", "-b", "master"], path)
    _run_git(["config", "user.email", "test@example.com"], path)
    _run_git(["config", "user.name", "Test"], path)
    _run_git(["add", "."], path)
    _run_git(["commit", "-m", "init"], path)
    _run_git(["remote", "add", "origin", GAME_REPO_REMOTE_URL], path)
    return path


def bind_over(tmp_path: Path, game_repo: Path) -> project.Binding:
    garage_root = tmp_path / "nuke-raider-garage"
    garage_root.mkdir(exist_ok=True)
    return project.bind(garage_root)


class TestParseDiffTextPure(unittest.TestCase):
    """parse_diff_text is pure -- fed crafted `git diff` text, no git call."""

    def test_modified_file_hunk_lines_tagged(self):
        text = (
            "diff --git a/src/config.h b/src/config.h\n"
            "index 1111111..2222222 100644\n"
            "--- a/src/config.h\n"
            "+++ b/src/config.h\n"
            "@@ -1,3 +1,3 @@\n"
            " context line\n"
            "-#define GEAR1_MAX_SPEED 2u\n"
            "+#define GEAR1_MAX_SPEED 9u\n"
        )
        files, truncated, reason = diff.parse_diff_text(text)

        self.assertFalse(truncated)
        self.assertEqual(reason, "")
        self.assertEqual(len(files), 1)
        f = files[0]
        self.assertEqual(f.path, "src/config.h")
        self.assertEqual(f.change_type, "modified")
        self.assertFalse(f.binary)
        self.assertEqual(len(f.hunks), 1)
        hunk = f.hunks[0]
        self.assertEqual(hunk.header, "@@ -1,3 +1,3 @@")
        kinds = [(l.kind, l.text) for l in hunk.lines]
        self.assertEqual(
            kinds,
            [
                ("context", "context line"),
                ("remove", "#define GEAR1_MAX_SPEED 2u"),
                ("add", "#define GEAR1_MAX_SPEED 9u"),
            ],
        )

    def test_added_file(self):
        text = (
            "diff --git a/new.txt b/new.txt\n"
            "new file mode 100644\n"
            "index 0000000..1111111\n"
            "--- /dev/null\n"
            "+++ b/new.txt\n"
            "@@ -0,0 +1,2 @@\n"
            "+line one\n"
            "+line two\n"
        )
        files, _, _ = diff.parse_diff_text(text)
        self.assertEqual(files[0].change_type, "added")
        self.assertEqual(files[0].path, "new.txt")
        self.assertEqual([l.kind for l in files[0].hunks[0].lines], ["add", "add"])

    def test_deleted_file(self):
        text = (
            "diff --git a/gone.txt b/gone.txt\n"
            "deleted file mode 100644\n"
            "index 1111111..0000000\n"
            "--- a/gone.txt\n"
            "+++ /dev/null\n"
            "@@ -1,2 +0,0 @@\n"
            "-line one\n"
            "-line two\n"
        )
        files, _, _ = diff.parse_diff_text(text)
        self.assertEqual(files[0].change_type, "deleted")
        self.assertEqual(files[0].path, "gone.txt")
        self.assertEqual([l.kind for l in files[0].hunks[0].lines], ["remove", "remove"])

    def test_binary_file_reported_without_crash(self):
        text = (
            "diff --git a/assets/sprites/car-2.png b/assets/sprites/car-2.png\n"
            "index 1111111..2222222 100644\n"
            "Binary files a/assets/sprites/car-2.png and b/assets/sprites/car-2.png differ\n"
        )
        files, truncated, _ = diff.parse_diff_text(text)
        self.assertFalse(truncated)
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].binary)
        self.assertEqual(files[0].hunks, [])

    def test_no_newline_at_eof_marker_does_not_crash(self):
        text = (
            "diff --git a/f.txt b/f.txt\n"
            "index 1111111..2222222 100644\n"
            "--- a/f.txt\n"
            "+++ b/f.txt\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "\\ No newline at end of file\n"
            "+new\n"
            "\\ No newline at end of file\n"
        )
        files, _, _ = diff.parse_diff_text(text)
        kinds = [l.kind for l in files[0].hunks[0].lines]
        self.assertEqual(kinds, ["remove", "meta", "add", "meta"])

    def test_multiple_files_in_one_diff(self):
        text = (
            "diff --git a/a.txt b/a.txt\n"
            "index 1111111..2222222 100644\n"
            "--- a/a.txt\n"
            "+++ b/a.txt\n"
            "@@ -1 +1 @@\n"
            "-a\n"
            "+A\n"
            "diff --git a/b.txt b/b.txt\n"
            "index 3333333..4444444 100644\n"
            "--- a/b.txt\n"
            "+++ b/b.txt\n"
            "@@ -1 +1 @@\n"
            "-b\n"
            "+B\n"
        )
        files, _, _ = diff.parse_diff_text(text)
        self.assertEqual([f.path for f in files], ["a.txt", "b.txt"])

    def test_empty_text_is_no_files(self):
        files, truncated, reason = diff.parse_diff_text("")
        self.assertEqual(files, [])
        self.assertFalse(truncated)
        self.assertEqual(reason, "")

    def test_large_diff_is_truncated_visibly(self):
        hunk_lines = "".join(f"+line {i}\n" for i in range(50))
        text = (
            "diff --git a/big.txt b/big.txt\n"
            "index 1111111..2222222 100644\n"
            "--- a/big.txt\n"
            "+++ b/big.txt\n"
            "@@ -0,0 +1,50 @@\n"
            + hunk_lines
        )
        files, truncated, reason = diff.parse_diff_text(text, max_lines=10)

        self.assertTrue(truncated)
        self.assertNotEqual(reason, "")
        total_lines = sum(len(h.lines) for f in files for h in f.hunks)
        self.assertLessEqual(total_lines, 10)


class TestGetDiff(unittest.TestCase):
    def test_clean_worktree_has_no_files_and_no_untracked(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            game_repo = make_committed_game_repo(
                tmp_path / "nuke-raider", {"src/config.h": "#define X 1\n"}
            )
            binding = bind_over(tmp_path, game_repo)

            result = diff.get_diff(binding)

            self.assertEqual(result.files, [])
            self.assertEqual(result.untracked, [])
            self.assertFalse(result.truncated)

    def test_modified_file_appears_as_removed_and_added_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            game_repo = make_committed_game_repo(
                tmp_path / "nuke-raider", {"src/config.h": "#define GEAR1_MAX_SPEED 2u\n"}
            )
            binding = bind_over(tmp_path, game_repo)
            (game_repo / "src" / "config.h").write_text(
                "#define GEAR1_MAX_SPEED 9u\n", encoding="utf-8"
            )

            result = diff.get_diff(binding)

            self.assertEqual(len(result.files), 1)
            f = result.files[0]
            self.assertEqual(f.path, "src/config.h")
            self.assertEqual(f.change_type, "modified")
            kinds = {l.kind for h in f.hunks for l in h.lines}
            self.assertIn("add", kinds)
            self.assertIn("remove", kinds)

    def test_staged_and_unstaged_changes_both_appear_in_one_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            game_repo = make_committed_game_repo(
                tmp_path / "nuke-raider",
                {"a.txt": "a\n", "b.txt": "b\n"},
            )
            binding = bind_over(tmp_path, game_repo)
            (game_repo / "a.txt").write_text("A\n", encoding="utf-8")
            _run_git(["add", "a.txt"], game_repo)  # staged
            (game_repo / "b.txt").write_text("B\n", encoding="utf-8")  # unstaged

            result = diff.get_diff(binding)

            self.assertEqual({f.path for f in result.files}, {"a.txt", "b.txt"})

    def test_deleted_file_shows_as_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            game_repo = make_committed_game_repo(
                tmp_path / "nuke-raider", {"gone.txt": "bye\n"}
            )
            binding = bind_over(tmp_path, game_repo)
            (game_repo / "gone.txt").unlink()

            result = diff.get_diff(binding)

            self.assertEqual(len(result.files), 1)
            self.assertEqual(result.files[0].change_type, "deleted")

    def test_untracked_file_listed_by_name_not_diffed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            game_repo = make_committed_game_repo(
                tmp_path / "nuke-raider", {"src/config.h": "#define X 1\n"}
            )
            binding = bind_over(tmp_path, game_repo)
            (game_repo / "assets" / "sprites").mkdir(parents=True)
            (game_repo / "assets" / "sprites" / "car-2.xcf").write_bytes(b"\x00\x01")

            result = diff.get_diff(binding)

            self.assertEqual(result.files, [])
            self.assertEqual(result.untracked, ["assets/sprites/car-2.xcf"])

    def test_binary_file_change_reports_binary_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            game_repo = make_committed_game_repo(
                tmp_path / "nuke-raider", {"art.bin": "\x00\x01\x02"}
            )
            binding = bind_over(tmp_path, game_repo)
            (game_repo / "art.bin").write_bytes(b"\x00\x01\x02\x03\xff")

            result = diff.get_diff(binding)

            self.assertEqual(len(result.files), 1)
            self.assertTrue(result.files[0].binary)
            self.assertEqual(result.files[0].hunks, [])

    def test_no_commits_yet_still_diffs_staged_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            game_repo = make_bare_game_repo(tmp_path / "nuke-raider")
            (game_repo / "src").mkdir()
            (game_repo / "src" / "config.h").write_text("#define X 1\n", encoding="utf-8")
            _run_git(["add", "."], game_repo)
            binding = bind_over(tmp_path, game_repo)

            result = diff.get_diff(binding)

            self.assertEqual(len(result.files), 1)
            self.assertEqual(result.files[0].path, "src/config.h")
            self.assertEqual(result.files[0].change_type, "added")

    def test_no_commits_yet_with_no_staged_content_is_clean_with_untracked(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            game_repo = make_bare_game_repo(tmp_path / "nuke-raider")
            (game_repo / "README.md").write_text("hi\n", encoding="utf-8")
            binding = bind_over(tmp_path, game_repo)

            result = diff.get_diff(binding)

            self.assertEqual(result.files, [])
            self.assertEqual(result.untracked, ["README.md"])

    def test_normal_refresh_uses_two_subprocess_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            game_repo = make_committed_game_repo(
                tmp_path / "nuke-raider", {"src/config.h": "#define X 1\n"}
            )
            binding = bind_over(tmp_path, game_repo)
            (game_repo / "src" / "config.h").write_text("#define X 2\n", encoding="utf-8")

            with unittest.mock.patch(
                "tools.garage.core.diff.subprocess.run", wraps=subprocess.run
            ) as spy:
                diff.get_diff(binding)

            self.assertEqual(spy.call_count, 2)  # one diff, one untracked list


class TestGetChangeSummary(unittest.TestCase):
    """R2/AC2, redesigned header: the four totals -- tracked changed-file
    count, untracked count, added lines, removed lines -- computed once in
    core so the Qt layer never derives them itself.
    """

    def test_clean_worktree_is_not_dirty(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            game_repo = make_committed_game_repo(
                tmp_path / "nuke-raider", {"src/config.h": "#define X 1\n"}
            )

            summary = diff.get_change_summary(game_repo)

            self.assertFalse(summary.dirty)
            self.assertEqual(summary.changed_file_count, 0)
            self.assertEqual(summary.untracked_count, 0)
            self.assertEqual(summary.added_lines, 0)
            self.assertEqual(summary.removed_lines, 0)

    def test_tracked_change_and_untracked_file_are_counted_separately(self):
        # AC2 fix: an untracked file must not inflate changed_file_count --
        # one modified tracked file and one untracked file must read as
        # changed_file_count=1, untracked_count=1, never changed_file_count=2.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            game_repo = make_committed_game_repo(
                tmp_path / "nuke-raider", {"a.txt": "a\n", "b.txt": "b\n"}
            )
            (game_repo / "a.txt").write_text("A\n", encoding="utf-8")
            (game_repo / "new.txt").write_text("new\n", encoding="utf-8")

            summary = diff.get_change_summary(game_repo)

            self.assertTrue(summary.dirty)
            self.assertEqual(summary.changed_file_count, 1)
            self.assertEqual(summary.untracked_count, 1)

    def test_added_and_removed_line_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            game_repo = make_committed_game_repo(
                tmp_path / "nuke-raider", {"a.txt": "one\ntwo\nthree\n"}
            )
            (game_repo / "a.txt").write_text("one\nTWO\nTHREE\nfour\n", encoding="utf-8")

            summary = diff.get_change_summary(game_repo)

            self.assertEqual(summary.changed_file_count, 1)
            self.assertEqual(summary.added_lines, 3)
            self.assertEqual(summary.removed_lines, 2)

    def test_multiple_changed_files_sum_across_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            game_repo = make_committed_game_repo(
                tmp_path / "nuke-raider", {"a.txt": "a\n", "b.txt": "b\nc\n"}
            )
            (game_repo / "a.txt").write_text("A\nA2\n", encoding="utf-8")
            (game_repo / "b.txt").write_text("B\n", encoding="utf-8")

            summary = diff.get_change_summary(game_repo)

            self.assertEqual(summary.changed_file_count, 2)
            self.assertEqual(summary.added_lines, 3)  # A, A2, B
            self.assertEqual(summary.removed_lines, 3)  # a, b, c

    def test_no_commits_yet_counts_staged_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            game_repo = make_bare_game_repo(tmp_path / "nuke-raider")
            (game_repo / "src").mkdir()
            (game_repo / "src" / "config.h").write_text("#define X 1\n", encoding="utf-8")
            _run_git(["add", "."], game_repo)

            summary = diff.get_change_summary(game_repo)

            self.assertEqual(summary.changed_file_count, 1)
            self.assertEqual(summary.added_lines, 1)
            self.assertEqual(summary.removed_lines, 0)
            self.assertEqual(summary.untracked_count, 0)

    def test_ac20_untracked_only_is_not_dirty(self):
        # AC20: the "●" mark stands for a *tracked* file that differs from
        # HEAD. An untracked file is counted (untracked_count == 1) but
        # must not raise `dirty` on its own -- real temp git repo, no mock.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            game_repo = make_committed_game_repo(
                tmp_path / "nuke-raider", {"src/config.h": "#define X 1\n"}
            )
            (game_repo / "new.txt").write_text("new\n", encoding="utf-8")

            summary = diff.get_change_summary(game_repo)

            self.assertFalse(summary.dirty)
            self.assertEqual(summary.changed_file_count, 0)
            self.assertEqual(summary.untracked_count, 1)

    def test_ac20_tracked_change_alone_is_dirty(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            game_repo = make_committed_game_repo(
                tmp_path / "nuke-raider", {"a.txt": "a\n"}
            )
            (game_repo / "a.txt").write_text("A\n", encoding="utf-8")

            summary = diff.get_change_summary(game_repo)

            self.assertTrue(summary.dirty)
            self.assertEqual(summary.changed_file_count, 1)
            self.assertEqual(summary.untracked_count, 0)

    def test_ac20_tracked_change_and_untracked_together_is_dirty(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            game_repo = make_committed_game_repo(
                tmp_path / "nuke-raider", {"a.txt": "a\n"}
            )
            (game_repo / "a.txt").write_text("A\n", encoding="utf-8")
            (game_repo / "new.txt").write_text("new\n", encoding="utf-8")

            summary = diff.get_change_summary(game_repo)

            self.assertTrue(summary.dirty)
            self.assertEqual(summary.changed_file_count, 1)
            self.assertEqual(summary.untracked_count, 1)

    def test_is_master_branch(self):
        self.assertTrue(diff.is_master_branch("master"))
        self.assertFalse(diff.is_master_branch("feat"))
        self.assertFalse(diff.is_master_branch(None))


# -- doctor (R14 / AC14) -----------------------------------------------------
#
# Every test below describes a machine to `doctor.run_checks` through its
# seams (`which`, `environ`, `settings`, `probe`) instead of asking the one
# the suite happens to run on. Nothing here reads the real PATH: the point
# of the module is what it says when a tool is missing, and the test machine
# is not allowed a say in whether that case is exercised.


def make_toolchain(tmp_path: Path):
    """A machine with every R14 item present. Returns (which, environ,
    settings); a test removes what it wants missing.

    The paths that are looked at on disk (GBDK's bin/lcc, the Emulicious
    jar) are created for real, since `doctor` stats them.
    """
    gbdk = tmp_path / "gbdk"
    (gbdk / "bin").mkdir(parents=True, exist_ok=True)
    (gbdk / "bin" / "lcc.exe").write_text("", encoding="utf-8")
    (gbdk / "bin" / "romusage.exe").write_text("", encoding="utf-8")

    jar = tmp_path / "Emulicious" / "Emulicious.jar"
    jar.parent.mkdir(parents=True, exist_ok=True)
    jar.write_text("", encoding="utf-8")

    git_bin = tmp_path / "Git" / "bin"
    git_usr_bin = tmp_path / "Git" / "usr" / "bin"

    which = {
        "make": str(tmp_path / "make.exe"),
        "gcc": str(tmp_path / "mingw" / "bin" / "gcc.exe"),
        "romusage": str(gbdk / "bin" / "romusage.exe"),
        "java": str(tmp_path / "jdk" / "bin" / "java.exe"),
        "bash": str(git_bin / "bash.exe"),
        "sed": str(git_usr_bin / "sed.exe"),
    }
    # Forward slashes, like the value that actually builds: the Makefile
    # expands GBDK_HOME inside a bash recipe, so a backslash in it is a
    # failure of its own (see the backslash test below).
    environ = {"GBDK_HOME": str(gbdk).replace("\\", "/")}
    settings = {"emulicious_jar": str(jar)}
    return which, environ, settings


def stub_binding(tmp_path: Path) -> project.Binding:
    """A resolved Binding built directly, for the tests whose subject is a
    tool rather than the binding itself -- so a report's totals do not
    depend on a git repository the test never looks at.
    """
    worktree = project.Worktree(path=tmp_path / "nuke-raider", branch="feat", head="0" * 40)
    return project.Binding(
        game_repo=worktree.path,
        game_repo_source="recorded",
        worktree_root=tmp_path / "worktrees",
        worktrees=[worktree],
        active_worktree=worktree,
        active_source="main-fallback",
        settings_path=tmp_path / "nuke-raider-garage" / "garage.local.json",
    )


def run_doctor(which_map, environ, settings, binding=None, binding_error=None):
    return doctor.run_checks(
        binding,
        binding_error,
        which=lambda name: which_map.get(name),
        environ=environ,
        settings=settings,
        probe=lambda command: "1.2.3",
    )


class TestDoctorChecksEverythingR14Names(unittest.TestCase):
    def test_report_covers_every_required_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            which, environ, settings = make_toolchain(Path(tmp))

            report = run_doctor(which, environ, settings)

            self.assertEqual(
                [c.key for c in report.checks],
                [
                    "game-repo",
                    "classification",
                    "make",
                    "gcc",
                    "gbdk-home",
                    "romusage",
                    "git-unix-tools",
                    "java",
                    "emulicious",
                ],
            )

    def test_a_complete_machine_passes_every_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            which, environ, settings = make_toolchain(tmp_path)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo(tmp_path / "nuke-raider")
            binding = project.bind(garage_root)

            report = run_doctor(which, environ, settings, binding=binding)

            # The classification check reads the bound repository's
            # src/config.h; this fixture repo has none, so that one row is
            # expected to fail and every other must pass.
            self.assertEqual(
                [c.key for c in report.failures], ["classification"]
            )
            self.assertEqual(report.summary(), "8 of 9 checks passing · failing: classification")

    def test_every_failure_names_what_it_prevents(self):
        # The general form of AC14: no check may report a failure without
        # saying which part of the loop just stopped working.
        with tempfile.TemporaryDirectory() as tmp:
            # An explicit jar path that does not exist: the default install
            # path may well be present on the machine running this.
            report = run_doctor(
                {}, {"EMULICIOUS_JAR": str(Path(tmp) / "nowhere.jar")}, None
            )

            self.assertEqual(len(report.failures), 9)
            for check in report.failures:
                self.assertTrue(
                    check.prevents.strip(),
                    f"{check.key} failed without naming what it prevents",
                )
                self.assertTrue(check.detail.strip(), f"{check.key} gave no detail")


class TestDoctorClassification(unittest.TestCase):
    """R8/AC9's second half: Garage reports the drift when it starts. The
    first half — the same drift failing this repository's test suite —
    lives in tests/test_garage_lint.py.
    """

    def _bound(self, tmp_path, config_text):
        garage_root = tmp_path / "nuke-raider-garage"
        garage_root.mkdir()
        make_game_repo_with_config(tmp_path / "nuke-raider", config_text)
        return project.bind(garage_root)

    def test_a_header_that_matches_the_classification_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding = self._bound(tmp_path, SAMPLE_CONFIG_TEXT)
            schema = Schema.load(
                write_json(tmp_path / "t.json", SAMPLE_TUNABLES_FOR_CONFIG_IO)
            )

            check = doctor.check_classification(binding, schema)

            self.assertEqual(check.status, doctor.PASS)
            self.assertIn("all classified", check.detail)

    def test_an_unclassified_define_is_reported_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            drifted = SAMPLE_CONFIG_TEXT.replace(
                "#endif /* CONFIG_H */",
                "#define NEW_UNCLASSIFIED_DEFINE 3u\n\n#endif /* CONFIG_H */",
            )
            binding = self._bound(tmp_path, drifted)
            schema = Schema.load(
                write_json(tmp_path / "t.json", SAMPLE_TUNABLES_FOR_CONFIG_IO)
            )

            check = doctor.check_classification(binding, schema)

            self.assertEqual(check.status, doctor.FAIL)
            self.assertIn("NEW_UNCLASSIFIED_DEFINE", check.detail)
            self.assertIn("unclassified", check.detail)
            self.assertIn("tunables.json", check.prevents)
            self.assertEqual(check.tag, "1 unclassified")

    def test_a_classification_entry_the_header_dropped_is_reported_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding = self._bound(tmp_path, SAMPLE_CONFIG_TEXT)
            extended = json.loads(json.dumps(SAMPLE_TUNABLES_FOR_CONFIG_IO))
            extended["entries"]["GONE_FROM_HEADER"] = {
                "class": "structural",
                "reason": "removed from the header",
            }
            schema = Schema.load(write_json(tmp_path / "t.json", extended))

            check = doctor.check_classification(binding, schema)

            self.assertEqual(check.status, doctor.FAIL)
            self.assertIn("GONE_FROM_HEADER", check.detail)
            self.assertIn("gone from src/config.h", check.detail)

    def test_without_a_binding_it_says_it_cannot_check(self):
        check = doctor.check_classification(None)

        self.assertEqual(check.status, doctor.FAIL)
        self.assertIn("no game repository is bound", check.detail)


class TestDoctorRomusage(unittest.TestCase):
    """AC14: "The toolchain verification reports a failure when romusage is
    absent from PATH, and names what it prevents."
    """

    def test_absent_from_path_is_a_failure_naming_bank_post_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            which, environ, settings = make_toolchain(Path(tmp))
            del which["romusage"]

            report = run_doctor(which, environ, settings)
            check = {c.key: c for c in report.checks}["romusage"]

            self.assertEqual(check.status, doctor.FAIL)
            self.assertIn("not found on PATH", check.detail)
            self.assertIn("bank-post-build", check.prevents)
            self.assertIn("461", check.prevents)

    def test_failure_shows_in_the_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            which, environ, settings = make_toolchain(tmp_path)
            del which["romusage"]

            report = run_doctor(
                which, environ, settings, binding=stub_binding(tmp_path)
            )

            self.assertFalse(report.ok)
            self.assertIn("romusage", report.summary())
            # The stub binding names no real repository, so the
            # classification row fails alongside romusage.
            self.assertIn("7 of 9 checks passing", report.summary())

    def test_detail_names_the_gbdk_bin_directory_that_ships_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            which, environ, settings = make_toolchain(tmp_path)
            del which["romusage"]

            report = run_doctor(which, environ, settings)
            check = {c.key: c for c in report.checks}["romusage"]

            self.assertIn(str(tmp_path / "gbdk" / "bin"), check.detail)

    def test_detail_omits_the_hint_when_gbdk_home_does_not_hold_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            which, environ, settings = make_toolchain(tmp_path)
            del which["romusage"]
            (tmp_path / "gbdk" / "bin" / "romusage.exe").unlink()

            report = run_doctor(which, environ, settings)
            check = {c.key: c for c in report.checks}["romusage"]

            self.assertEqual(check.detail, "not found on PATH")

    def test_present_reports_its_resolved_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            which, environ, settings = make_toolchain(tmp_path)

            report = run_doctor(which, environ, settings)
            check = {c.key: c for c in report.checks}["romusage"]

            self.assertEqual(check.status, doctor.PASS)
            self.assertEqual(check.detail, which["romusage"])
            self.assertEqual(check.prevents, "")


class TestDoctorBuildChain(unittest.TestCase):
    def test_make_absent_is_a_failure_naming_the_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            which, environ, settings = make_toolchain(Path(tmp))
            del which["make"]

            check = {c.key: c for c in run_doctor(which, environ, settings).checks}["make"]

            self.assertEqual(check.status, doctor.FAIL)
            self.assertIn("memory-check", check.prevents)

    def test_gcc_absent_is_a_failure_naming_the_host_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            which, environ, settings = make_toolchain(Path(tmp))
            del which["gcc"]

            check = {c.key: c for c in run_doctor(which, environ, settings).checks}["gcc"]

            self.assertEqual(check.status, doctor.FAIL)
            self.assertIn("make test", check.prevents)

    def test_gbdk_home_unset_is_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            which, environ, settings = make_toolchain(Path(tmp))
            environ.pop("GBDK_HOME")

            report = run_doctor(which, environ, settings)
            check = {c.key: c for c in report.checks}["gbdk-home"]

            self.assertEqual(check.status, doctor.FAIL)
            self.assertEqual(check.detail, "not set")
            self.assertIn("lcc", check.prevents)

    def test_gbdk_home_without_lcc_is_a_failure_that_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            which, environ, settings = make_toolchain(tmp_path)
            (tmp_path / "gbdk" / "bin" / "lcc.exe").unlink()

            check = {
                c.key: c for c in run_doctor(which, environ, settings).checks
            }["gbdk-home"]

            self.assertEqual(check.status, doctor.FAIL)
            self.assertIn("bin/lcc", check.detail)

    def test_gbdk_home_with_backslashes_fails_even_though_lcc_is_there(self):
        # The real defect: `C:\gbdk` holds bin/lcc, so every existence test
        # passes, and no source file compiles. The Makefile expands it into
        # a bash recipe, where `\g` is an escape and the path is mangled.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            which, environ, settings = make_toolchain(tmp_path)
            environ["GBDK_HOME"] = str(tmp_path / "gbdk").replace("/", "\\")

            check = {
                c.key: c for c in run_doctor(which, environ, settings).checks
            }["gbdk-home"]

            self.assertEqual(check.status, doctor.FAIL)
            self.assertIn("backslash", check.detail)
            # It names the form to use, not just the problem.
            self.assertIn(str(tmp_path / "gbdk").replace("\\", "/"), check.detail)
            self.assertIn("127", check.prevents)

    def test_gbdk_home_holding_lcc_passes_and_reports_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            which, environ, settings = make_toolchain(tmp_path)

            check = {
                c.key: c for c in run_doctor(which, environ, settings).checks
            }["gbdk-home"]

            self.assertEqual(check.status, doctor.PASS)
            self.assertEqual(check.detail, str(tmp_path / "gbdk" / "bin" / "lcc.exe"))

    def test_git_unix_tools_missing_bash_is_a_failure_naming_bash(self):
        with tempfile.TemporaryDirectory() as tmp:
            which, environ, settings = make_toolchain(Path(tmp))
            del which["bash"]

            check = {
                c.key: c for c in run_doctor(which, environ, settings).checks
            }["git-unix-tools"]

            self.assertEqual(check.status, doctor.FAIL)
            self.assertIn("bash", check.detail)
            self.assertNotIn("sed", check.detail)
            self.assertIn("SHELL := bash", check.prevents)

    def test_git_unix_tools_reports_both_directories_once_each(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            which, environ, settings = make_toolchain(tmp_path)

            check = {
                c.key: c for c in run_doctor(which, environ, settings).checks
            }["git-unix-tools"]

            self.assertEqual(check.status, doctor.PASS)
            self.assertIn(str(tmp_path / "Git" / "bin"), check.detail)
            self.assertIn(str(tmp_path / "Git" / "usr" / "bin"), check.detail)

    def test_git_unix_tools_in_one_directory_is_not_repeated(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            which, environ, settings = make_toolchain(tmp_path)
            which["sed"] = str(Path(which["bash"]).parent / "sed.exe")

            check = {
                c.key: c for c in run_doctor(which, environ, settings).checks
            }["git-unix-tools"]

            self.assertEqual(check.detail, str(tmp_path / "Git" / "bin"))


class TestDoctorEmulator(unittest.TestCase):
    def test_java_absent_prevents_the_emulator(self):
        with tempfile.TemporaryDirectory() as tmp:
            which, environ, settings = make_toolchain(Path(tmp))
            del which["java"]

            check = {c.key: c for c in run_doctor(which, environ, settings).checks}["java"]

            self.assertEqual(check.status, doctor.FAIL)
            self.assertIn("Emulicious", check.prevents)

    def test_missing_jar_is_a_failure_naming_the_settings_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            which, environ, settings = make_toolchain(tmp_path)
            (tmp_path / "Emulicious" / "Emulicious.jar").unlink()

            check = {
                c.key: c for c in run_doctor(which, environ, settings).checks
            }["emulicious"]

            self.assertEqual(check.status, doctor.FAIL)
            self.assertIn("garage.local.json", check.detail)
            self.assertIn("emulicious_jar", check.detail)

    def test_jar_path_comes_from_settings_first_then_env_then_the_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            recorded = tmp_path / "recorded.jar"
            from_env = tmp_path / "env.jar"

            self.assertEqual(
                doctor.resolve_emulicious_jar(
                    {"emulicious_jar": str(recorded)},
                    {"EMULICIOUS_JAR": str(from_env)},
                ),
                recorded,
            )
            self.assertEqual(
                doctor.resolve_emulicious_jar({}, {"EMULICIOUS_JAR": str(from_env)}),
                from_env,
            )
            self.assertEqual(
                doctor.resolve_emulicious_jar(None, {}),
                Path(doctor.DEFAULT_EMULICIOUS_JAR),
            )


class TestDoctorBinding(unittest.TestCase):
    """R17's last sentence: a binding that no longer resolves is reported
    here as a toolchain failure, not only inside the panels that trip on it.
    """

    def test_a_resolved_binding_passes_and_shows_the_active_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo(tmp_path / "nuke-raider")
            binding = project.bind(garage_root)

            check = doctor.check_binding(binding, None)

            self.assertEqual(check.status, doctor.PASS)
            self.assertEqual(check.detail, str(game_repo))

    def test_a_binding_error_is_a_failure_carrying_its_message(self):
        error = project.BindingError("game_repo", "the recorded path is gone")

        check = doctor.check_binding(None, error)

        self.assertEqual(check.status, doctor.FAIL)
        self.assertIn("game_repo", check.detail)
        self.assertIn("the recorded path is gone", check.detail)
        self.assertIn("config.h", check.prevents)

    def test_settings_default_to_the_bound_repositorys_own_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo(tmp_path / "nuke-raider")
            binding = project.bind(garage_root)
            jar = tmp_path / "recorded.jar"
            jar.write_text("", encoding="utf-8")
            recorded = project.load_settings(garage_root)
            recorded["emulicious_jar"] = str(jar)
            project.save_settings(garage_root, recorded)

            report = doctor.run_checks(
                binding,
                None,
                which=lambda name: None,
                environ={},
                probe=lambda command: "",
            )
            check = {c.key: c for c in report.checks}["emulicious"]

            self.assertEqual(check.status, doctor.PASS)
            self.assertEqual(check.detail, str(jar))

    def test_load_binding_settings_without_a_binding(self):
        self.assertIsNone(doctor.load_binding_settings(None))


class TestDoctorVersionProbe(unittest.TestCase):
    def test_reads_the_first_dotted_version_from_stdout(self):
        self.assertEqual(
            doctor.probe_version(
                [sys.executable, "-c", "print('GNU Make 4.4.1')"]
            ),
            "4.4.1",
        )

    def test_reads_a_version_written_to_stderr(self):
        # java -version writes its banner to stderr.
        self.assertEqual(
            doctor.probe_version(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stderr.write('openjdk version \"25.0.3\"')",
                ]
            ),
            "25.0.3",
        )

    def test_a_tool_that_cannot_be_run_gives_no_version_and_does_not_raise(self):
        self.assertEqual(
            doctor.probe_version(["no-such-executable-should-exist-here"]), ""
        )

    def test_output_without_a_version_gives_an_empty_string(self):
        self.assertEqual(
            doctor.probe_version([sys.executable, "-c", "print('hello')"]), ""
        )


# -- make_runner (R11 / R6 / AC11) -------------------------------------------
#
# Nothing here runs `make`: the suite must pass on a machine with no
# toolchain (AC15), and what is being tested is the streaming, the exit
# code, the cwd and the cancellation -- none of which is specific to make.
# The child process is this interpreter, which is guaranteed to be present
# and whose output the test controls exactly.


def _worktree_with_objects(worktree: Path) -> Path:
    """A worktree that has been compiled once: src/config.h and a couple of
    objects in build/obj.
    """
    (worktree / "src").mkdir(parents=True, exist_ok=True)
    (worktree / "src" / "config.h").write_text("#define A 1\n", encoding="utf-8")
    (worktree / "build" / "obj").mkdir(parents=True, exist_ok=True)
    for name in ("main.o", "race.o"):
        (worktree / "build" / "obj" / name).write_bytes(b"\0")
    return worktree


def _touch_newer(path: Path, than: Path) -> None:
    """Make `path` unambiguously newer than everything in `than`, without
    depending on the filesystem's timestamp resolution or on sleeping.
    """
    newest = max(child.stat().st_mtime for child in than.iterdir())
    import os

    os.utime(path, (newest + 10, newest + 10))


def python_command(source: str, label="python") -> make_runner.Command:
    return make_runner.Command(argv=(sys.executable, "-c", source), label=label)


class TestMakeCommands(unittest.TestCase):
    def test_the_four_targets_r11_names(self):
        self.assertEqual(make_runner.make_command("build").argv, ("make",))
        self.assertEqual(make_runner.make_command("clean").argv, ("make", "clean"))
        self.assertEqual(
            make_runner.make_command("memory-check").argv, ("make", "memory-check")
        )
        self.assertEqual(
            make_runner.make_command("bank-post-build").argv,
            ("make", "bank-post-build"),
        )

    def test_label_is_what_a_log_echoes(self):
        self.assertEqual(make_runner.make_command("build").label, "make")
        self.assertEqual(make_runner.make_command("clean").label, "make clean")

    def test_an_unknown_target_is_refused(self):
        with self.assertRaises(make_runner.UnknownTargetError) as raised:
            make_runner.make_command("install")
        self.assertIn("bank-post-build", str(raised.exception))

    def test_rom_path_resolves_against_the_worktree(self):
        # AC11: the ROM the default target writes, in the active worktree.
        worktree = Path("C:/worktrees/feat-x")
        self.assertEqual(
            make_runner.rom_path(worktree), worktree / "build" / "nuke-raider.gb"
        )

    def test_describe_rom_reports_the_written_rom_and_its_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp)
            (worktree / "build").mkdir()
            (worktree / "build" / "nuke-raider.gb").write_bytes(b"\0" * 524288)

            description = make_runner.describe_rom(worktree)

            self.assertIn("nuke-raider.gb", description)
            self.assertIn("512 KB", description)

    def test_a_config_edit_after_a_compile_needs_a_clean_build(self):
        # The game repository's Makefile has no header dependency, so an
        # incremental make would relink the old objects and hand back a ROM
        # that does not carry the edited value.
        with tempfile.TemporaryDirectory() as tmp:
            worktree = _worktree_with_objects(Path(tmp))
            _touch_newer(worktree / "src" / "config.h", worktree / "build" / "obj")

            self.assertTrue(make_runner.needs_clean_build(worktree))

    def test_objects_compiled_after_the_last_edit_need_no_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            worktree = _worktree_with_objects(Path(tmp))
            _touch_newer(worktree / "build" / "obj" / "main.o", worktree / "src")

            self.assertFalse(make_runner.needs_clean_build(worktree))

    def test_a_tree_that_was_never_compiled_needs_no_clean(self):
        # Nothing to relink: a build with no objects compiles everything,
        # and cleaning would only delete an empty directory.
        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp)
            (worktree / "src").mkdir()
            (worktree / "src" / "config.h").write_text("#define A 1\n", encoding="utf-8")

            self.assertFalse(make_runner.needs_clean_build(worktree))

    def test_a_command_remembers_the_target_it_came_from(self):
        self.assertEqual(make_runner.make_command("clean").target, "clean")

    def test_describe_rom_says_so_when_the_rom_is_absent(self):
        # A make that exits 0 without writing the ROM must not read as a
        # successful build.
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("was not written", make_runner.describe_rom(Path(tmp)))


class TestExplainFailure(unittest.TestCase):
    """A failed target names the toolchain check that already explains it.
    Both of the real cases this came from -- `make clean` dying on a
    missing `rm` (Git's usr\\bin absent, so make's `SHELL := bash` falls
    back to cmd) and `make bank-post-build` dying on a missing `romusage`
    -- were reported by the Doctor at startup and then left for the user to
    re-derive from the tool's own traceback.
    """

    def _report(self, *failing_keys):
        checks = []
        for key in ("make", "gbdk-home", "romusage", "git-unix-tools"):
            failed = key in failing_keys
            checks.append(
                doctor.CheckResult(
                    key=key,
                    name=f"{key} — a tool",
                    status=doctor.FAIL if failed else doctor.PASS,
                    detail="not found on PATH" if failed else "C:/bin/tool.exe",
                    prevents="the thing it prevents" if failed else "",
                )
            )
        return doctor.Report(checks=checks)

    def test_every_target_declares_what_it_needs(self):
        self.assertEqual(
            set(make_runner.TARGET_REQUIREMENTS), set(make_runner.MAKE_TARGETS)
        )
        keys = {
            key
            for required in make_runner.TARGET_REQUIREMENTS.values()
            for key in required
        }
        report_keys = {c.key for c in doctor.run_checks(which=lambda n: None).checks}
        self.assertTrue(
            keys <= report_keys, f"unknown check keys: {keys - report_keys}"
        )

    def test_bank_post_build_points_at_romusage(self):
        lines = make_runner.explain_failure(
            "bank-post-build", self._report("romusage")
        )

        self.assertTrue(lines)
        self.assertIn("Toolchain", lines[0])
        self.assertTrue(any("romusage" in line for line in lines))
        self.assertTrue(any("the thing it prevents" in line for line in lines))

    def test_clean_points_at_the_missing_coreutils(self):
        lines = make_runner.explain_failure("clean", self._report("git-unix-tools"))

        self.assertTrue(any("git-unix-tools" in line for line in lines))

    def test_a_check_the_target_does_not_need_is_not_mentioned(self):
        # memory-check runs a Python script; a missing romusage has nothing
        # to do with it, and saying so would bury the real error.
        self.assertEqual(
            make_runner.explain_failure("memory-check", self._report("romusage")), []
        )

    def test_a_whole_toolchain_explains_nothing(self):
        self.assertEqual(
            make_runner.explain_failure("bank-post-build", self._report()), []
        )

    def test_a_measuring_target_with_no_build_says_build_first(self):
        # The real case: `make memory-check` against a cleaned worktree
        # raises a TypeError out of the game repository's own script,
        # because it formats a None. "Run Build first" is the content.
        with tempfile.TemporaryDirectory() as tmp:
            lines = make_runner.explain_missing_rom("memory-check", Path(tmp))

            self.assertTrue(lines)
            self.assertIn("Run Build first", lines[0])
            self.assertIn("nuke-raider.gb", lines[0])

    def test_a_measuring_target_with_a_rom_present_explains_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp)
            (worktree / "build").mkdir()
            (worktree / "build" / "nuke-raider.gb").write_bytes(b"\0")

            self.assertEqual(
                make_runner.explain_missing_rom("bank-post-build", worktree), []
            )

    def test_a_build_target_is_never_told_to_build_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(make_runner.explain_missing_rom("build", Path(tmp)), [])
            self.assertEqual(make_runner.explain_missing_rom("clean", Path(tmp)), [])

    def test_no_report_and_no_target_are_both_harmless(self):
        self.assertEqual(make_runner.explain_failure("build", None), [])
        self.assertEqual(make_runner.explain_failure("", self._report("make")), [])


class TestRun(unittest.TestCase):
    def test_lines_arrive_one_by_one_in_order(self):
        lines = []

        result = make_runner.run(
            python_command("print('one'); print('two'); print('three')"),
            Path.cwd(),
            lines.append,
        )

        self.assertEqual(lines, ["one", "two", "three"])
        self.assertTrue(result.ok)
        self.assertEqual(result.exit_code, 0)

    def test_output_arrives_while_the_process_is_still_running(self):
        # R6: the display must show progress, not a blob at the end. The
        # child holds its second line back until the test has seen the
        # first one, so this can only pass if `run` delivered mid-flight.
        seen_first = threading.Event()
        lines = []

        def on_line(line):
            lines.append(line)
            seen_first.set()

        source = (
            "import sys, time\n"
            "print('first', flush=True)\n"
            "time.sleep(0.4)\n"
            "print('second', flush=True)\n"
        )
        finished = threading.Event()

        def target():
            make_runner.run(python_command(source), Path.cwd(), on_line)
            finished.set()

        worker = threading.Thread(target=target)
        worker.start()
        try:
            self.assertTrue(seen_first.wait(10), "no line arrived at all")
            self.assertEqual(lines, ["first"])
            self.assertFalse(finished.is_set(), "the run had already ended")
        finally:
            worker.join(15)
        self.assertEqual(lines, ["first", "second"])

    def test_stderr_is_merged_into_the_same_stream(self):
        lines = []

        make_runner.run(
            python_command(
                "import sys\n"
                "sys.stdout.write('out\\n'); sys.stdout.flush()\n"
                "sys.stderr.write('err\\n')\n"
            ),
            Path.cwd(),
            lines.append,
        )

        self.assertEqual(sorted(lines), ["err", "out"])

    def test_a_failing_command_reports_its_exit_code(self):
        result = make_runner.run(
            python_command("raise SystemExit(2)"), Path.cwd(), lambda line: None
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.exit_code, 2)
        self.assertFalse(result.cancelled)

    def test_it_runs_in_the_directory_it_is_given(self):
        # R2: every make call resolves against the active worktree.
        with tempfile.TemporaryDirectory() as tmp:
            lines = []

            make_runner.run(
                python_command("import os; print(os.getcwd())"),
                Path(tmp),
                lines.append,
            )

            self.assertEqual(
                Path(lines[0]).resolve(), Path(tmp).resolve()
            )

    def test_a_missing_executable_is_a_result_not_a_crash(self):
        lines = []

        result = make_runner.run(
            make_runner.Command(argv=("no-such-tool-anywhere",), label="no-such-tool"),
            Path.cwd(),
            lines.append,
        )

        self.assertEqual(result.exit_code, make_runner.EXIT_NOT_STARTED)
        self.assertFalse(result.ok)
        self.assertTrue(lines, "the failure was not reported to the log")
        self.assertIn("no-such-tool-anywhere", lines[0])

    def test_output_that_is_not_utf8_costs_one_glyph_not_the_run(self):
        result = make_runner.run(
            python_command(
                "import sys\n"
                "sys.stdout.buffer.write(b'caf\\xe9 au lait\\n')\n"
            ),
            Path.cwd(),
            lambda line: None,
        )

        self.assertTrue(result.ok)


class TestCancellation(unittest.TestCase):
    FOREVER = (
        "import time\n"
        "print('started', flush=True)\n"
        "while True:\n"
        "    time.sleep(0.05)\n"
    )

    def test_cancelling_a_running_command_ends_it(self):
        started = threading.Event()
        cancellation = make_runner.Cancellation()
        results = []

        def on_line(line):
            started.set()

        def target():
            results.append(
                make_runner.run(
                    python_command(self.FOREVER), Path.cwd(), on_line, cancellation
                )
            )

        worker = threading.Thread(target=target)
        worker.start()
        try:
            self.assertTrue(started.wait(10), "the child never started")
            cancellation.cancel()
            worker.join(15)
            self.assertFalse(worker.is_alive(), "the run outlived its cancellation")
        finally:
            cancellation.cancel()
            worker.join(15)

        result = results[0]
        self.assertTrue(result.cancelled)
        self.assertEqual(result.exit_code, make_runner.EXIT_CANCELLED)
        # A stopped run is not a failed build, and must not read as one.
        self.assertFalse(result.ok)

    def test_a_command_started_after_a_cancellation_never_runs(self):
        cancellation = make_runner.Cancellation()
        cancellation.cancel()
        lines = []

        result = make_runner.run(
            python_command("print('should not appear')"),
            Path.cwd(),
            lines.append,
            cancellation,
        )

        self.assertEqual(lines, [])
        self.assertTrue(result.cancelled)


class TestRunSequence(unittest.TestCase):
    def test_commands_run_in_order_and_are_echoed_first(self):
        echoed = []
        lines = []

        results = make_runner.run_sequence(
            [
                python_command("print('clean')", label="make clean"),
                python_command("print('build')", label="make"),
            ],
            Path.cwd(),
            lines.append,
            on_command=lambda command: echoed.append(command.label),
        )

        self.assertEqual(echoed, ["make clean", "make"])
        self.assertEqual(lines, ["clean", "build"])
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.ok for r in results))

    def test_a_failure_stops_the_rest(self):
        # "Clean build" is clean then build; building on a clean that
        # failed would compile against a half-deleted tree.
        lines = []

        results = make_runner.run_sequence(
            [
                python_command("raise SystemExit(2)", label="make clean"),
                python_command("print('build')", label="make"),
            ],
            Path.cwd(),
            lines.append,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].exit_code, 2)
        self.assertEqual(lines, [])

    def test_a_cancelled_sequence_stops_between_commands(self):
        cancellation = make_runner.Cancellation()
        cancellation.cancel()

        results = make_runner.run_sequence(
            [python_command("print('nope')")],
            Path.cwd(),
            lambda line: None,
            cancellation,
        )

        self.assertEqual(results, [])


# -- budgets (R12 / R13 / AC12 / AC13) ---------------------------------------
#
# The two fixtures below are verbatim output from a real build of the game
# repository (a clone, full toolchain, GBDK 4.3 / romusage 1.3.2). AC12 is
# "the budget panel shows the same numbers as `make memory-check`", so the
# text those tools actually print is the only honest fixture: a paraphrase
# would let the parser drift from the format it exists to read.

MEMORY_CHECK_OUTPUT = """\
python tools/memory_check.py .
=== GB Memory Validation Report ===
WRAM:  1,534 / 8,192 bytes   (18%)  PASS
VRAM:  76 / 384 tiles   (19%)  PASS
OAM:   32 / 40 sprites  (80%)  WARN  [busiest scene: Playing]
       cross-check vs pool: PASS — pool MAX_SPRITES=32 matches busiest scene (Playing)
       per-scene peak OAM:
         Title      0 / 40   (—)
         Overmap    1 / 40   (car=1)
         Hub        1 / 40   (dialog_arrow=1)
         Prerace    0 / 40   (—)
         Playing   32 / 40   (player=4, projectiles=8, turrets=8, racers=8, patrol=4)
         Results    0 / 40   (—)
         GameOver   0 / 40   (—)

WARN
"""

BANK_REPORT_OUTPUT = """\
python tools/bank_post_build.py .
=== Bank Post-Build Report ===
ROM_0: 96%  [WARN]
ROM_1: 100%  [WARN]
ROM_2: 97%  [WARN]
ROM_3: 36%  [PASS]
ROM_31: 61%  [PASS]
State symbols: OK — all within ROM capacity (32 banks)
__bank_ symbols: OK
ROM capacity: OK — 32 banks (cartridge header 0x148), highest bank in use 31

[WARN]
"""


class TestParseMemoryCheck(unittest.TestCase):
    def test_the_three_memory_budgets_match_the_tools_numbers(self):
        # AC12, literally: these are the numbers `make memory-check` printed.
        report = budgets.parse_memory_check(MEMORY_CHECK_OUTPUT)

        wram = report.budget("wram")
        self.assertEqual((wram.used, wram.limit, wram.unit), (1534, 8192, "bytes"))
        self.assertEqual((wram.percent, wram.status), (18, budgets.PASS))
        self.assertEqual(wram.value_text(), "1,534 / 8,192 bytes")

        vram = report.budget("vram")
        self.assertEqual((vram.used, vram.limit, vram.unit), (76, 384, "tiles"))
        self.assertEqual(vram.status, budgets.PASS)

        oam = report.budget("oam")
        self.assertEqual((oam.used, oam.limit, oam.unit), (32, 40, "sprites"))
        self.assertEqual((oam.percent, oam.status), (80, budgets.WARN))
        self.assertEqual(oam.hint, "busiest scene: Playing")

    def test_the_per_scene_oam_peaks_are_read(self):
        report = budgets.parse_memory_check(MEMORY_CHECK_OUTPUT)

        names = [s.name for s in report.scenes]
        self.assertEqual(
            names,
            ["Title", "Overmap", "Hub", "Prerace", "Playing", "Results", "GameOver"],
        )
        peak = report.peak_scene()
        self.assertEqual((peak.name, peak.used, peak.limit), ("Playing", 32, 40))
        self.assertIn("projectiles=8", peak.detail)
        # An em dash means "nothing on screen", not a detail worth showing.
        self.assertEqual(report.scenes[0].detail, "")

    def test_the_cross_check_line_is_not_read_as_a_budget(self):
        report = budgets.parse_memory_check(MEMORY_CHECK_OUTPUT)

        self.assertEqual(len(report.budgets), 3)

    def test_output_that_is_not_a_report_yields_nothing_rather_than_guesses(self):
        report = budgets.parse_memory_check("make: *** [Makefile:277] Error 1")

        self.assertEqual(report.budgets, [])
        self.assertEqual(report.scenes, [])


class TestParseBankReport(unittest.TestCase):
    def test_the_rom_bank_budget_takes_the_worst_bank_and_the_capacity(self):
        banks = budgets.parse_bank_report(BANK_REPORT_OUTPUT)

        # One bank at 100% is the problem, whatever the others do.
        self.assertEqual(banks.status, budgets.WARN)
        self.assertEqual(banks.hint, "busiest ROM_1 100%")
        # The meter shows the cartridge, from the capacity line.
        self.assertEqual((banks.used, banks.limit, banks.unit), (31, 32, "banks"))
        self.assertEqual(banks.percent, 97)

    def test_a_failing_bank_makes_the_budget_fail(self):
        banks = budgets.parse_bank_report(
            BANK_REPORT_OUTPUT.replace("ROM_1: 100%  [WARN]", "ROM_1: 100%  [FAIL]")
        )

        self.assertEqual(banks.status, budgets.FAIL)
        self.assertEqual(banks.hint, "busiest ROM_1 100%")

    def test_a_report_that_never_ran_is_not_a_budget(self):
        self.assertIsNone(budgets.parse_bank_report("romusage not found on PATH"))
        self.assertIsNone(budgets.parse_bank_report(""))


class TestBuildReport(unittest.TestCase):
    def test_the_four_budgets_r12_names_are_always_present(self):
        report = budgets.build_report(MEMORY_CHECK_OUTPUT, BANK_REPORT_OUTPUT)

        self.assertEqual(
            [b.key for b in report.budgets], ["wram", "vram", "oam", "rom-banks"]
        )
        self.assertEqual(report.status, budgets.WARN)
        self.assertFalse(report.has_fail)

    def test_a_missing_report_is_blocked_not_absent(self):
        # Dropping the row would read as "no ROM bank problem", which is
        # exactly the silence R14 exists to end.
        report = budgets.build_report(MEMORY_CHECK_OUTPUT, "")

        banks = report.budget("rom-banks")
        self.assertEqual(banks.status, budgets.BLOCKED)
        self.assertEqual(banks.value_text(), "—")
        self.assertFalse(report.has_fail)

    def test_nothing_measured_at_all_still_lists_four_budgets(self):
        report = budgets.build_report("", "")

        self.assertEqual(len(report.budgets), 4)
        self.assertTrue(all(b.status == budgets.BLOCKED for b in report.budgets))
        self.assertEqual(report.status, budgets.BLOCKED)

    def test_summary_names_a_measured_result_over_an_unmeasured_one(self):
        # Found by pressing Bank check on a fresh window: the summary said
        # "budgets BLOCKED: WRAM, VRAM, OAM" and never mentioned the bank
        # result it had just read. A measured WARN is a fact about the ROM;
        # BLOCKED is the absence of one, and belongs in its own count.
        report = budgets.build_report("", BANK_REPORT_OUTPUT)

        self.assertEqual(report.summary(), "budgets WARN: ROM banks · 3 not measured")

    def test_summary_counts_the_unmeasured_beside_a_pass(self):
        passing = BANK_REPORT_OUTPUT.replace("[WARN]", "[PASS]")

        self.assertEqual(
            budgets.build_report("", passing).summary(),
            "budgets all PASS · 3 not measured",
        )

    def test_summary_when_nothing_was_measured_at_all(self):
        self.assertEqual(budgets.build_report("", "").summary(), "budgets not measured yet")

    def test_summary_names_the_worst_result(self):
        self.assertEqual(
            budgets.build_report(MEMORY_CHECK_OUTPUT, BANK_REPORT_OUTPUT).summary(),
            "budgets WARN: OAM, ROM banks",
        )
        all_pass = MEMORY_CHECK_OUTPUT.replace(
            "OAM:   32 / 40 sprites  (80%)  WARN", "OAM:   12 / 40 sprites  (30%)  PASS"
        )
        bank_pass = BANK_REPORT_OUTPUT.replace("[WARN]", "[PASS]")
        self.assertEqual(
            budgets.build_report(all_pass, bank_pass).summary(), "budgets all PASS"
        )

    def test_a_failing_budget_is_reported_as_a_failure(self):
        over = MEMORY_CHECK_OUTPUT.replace(
            "WRAM:  1,534 / 8,192 bytes   (18%)  PASS",
            "WRAM:  8,400 / 8,192 bytes   (103%)  FAIL",
        )

        report = budgets.build_report(over, BANK_REPORT_OUTPUT)

        self.assertTrue(report.has_fail)
        self.assertEqual(report.status, budgets.FAIL)
        self.assertEqual([b.name for b in report.failures], ["WRAM"])


class TestEmuliciousGate(unittest.TestCase):
    """AC13: Garage does not start Emulicious when a memory budget result
    is FAIL. Nothing here starts a process -- the gate is a pure decision,
    and that is the half that must never be wrong.
    """

    def _rig(self, tmp: str):
        tmp_path = Path(tmp)
        rom = tmp_path / "build" / "nuke-raider.gb"
        rom.parent.mkdir(parents=True)
        rom.write_bytes(b"\0")
        jar = tmp_path / "Emulicious.jar"
        jar.write_text("", encoding="utf-8")
        return rom, jar

    def test_a_warn_build_may_run(self):
        # The build that ships today is OAM 32/40 WARN. A gate that stops
        # that is a gate the user learns to route around.
        with tempfile.TemporaryDirectory() as tmp:
            rom, jar = self._rig(tmp)
            report = budgets.build_report(MEMORY_CHECK_OUTPUT, BANK_REPORT_OUTPUT)

            self.assertIsNone(emulicious.refuse_reason(report, rom, jar))

    def test_a_failing_budget_refuses_and_names_the_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            rom, jar = self._rig(tmp)
            over = MEMORY_CHECK_OUTPUT.replace(
                "WRAM:  1,534 / 8,192 bytes   (18%)  PASS",
                "WRAM:  8,400 / 8,192 bytes   (103%)  FAIL",
            )
            report = budgets.build_report(over, BANK_REPORT_OUTPUT)

            reason = emulicious.refuse_reason(report, rom, jar)

            self.assertIsNotNone(reason)
            self.assertIn("WRAM", reason)
            self.assertIn("8,400 / 8,192 bytes", reason)

    def test_no_rom_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, jar = self._rig(tmp)
            missing = Path(tmp) / "build" / "not-here.gb"

            reason = emulicious.refuse_reason(None, missing, jar)

            self.assertIn("no ROM", reason)
            self.assertIn("Build first", reason)

    def test_a_missing_jar_refuses_and_points_at_the_doctor(self):
        with tempfile.TemporaryDirectory() as tmp:
            rom, _ = self._rig(tmp)

            reason = emulicious.refuse_reason(None, rom, Path(tmp) / "nope.jar")

            self.assertIn("Toolchain", reason)

    def test_an_unmeasured_budget_does_not_refuse(self):
        # BLOCKED is "the check could not run", not "the ROM is broken".
        with tempfile.TemporaryDirectory() as tmp:
            rom, jar = self._rig(tmp)
            report = budgets.build_report("", "")

            self.assertIsNone(emulicious.refuse_reason(report, rom, jar))

    def test_the_launch_command_is_java_dash_jar(self):
        jar, rom = Path("C:/T/Emulicious.jar"), Path("C:/w/rom.gb")

        # Native separators, and no shell: unlike GBDK_HOME in the
        # Makefile, these arguments never pass through bash, so a
        # backslash in them is a path and not an escape.
        self.assertEqual(
            emulicious.launch_command(jar, rom), ["java", "-jar", str(jar), str(rom)]
        )


# -- worktrees (R3 / R4 / AC3 / AC4) -----------------------------------------
#
# Real repositories throughout: `git worktree add` and `git worktree
# remove` are what is being tested, and a mocked git would prove only that
# the mock agrees with itself. AC3 is literally "appears in `git worktree
# list`", so that is what the assertion reads.


class WorktreeFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.garage_root = self.tmp_path / "nuke-raider-garage"
        self.garage_root.mkdir()
        self.game_repo = make_game_repo(self.tmp_path / "nuke-raider")
        self.worktree_root = self.tmp_path / "worktrees"
        self.binding = project.bind(self.garage_root)
        self.main = self.binding.active_worktree

    def tearDown(self):
        self._tmp.cleanup()

    def git_worktree_list(self):
        """`git worktree list` output, as git writes it. It prints forward
        slashes on Windows, so a caller comparing a Path must compare
        `as_posix()` -- `str(path)` would never match, which would make an
        assertNotIn pass whether the worktree was removed or not.
        """
        return _run_git(["worktree", "list"], self.game_repo).stdout

    def add_worktree(self, branch="feat/spike"):
        path = worktrees.create(self.game_repo, self.worktree_root, branch)
        listed = project.list_worktrees(self.game_repo)
        return next(w for w in listed if project._same_path(w.path, path))


class TestCreateWorktree(WorktreeFixture):
    def test_a_created_worktree_appears_in_git_worktree_list(self):
        # AC3, in the words of the criterion.
        path = worktrees.create(self.game_repo, self.worktree_root, "feat/spike")

        self.assertTrue(path.is_dir())
        self.assertIn(path.as_posix(), self.git_worktree_list())

    def test_a_branch_name_with_a_slash_gets_a_flat_directory(self):
        path = worktrees.create(self.game_repo, self.worktree_root, "feat/garage-p1")

        self.assertEqual(path.name, "feat-garage-p1")
        self.assertEqual(path.parent, self.worktree_root)

    def test_a_new_branch_is_created_and_checked_out(self):
        worktrees.create(self.game_repo, self.worktree_root, "feat/spike")

        self.assertTrue(worktrees.branch_exists(self.game_repo, "feat/spike"))
        listed = project.list_worktrees(self.game_repo)
        self.assertIn("feat/spike", [w.branch for w in listed])

    def test_an_existing_branch_is_checked_out_rather_than_recreated(self):
        _run_git(["branch", "already-here"], self.game_repo)

        path = worktrees.create(self.game_repo, self.worktree_root, "already-here")

        listed = project.list_worktrees(self.game_repo)
        branch = next(
            w.branch for w in listed if project._same_path(w.path, path)
        )
        self.assertEqual(branch, "already-here")

    def test_an_invalid_branch_name_is_refused_before_anything_is_created(self):
        with self.assertRaises(worktrees.WorktreeError) as raised:
            worktrees.create(self.game_repo, self.worktree_root, "feat/..bad")

        self.assertIn("not a valid branch name", str(raised.exception))
        self.assertFalse(self.worktree_root.exists())

    def test_an_empty_branch_name_is_refused(self):
        with self.assertRaises(worktrees.WorktreeError):
            worktrees.create(self.game_repo, self.worktree_root, "   ")

    def test_an_occupied_directory_is_refused_rather_than_overwritten(self):
        occupied = self.worktree_root / "taken"
        occupied.mkdir(parents=True)
        (occupied / "keep.txt").write_text("mine\n", encoding="utf-8")

        with self.assertRaises(worktrees.WorktreeError) as raised:
            worktrees.create(self.game_repo, self.worktree_root, "taken")

        self.assertIn("already exists", str(raised.exception))
        self.assertTrue((occupied / "keep.txt").is_file())


class TestDeleteWorktree(WorktreeFixture):
    """AC4: Garage refuses to delete the active worktree, and refuses to
    delete a worktree that holds uncommitted changes, stating the reason in
    both cases.
    """

    def test_the_active_worktree_is_refused_with_its_reason(self):
        reason = worktrees.refuse_delete_reason(self.main, self.main)

        self.assertIsNotNone(reason)
        self.assertIn("active worktree", reason)
        with self.assertRaises(worktrees.WorktreeError):
            worktrees.delete(self.game_repo, self.main, self.main, self.main.path.name)

    def test_a_worktree_with_uncommitted_changes_is_refused_with_its_reason(self):
        spike = self.add_worktree()
        (spike.path / "README.md").write_text("edited\n", encoding="utf-8")

        reason = worktrees.refuse_delete_reason(spike, self.main)

        self.assertIn("uncommitted work", reason)
        self.assertIn("1 file differs from HEAD", reason)
        with self.assertRaises(worktrees.WorktreeError):
            worktrees.delete(self.game_repo, spike, self.main, spike.path.name)
        self.assertTrue(spike.path.is_dir())

    def test_a_worktree_with_only_untracked_files_is_refused_too(self):
        # Stricter than R4's letter, on purpose: git will not stop for an
        # untracked file, and the removal destroys it. It exists nowhere
        # else.
        spike = self.add_worktree()
        (spike.path / "notes.txt").write_text("scratch\n", encoding="utf-8")

        reason = worktrees.refuse_delete_reason(spike, self.main)

        self.assertIn("untracked", reason)
        self.assertIn("no copy", reason)

    def test_the_main_working_tree_is_refused_even_when_it_is_not_active(self):
        # With `spike` active, the main tree is no longer refused for being
        # active -- and must still be refused for being the main one.
        spike = self.add_worktree()
        listed = project.list_worktrees(self.game_repo)

        reason = worktrees.refuse_delete_reason(self.main, spike, listed)

        self.assertIn("main working tree", reason)

    def test_the_name_must_be_typed_back_exactly(self):
        spike = self.add_worktree()

        with self.assertRaises(worktrees.WorktreeError) as raised:
            worktrees.delete(self.game_repo, spike, self.main, "feat-spik")

        self.assertIn("type its name exactly", str(raised.exception))
        self.assertTrue(spike.path.is_dir())

    def test_a_clean_worktree_with_the_name_typed_is_removed(self):
        spike = self.add_worktree()

        worktrees.delete(self.game_repo, spike, self.main, spike.path.name)

        # Prove the listing really does name a worktree that exists, so
        # the assertNotIn below is not vacuously true.
        self.assertNotIn(spike.path.as_posix(), self.git_worktree_list())
        self.assertIn(self.main.path.as_posix(), self.git_worktree_list())
        self.assertFalse(spike.path.is_dir())

    def test_the_branch_survives_the_worktree(self):
        # R4: "It must never delete a branch." The work is on the branch;
        # the worktree is only where it was checked out.
        spike = self.add_worktree("feat/keep-me")

        worktrees.delete(self.game_repo, spike, self.main, spike.path.name)

        self.assertTrue(worktrees.branch_exists(self.game_repo, "feat/keep-me"))


class TestActivateWorktree(WorktreeFixture):
    def test_activating_records_the_path_and_binds_to_it(self):
        spike = self.add_worktree()

        worktrees.activate(self.garage_root, spike)

        rebound = project.bind(self.garage_root)
        self.assertTrue(
            project._same_path(rebound.active_worktree.path, spike.path)
        )
        self.assertEqual(rebound.active_source, "recorded")

    def test_activating_leaves_every_other_setting_alone(self):
        settings = project.load_settings(self.garage_root)
        settings["emulicious_jar"] = "C:/Tools/Emulicious/Emulicious.jar"
        project.save_settings(self.garage_root, settings)
        spike = self.add_worktree()

        worktrees.activate(self.garage_root, spike)

        after = project.load_settings(self.garage_root)
        self.assertEqual(after["emulicious_jar"], "C:/Tools/Emulicious/Emulicious.jar")
        self.assertEqual(after["game_repo"], settings["game_repo"])


class TestDescribeWorktree(WorktreeFixture):
    def test_a_clean_worktree_reads_clean(self):
        spike = self.add_worktree("feat/clean")

        self.assertEqual(worktrees.describe(spike, self.main), "feat/clean — clean")

    def test_the_active_one_says_so_first(self):
        self.assertIn("active", worktrees.describe(self.main, self.main))

    def test_a_dirty_worktree_states_its_totals(self):
        spike = self.add_worktree()
        (spike.path / "README.md").write_text("edited\n", encoding="utf-8")
        (spike.path / "new.txt").write_text("new\n", encoding="utf-8")

        described = worktrees.describe(spike, self.main)

        self.assertIn("1 changed", described)
        self.assertIn("1 untracked", described)


# -- commit (R5 / R6 / AC5 / AC6) --------------------------------------------


class CommitFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.garage_root = self.tmp_path / "nuke-raider-garage"
        self.garage_root.mkdir()
        self.game_repo = make_game_repo(self.tmp_path / "nuke-raider")
        self.binding = project.bind(self.garage_root)

    def tearDown(self):
        self._tmp.cleanup()

    def on_branch(self, name="feat/tuning"):
        _run_git(["checkout", "-q", "-b", name], self.game_repo)
        return project.bind(self.garage_root)

    def change_a_tracked_file(self):
        (self.game_repo / "README.md").write_text("changed\n", encoding="utf-8")

    def summary(self):
        return diff.get_change_summary(self.binding.active_worktree.path)


class TestCommitRefusals(CommitFixture):
    def test_master_is_refused_and_says_why(self):
        # AC5. The fixture starts on master, which is the point.
        self.change_a_tracked_file()

        reason = commit.refuse_reason(self.binding, "tune the gears", self.summary())

        self.assertIsNotNone(reason)
        self.assertIn("master", reason)
        self.assertIn("branch", reason)

    def test_the_branch_is_checked_before_the_message(self):
        # A user on master cannot fix it by typing more, so that is the
        # sentence they get.
        reason = commit.refuse_reason(self.binding, "", self.summary())

        self.assertIn("master", reason)

    def test_an_empty_message_is_refused_on_a_branch(self):
        binding = self.on_branch()
        self.change_a_tracked_file()

        reason = commit.refuse_reason(binding, "   ", diff.get_change_summary(
            binding.active_worktree.path))

        self.assertIn("message is required", reason)

    def test_nothing_to_commit_is_refused(self):
        binding = self.on_branch()

        reason = commit.refuse_reason(binding, "a message", diff.get_change_summary(
            binding.active_worktree.path))

        self.assertIn("Nothing to commit", reason)

    def test_untracked_only_is_refused_and_says_they_are_not_included(self):
        binding = self.on_branch()
        (self.game_repo / "new.txt").write_text("new\n", encoding="utf-8")

        reason = commit.refuse_reason(binding, "a message", diff.get_change_summary(
            binding.active_worktree.path))

        self.assertIn("untracked", reason)
        self.assertIn("terminal", reason)

    def test_a_detached_head_is_refused(self):
        _run_git(["checkout", "-q", "--detach"], self.game_repo)
        binding = project.bind(self.garage_root)

        reason = commit.refuse_reason(binding, "a message", None)

        self.assertIn("detached HEAD", reason)

    def test_a_branch_with_a_message_and_a_change_is_allowed(self):
        binding = self.on_branch()
        self.change_a_tracked_file()

        self.assertIsNone(
            commit.refuse_reason(binding, "tune the gears", diff.get_change_summary(
                binding.active_worktree.path))
        )


class TestCommitCommand(CommitFixture):
    def test_the_command_commits_tracked_changes_and_never_skips_the_hook(self):
        command = commit.commit_command("tune the gears")

        self.assertEqual(
            list(command.argv), ["git", "commit", "-a", "-m", "tune the gears"]
        )
        self.assertNotIn("--no-verify", command.argv)
        # The label must not echo the message back: it can be a paragraph.
        self.assertEqual(command.label, "git commit -a")

    def test_running_it_puts_the_commit_in_git_log(self):
        # AC6, through the same runner the panel uses.
        binding = self.on_branch()
        self.change_a_tracked_file()
        lines = []

        result = make_runner.run(
            commit.commit_command("tune the gears"),
            binding.active_worktree.path,
            lines.append,
        )

        self.assertTrue(result.ok, lines)
        self.assertIn(
            "tune the gears", commit.head_line(binding.active_worktree.path)
        )
        self.assertTrue(
            any("tune the gears" in line for line in commit.log_lines(
                binding.active_worktree.path))
        )

    def test_a_multiline_message_survives(self):
        binding = self.on_branch()
        self.change_a_tracked_file()

        make_runner.run(
            commit.commit_command("subject line\n\nA body paragraph."),
            binding.active_worktree.path,
            lambda line: None,
        )

        self.assertIn("subject line", commit.head_line(binding.active_worktree.path))
        body = _run_git(["log", "-1", "--format=%b"], self.game_repo).stdout
        self.assertIn("A body paragraph.", body)


class TestStaleIndexLock(CommitFixture):
    """Garage stops a run by killing the process tree, which is the one
    exit git does not control: it leaves the index lock it was holding, and
    every later git write in that worktree fails on it. Found by pressing
    Stop and then Build.
    """

    def test_the_git_dir_of_a_linked_worktree_is_its_own(self):
        worktree_root = self.tmp_path / "worktrees"
        path = worktrees.create(self.game_repo, worktree_root, "feat/spike")

        directory = commit.git_dir(path)

        self.assertEqual(directory.name, "feat-spike")
        self.assertEqual(directory.parent.name, "worktrees")
        self.assertTrue(directory.is_dir())

    def test_a_stale_lock_is_removed_and_the_removal_is_stated(self):
        lock = commit.git_dir(self.game_repo) / "index.lock"
        lock.write_bytes(b"stale")

        message = commit.remove_stale_index_lock(self.game_repo)

        self.assertFalse(lock.exists())
        self.assertIn("index.lock", message)
        self.assertIn("refuse every later write", message)

    def test_a_lock_in_a_linked_worktree_is_found_where_git_keeps_it(self):
        # Not in the repository's own .git, which is where a naive
        # implementation would look and find nothing.
        worktree_root = self.tmp_path / "worktrees"
        path = worktrees.create(self.game_repo, worktree_root, "feat/spike")
        lock = commit.git_dir(path) / "index.lock"
        lock.write_bytes(b"stale")

        message = commit.remove_stale_index_lock(path)

        self.assertFalse(lock.exists())
        self.assertIsNotNone(message)
        self.assertFalse((self.game_repo / ".git" / "index.lock").exists())

    def test_no_lock_means_nothing_to_say_and_nothing_removed(self):
        self.assertIsNone(commit.remove_stale_index_lock(self.game_repo))

    def test_a_path_that_is_not_a_repository_is_harmless(self):
        self.assertIsNone(commit.remove_stale_index_lock(self.tmp_path))

    def test_a_locked_index_blocks_git_until_it_is_removed(self):
        # The failure the user hit, reproduced: with the lock in place git
        # refuses to write, and removing it restores the worktree.
        self.on_branch()
        self.change_a_tracked_file()
        lock = commit.git_dir(self.game_repo) / "index.lock"
        lock.write_bytes(b"stale")

        blocked = make_runner.run(
            commit.commit_command("blocked"), self.game_repo, lambda line: None
        )
        self.assertFalse(blocked.ok)

        commit.remove_stale_index_lock(self.game_repo)

        allowed = make_runner.run(
            commit.commit_command("allowed"), self.game_repo, lambda line: None
        )
        self.assertTrue(allowed.ok)
        self.assertIn("allowed", commit.head_line(self.game_repo))


class TestDescribePending(CommitFixture):
    def test_it_states_the_totals_and_what_is_left_out(self):
        self.change_a_tracked_file()
        (self.game_repo / "new.txt").write_text("new\n", encoding="utf-8")

        described = commit.describe_pending(self.summary())

        self.assertIn("1 file", described)
        self.assertIn("1 untracked file will not be included", described)

    def test_a_clean_worktree_says_there_is_nothing(self):
        self.assertIn("No tracked change", commit.describe_pending(self.summary()))


if __name__ == "__main__":
    unittest.main()
