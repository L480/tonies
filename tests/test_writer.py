import unittest
from pathlib import Path

from tonie_writer.nfcfile import parse_nfc_file
from tonie_writer.proxmark import Pm3Result
from tonie_writer import writer
from tonie_writer.writer import WriteOptions

FIXTURES = Path(__file__).parent / "fixtures" / "nfc"

EXPECTED_ZUMA_DRY_RUN = [
    "hf 15 wrbl --ua -b 0 -d D93FEB0A",
    "hf 15 wrbl --ua -b 1 -d DB3D4447",
    "hf 15 wrbl --ua -b 2 -d 8BE48549",
    "hf 15 wrbl --ua -b 3 -d DB4E04E1",
    "hf 15 wrbl --ua -b 4 -d 939A226B",
    "hf 15 wrbl --ua -b 5 -d 2FB3911D",
    "hf 15 wrbl --ua -b 6 -d 982C1C55",
    "hf 15 wrbl --ua -b 7 -d 00F20064",
    "hf 15 raw -2 -akrc -d 02E00941500304E0",
    "hf 15 raw -2 -krc -d 02E009401D363020",
]


class FakeRunner:
    """Records every call and returns scripted Pm3Results in order (or a default)."""

    def __init__(self, default=Pm3Result(stdout="", stderr="", returncode=0), responses=None):
        self.default = default
        self.responses = list(responses or [])
        self.calls: list[list[str]] = []

    def __call__(self, commands, port=None, timeout=60, pm3_bin=None):
        self.calls.append(commands)
        if self.responses:
            return self.responses.pop(0)
        return self.default


class TestPlanWriteCommands(unittest.TestCase):
    """Contract test: --dry-run must produce exactly this list, in this order,
    for the Zuma fixture. Blocks first, then the two safe UID frames. No csetuid."""

    def test_dry_run_command_list_for_zuma(self):
        tag = parse_nfc_file(FIXTURES / "Zuma.nfc")
        commands = writer.plan_write_commands(tag, WriteOptions())
        self.assertEqual(commands, EXPECTED_ZUMA_DRY_RUN)

    def test_uid_only_skips_blocks(self):
        tag = parse_nfc_file(FIXTURES / "Zuma.nfc")
        commands = writer.plan_write_commands(tag, WriteOptions(uid_only=True))
        self.assertEqual(commands, EXPECTED_ZUMA_DRY_RUN[8:])

    def test_blocks_only_skips_uid(self):
        tag = parse_nfc_file(FIXTURES / "Zuma.nfc")
        commands = writer.plan_write_commands(tag, WriteOptions(blocks_only=True))
        self.assertEqual(commands, EXPECTED_ZUMA_DRY_RUN[:8])

    def test_no_csetuid_anywhere(self):
        tag = parse_nfc_file(FIXTURES / "Zuma.nfc")
        commands = writer.plan_write_commands(tag, WriteOptions())
        for cmd in commands:
            self.assertNotIn("csetuid", cmd)


class TestWriteBlocks(unittest.TestCase):
    def test_batch_success_marks_all_ok(self):
        tag = parse_nfc_file(FIXTURES / "Zuma.nfc")
        runner = FakeRunner()
        results = writer.write_blocks(tag, WriteOptions(), run_fn=runner)
        self.assertTrue(all(r.ok for r in results))
        self.assertEqual(len(runner.calls), 1)  # single batched invocation

    def test_batch_failure_falls_back_per_block(self):
        tag = parse_nfc_file(FIXTURES / "Zuma.nfc")
        runner = FakeRunner(responses=[Pm3Result("", "", 1)] + [Pm3Result("", "", 0)] * 8)
        results = writer.write_blocks(tag, WriteOptions(retries=2), run_fn=runner)
        self.assertTrue(all(r.ok for r in results))
        self.assertEqual(len(runner.calls), 9)  # 1 batch + 8 individual


class TestWriteUid(unittest.TestCase):
    def test_success_on_first_attempt(self):
        tag = parse_nfc_file(FIXTURES / "Zuma.nfc")
        responses = [
            Pm3Result("", "", 0),  # both UID frames, one session
            Pm3Result("[+] UID.................. E0 04 03 50 20 30 36 1D", "", 0),  # info
        ]
        runner = FakeRunner(responses=responses)
        result = writer.write_uid(tag, WriteOptions(), run_fn=runner, sleep_fn=lambda s: None)
        self.assertTrue(result.ok)
        self.assertEqual(result.read_back_uid, tag.uid)

    def test_only_the_first_frame_activates_the_field(self):
        """`-a` re-inits the reader (field off/on), which drops the pending
        first half — observed on real hardware as UID FF FF FF FF <last4>.
        So: `-a` on frame 1 only, `-k` on both, one pm3 session."""
        first, last = writer.proxmark.build_uid_frames(bytes.fromhex("E00403502030361D"))
        self.assertIn(" -akrc ", first)
        self.assertIn(" -krc ", last)
        self.assertNotIn("-akrc", last)

    def test_both_frames_share_one_session(self):
        """The field must stay up between the two halves — one pm3 call, in
        vendor order (0x41 first)."""
        tag = parse_nfc_file(FIXTURES / "Zuma.nfc")
        runner = FakeRunner(
            responses=[
                Pm3Result("", "", 0),
                Pm3Result("[+] UID.................. E0 04 03 50 20 30 36 1D", "", 0),
            ]
        )
        writer.write_uid(tag, WriteOptions(), run_fn=runner, sleep_fn=lambda s: None)
        self.assertEqual(
            runner.calls[0],
            [
                "hf 15 raw -2 -akrc -d 02E00941500304E0",
                "hf 15 raw -2 -krc -d 02E009401D363020",
            ],
        )

    def test_failure_when_uid_never_matches(self):
        tag = parse_nfc_file(FIXTURES / "Zuma.nfc")
        info_unchanged = Pm3Result("[+] UID.................. E0 04 02 11 22 33 44 55", "", 0)
        runner = FakeRunner(default=info_unchanged)
        result = writer.write_uid(tag, WriteOptions(), run_fn=runner, sleep_fn=lambda s: None)
        self.assertFalse(result.ok)
        self.assertEqual(result.attempts, 3)


class TestClassifyUidFailure(unittest.TestCase):
    TARGET = "E00403501C9FE7F1"

    def test_half_written_first_is_the_observed_field_failure(self):
        """Real hardware, `-a` on both frames: the 0x41 half is lost and the
        tag reads FF FF FF FF followed by the correct last four bytes."""
        self.assertEqual(
            writer.classify_uid_failure(self.TARGET, "FFFFFFFF1C9FE7F1"),
            "half-written-first",
        )

    def test_half_written_last(self):
        self.assertEqual(
            writer.classify_uid_failure(self.TARGET, "E0040350FFFFFFFF"),
            "half-written-last",
        )

    def test_unchanged_uid_is_not_mistaken_for_a_half_write(self):
        """Every SLIX-L UID starts with E0 04 03 50, so the shared prefix must
        not read as 'first half written'."""
        self.assertEqual(
            writer.classify_uid_failure(
                self.TARGET, "E004035011223344", previous_uid="E004035011223344"
            ),
            "unchanged",
        )

    def test_unknown_when_nothing_read_back(self):
        self.assertEqual(writer.classify_uid_failure(self.TARGET, None), "unknown")


class TestVerify(unittest.TestCase):
    def test_all_match(self):
        tag = parse_nfc_file(FIXTURES / "Zuma.nfc")

        def run_fn(commands, port=None, timeout=60, pm3_bin=None):
            cmd = commands[0]
            if cmd == "hf 15 info":
                return Pm3Result("[+] UID.................. E0 04 03 50 20 30 36 1D", "", 0)
            block = int(cmd.split("-b ")[1].split()[0])
            data = tag.blocks[block]
            spaced = " ".join(data[i : i + 2] for i in range(0, 8, 2))
            return Pm3Result(f"[+] {block:02d} | {spaced}", "", 0)

        result = writer.verify(tag, WriteOptions(), run_fn=run_fn)
        self.assertTrue(result.uid_ok)
        self.assertTrue(all(result.block_ok.values()))

    def test_unparseable_output_is_inconclusive_not_mismatch(self):
        tag = parse_nfc_file(FIXTURES / "Zuma.nfc")
        runner = FakeRunner(default=Pm3Result("connection reset", "", 1))
        result = writer.verify(tag, WriteOptions(), run_fn=runner)
        self.assertIsNone(result.uid_ok)
        self.assertTrue(all(v is None for v in result.block_ok.values()))

    def test_mismatch_detected(self):
        tag = parse_nfc_file(FIXTURES / "Zuma.nfc")

        def run_fn(commands, port=None, timeout=60, pm3_bin=None):
            cmd = commands[0]
            if cmd == "hf 15 info":
                return Pm3Result("[+] UID.................. E0 04 03 50 20 30 36 1D", "", 0)
            block = int(cmd.split("-b ")[1].split()[0])
            return Pm3Result(f"[+] {block:02d} | FF FF FF FF", "", 0)

        result = writer.verify(tag, WriteOptions(), run_fn=run_fn)
        self.assertFalse(all(v for v in result.block_ok.values() if v is not None))


class TestWriteReportOk(unittest.TestCase):
    def test_ok_true_when_everything_matches(self):
        tag = parse_nfc_file(FIXTURES / "Zuma.nfc")
        report = writer.WriteReport(
            tag=tag,
            block_results=[writer.BlockWriteResult(b, True, 1) for b in range(8)],
            uid_result=writer.UidWriteResult(True, tag.uid, 1),
            verify_result=writer.VerifyResult(uid_ok=True, block_ok={b: True for b in range(8)}),
        )
        self.assertTrue(report.ok)

    def test_ok_false_on_uid_write_failure(self):
        tag = parse_nfc_file(FIXTURES / "Zuma.nfc")
        report = writer.WriteReport(
            tag=tag,
            block_results=[writer.BlockWriteResult(b, True, 1) for b in range(8)],
            uid_result=writer.UidWriteResult(False, "E0040211223344AA", 3),
        )
        self.assertFalse(report.ok)

    def test_ok_true_when_verify_inconclusive(self):
        tag = parse_nfc_file(FIXTURES / "Zuma.nfc")
        report = writer.WriteReport(
            tag=tag,
            block_results=[writer.BlockWriteResult(b, True, 1) for b in range(8)],
            uid_result=writer.UidWriteResult(True, tag.uid, 1),
            verify_result=writer.VerifyResult(uid_ok=None, block_ok={b: None for b in range(8)}),
        )
        self.assertTrue(report.ok)


if __name__ == "__main__":
    unittest.main()
