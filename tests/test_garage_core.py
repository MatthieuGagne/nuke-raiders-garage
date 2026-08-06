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
from pathlib import Path

# Make the repository root importable regardless of the test runner's cwd.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.garage.core import config_io, project  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
