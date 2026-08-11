import unittest

from tonie_writer.proxmark import (
    build_rdbl_command,
    build_uid_frames,
    build_wrbl_command,
    parse_info_uid,
    parse_rdbl_data,
    strip_ansi,
    validate_block_hex,
    validate_block_number,
)

INFO_OUTPUT_SUCCESS = """\
[=] Starting standalone mode
[+] Searching for tag...
[+] ISO15693 tag found
[+] UID.................. E0 04 03 50 20 30 36 1D
[+] TYPE.................. NXP ICODE SLIX-L
[+] Reading tag memory...
"""

INFO_OUTPUT_GARBAGE = """\
[=] Starting standalone mode
[-] no tag found
"""

RDBL_OUTPUT_SUCCESS = """\
[+] Reading memory from tag...
[+] blk | data
[+] ---+-------------
[+]  00 | D9 3F EB 0A
"""

RDBL_OUTPUT_GARBAGE = "connection reset by peer\n"


class TestBuildUidFrames(unittest.TestCase):
    def test_known_vector_from_plan(self):
        uid = bytes.fromhex("E00403502030361D")
        first, last = build_uid_frames(uid)
        self.assertEqual(first, "hf 15 raw -2 -akrc -d 02E00941500304E0")
        self.assertEqual(last, "hf 15 raw -2 -krc -d 02E009401D363020")

    def test_matches_vendor_documented_example(self):
        """The worked example on the rfidfriend.com instruction sheet:
        UID E0 04 03 50 12 34 56 78, step 1 then step 2."""
        first, last = build_uid_frames(bytes.fromhex("E004035012345678"))
        self.assertEqual(first, "hf 15 raw -2 -akrc -d 02E00941500304E0")
        self.assertEqual(last, "hf 15 raw -2 -krc -d 02E0094078563412")

    def test_rejects_wrong_length(self):
        with self.assertRaises(ValueError):
            build_uid_frames(bytes.fromhex("E00403"))

    def test_never_mentions_csetuid(self):
        uid = bytes.fromhex("E00403502030361D")
        for frame in build_uid_frames(uid):
            self.assertNotIn("csetuid", frame)


class TestBuildCommands(unittest.TestCase):
    def test_wrbl_default_flags(self):
        self.assertEqual(build_wrbl_command(0, "d93feb0a"), "hf 15 wrbl --ua -b 0 -d D93FEB0A")

    def test_wrbl_option_flag(self):
        self.assertEqual(build_wrbl_command(7, "AABBCCDD", option=True), "hf 15 wrbl --ua -o -b 7 -d AABBCCDD")

    def test_wrbl_rejects_bad_block(self):
        with self.assertRaises(ValueError):
            build_wrbl_command(8, "AABBCCDD")

    def test_wrbl_rejects_bad_hex(self):
        with self.assertRaises(ValueError):
            build_wrbl_command(0, "ZZZZZZZZ")

    def test_rdbl_command(self):
        self.assertEqual(build_rdbl_command(3), "hf 15 rdbl --ua -b 3")

    def test_validate_block_number_bounds(self):
        validate_block_number(0)
        validate_block_number(7)
        with self.assertRaises(ValueError):
            validate_block_number(-1)
        with self.assertRaises(ValueError):
            validate_block_number(8)

    def test_validate_block_hex(self):
        self.assertEqual(validate_block_hex("aabbccdd"), "AABBCCDD")
        with self.assertRaises(ValueError):
            validate_block_hex("aabbcc")  # too short


class TestStripAnsi(unittest.TestCase):
    def test_strips_color_codes(self):
        self.assertEqual(strip_ansi("\x1b[32m[+]\x1b[0m ok"), "[+] ok")


class TestParseInfoUid(unittest.TestCase):
    def test_parses_success_output(self):
        self.assertEqual(parse_info_uid(INFO_OUTPUT_SUCCESS), "E00403502030361D")

    def test_returns_none_on_garbage(self):
        self.assertIsNone(parse_info_uid(INFO_OUTPUT_GARBAGE))

    def test_returns_none_on_empty(self):
        self.assertIsNone(parse_info_uid(""))

    def test_strips_ansi_before_parsing(self):
        colored = "[+] \x1b[33mUID\x1b[0m: E0 04 03 50 20 30 36 1D\n"
        self.assertEqual(parse_info_uid(colored), "E00403502030361D")


class TestParseRdblData(unittest.TestCase):
    def test_parses_success_output(self):
        self.assertEqual(parse_rdbl_data(RDBL_OUTPUT_SUCCESS, 0), "D93FEB0A")

    def test_returns_none_for_missing_block(self):
        self.assertIsNone(parse_rdbl_data(RDBL_OUTPUT_SUCCESS, 5))

    def test_returns_none_on_garbage(self):
        self.assertIsNone(parse_rdbl_data(RDBL_OUTPUT_GARBAGE, 0))


if __name__ == "__main__":
    unittest.main()
