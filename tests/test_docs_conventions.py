"""CLAUDE.md carries the shared-board conventions (#25 R1 / AC4).

No Qt import and no game-repo binding: this file runs under the default
`make test` target, which must pass with PySide6 absent.
"""
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

GAME_CLAUDE_MD_URL = (
    "https://github.com/MatthieuGagne/gmb-nuke-raider/blob/master/CLAUDE.md"
)

# One entry per operational must R1 enumerates. Each value is the shortest
# string that cannot land in the file by accident.
REQUIRED = {
    "title prefix feat": "`feat:`",
    "title prefix fix": "`fix:`",
    "title prefix bug": "`bug:`",
    "title prefix chore": "`chore:`",
    "title prefix docs": "`docs:`",
    "board field Type": "`Type`",
    "board field Status": "`Status`",
    "the shared board id": "PVT_kwHOAv4a5M4BepB5",
    "label prd": "`prd`",
    "label epic": "`epic`",
    "label adr": "`adr`",
    "label log": "`log`",
    "label plan": "`plan`",
    "label idea": "`idea`",
    "native sub-issue wiring": "sub_issues",
    "routing rule": "whose tracked files it changes",
}


class TestIssuesAndDocumentsSection(unittest.TestCase):
    def setUp(self):
        self.assertTrue(
            CLAUDE_MD.is_file(), "CLAUDE.md is missing from the repository root"
        )
        self.text = CLAUDE_MD.read_text(encoding="utf-8")

    def test_has_the_issues_and_documents_heading(self):
        self.assertIn("## Issues & documents", self.text)

    def test_names_the_game_repos_claude_md_as_canonical(self):
        self.assertIn(GAME_CLAUDE_MD_URL, self.text)

    def test_restates_every_operational_must(self):
        for must, needle in REQUIRED.items():
            with self.subTest(must=must):
                self.assertIn(needle, self.text)


if __name__ == "__main__":
    unittest.main()
