import unittest

from swarm_supervisor import cli


class TestArgumentDispatch(unittest.TestCase):
    """
    Regression test for a real bug found while testing this rewrite:
    argparse's add_subparsers() combined with a free-form `idea` positional
    made `supervisor "some idea"` crash with "invalid choice" any time the
    idea string wasn't literally one of the subcommand names. Confirmed
    present in the original v1 code too. cli.py now dispatches manually on
    the first token instead of relying on argparse subparsers for this.
    """

    def test_freeform_idea_does_not_collide_with_subcommand_parsing(self):
        for idea in ["add caching", "init something new", "config the retry logic",
                     "history of this endpoint", "verify the email", "mcp server support"]:
            self.assertNotIn(idea, cli._SUBCOMMAND_NAMES)
            args = cli._build_main_parser().parse_args([idea])
            self.assertEqual(args.idea, idea)

    def test_known_subcommands_dispatch_to_their_own_parser(self):
        args = cli._build_init_parser().parse_args(["--reset"])
        self.assertTrue(args.reset)

        args = cli._build_verify_parser().parse_args(["--tasks", "plan.json"])
        self.assertEqual(args.tasks, "plan.json")

        args = cli._build_history_parser().parse_args(["--n", "3"])
        self.assertEqual(args.n, 3)

    def test_idea_plus_project_dir_and_flags_parse_together(self):
        args = cli._build_main_parser().parse_args(["add caching", "./proj", "--yes", "--iterate"])
        self.assertEqual(args.idea, "add caching")
        self.assertEqual(args.project_dir_pos, "./proj")
        self.assertTrue(args.yes)
        self.assertTrue(args.iterate)

    def test_no_args_is_valid_and_prompts_later(self):
        args = cli._build_main_parser().parse_args([])
        self.assertIsNone(args.idea)


if __name__ == "__main__":
    unittest.main()
