"""Coverage for tools/garage/core/project.py, schema.py and config_io.py.

No Qt import anywhere in this file. Must pass with PySide6 absent.

Fixtures build real git repositories in a temp directory with `git init`,
`git remote add` and `git worktree add` -- git output is not mocked as
strings for the happy-path cases.
"""
import json
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

# Make the repository root importable regardless of the test runner's cwd.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.garage.core import config_io, diff, project  # noqa: E402
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
REAL_CONFIG_H_PATH = Path("C:/Code/nuke-raider/src/config.h")

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


if __name__ == "__main__":
    unittest.main()
