import unittest
from pathlib import Path

from tonie_writer.nfcfile import NfcParseError, parse_nfc_file

FIXTURES = Path(__file__).parent / "fixtures" / "nfc"


class TestParseNfcFile(unittest.TestCase):
    def test_parses_zuma(self):
        tag = parse_nfc_file(FIXTURES / "Zuma.nfc")
        self.assertEqual(tag.uid, "E00403502030361D")
        self.assertEqual(tag.uid_bytes, bytes.fromhex("E00403502030361D"))
        self.assertEqual(tag.device_type, "SLIX")
        self.assertEqual(tag.block_count, 8)
        self.assertEqual(tag.block_size, 4)
        self.assertEqual(len(tag.blocks), 8)
        self.assertEqual(tag.blocks[0], "D93FEB0A")
        self.assertEqual(tag.blocks[-1], "00F20064")
        self.assertEqual(tag.raw["Privacy Mode"], "false")

    def test_parses_nested_series_file(self):
        tag = parse_nfc_file(FIXTURES / "Joke Telling.nfc")
        self.assertTrue(tag.uid.startswith("E00403"))

    def test_parses_umlaut_filename(self):
        tag = parse_nfc_file(FIXTURES / "Kruemelmonsters Mitmampfspass.nfc")
        self.assertTrue(tag.uid.startswith("E00403"))

    def test_rejects_short_uid(self):
        with self.assertRaises(NfcParseError):
            parse_nfc_file(FIXTURES / "bad_short_uid.nfc")

    def test_rejects_bad_block_count(self):
        with self.assertRaises(NfcParseError):
            parse_nfc_file(FIXTURES / "bad_block_count.nfc")

    def test_rejects_truncated_file(self):
        with self.assertRaises(NfcParseError):
            parse_nfc_file(FIXTURES / "bad_truncated.nfc")


if __name__ == "__main__":
    unittest.main()
