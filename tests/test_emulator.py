import contextlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from tonie_writer import cli, emulator, proxmark
from tonie_writer.nfcfile import parse_nfc_file

FIXTURE = Path(__file__).parent / "fixtures" / "nfc" / "Zuma.nfc"


class TestEmulator(unittest.TestCase):
    def setUp(self):
        self.tag = parse_nfc_file(FIXTURE)

    def test_image_contains_transmission_uid_memory_and_metadata(self):
        image = emulator.build_image(self.tag)
        self.assertEqual(image["FileType"], "15693 v4")
        self.assertEqual(image["Card"]["uid"], "1D363020500304E0")
        self.assertEqual(image["Card"]["pagescount"], "08")
        self.assertEqual(image["Card"]["bytesperpage"], "04")
        self.assertEqual(image["Card"]["privacypasswd"], "7FFD6E5B")
        self.assertEqual(image["Card"]["locks"], "00" * 8)
        self.assertEqual(list(image["blocks"].values()), self.tag.blocks)

    def test_invalid_metadata_rejected(self):
        for key, value in [("Password Privacy", "AA"), ("Security Status", "ZZ"),
                           ("Lock AFI", "maybe"), ("Privacy Mode", "true")]:
            with self.subTest(key=key):
                tag = parse_nfc_file(FIXTURE)
                tag.raw[key] = value
                with self.assertRaises(ValueError):
                    emulator.build_image(tag)

    def test_pm3_command_path_quoting(self):
        self.assertEqual(emulator.load_command(Path("/tmp/with spaces/tag.json")),
                         'hf 15 eload -f "/tmp/with spaces/tag.json"')
        for path in ['/tmp/a;quit', '/tmp/a"b', '/tmp/a\nb', '/tmp/a\\b']:
            with self.assertRaises(ValueError):
                emulator.load_command(Path(path))

    @patch.object(proxmark, "run_live", return_value=proxmark.Pm3Result("Done!", "", 0))
    @patch.object(proxmark, "run")
    @patch.object(proxmark, "locate_pm3", return_value="pm3")
    def test_upload_before_simulation_and_cleanup(self, locate, run, live):
        paths = []

        def upload(commands, **kwargs):
            path = Path(commands[0].split('"')[1])
            paths.append(path)
            self.assertEqual(json.loads(path.read_text()), emulator.build_image(self.tag))
            live.assert_not_called()
            return proxmark.Pm3Result("[+] uploaded 2235 bytes to emulator memory", "", 0)

        run.side_effect = upload
        with contextlib.redirect_stdout(io.StringIO()):
            emulator.emulate(self.tag, port="/dev/test")
        self.assertFalse(paths[0].exists())
        live.assert_called_once_with(["hf 15 sim"], port="/dev/test", pm3_bin="pm3")
        self.assertEqual(run.call_args.kwargs["port"], "/dev/test")

    @patch.object(proxmark, "run_live")
    @patch.object(proxmark, "run")
    @patch.object(proxmark, "locate_pm3", return_value="pm3")
    def test_failed_upload_never_starts_stale_image(self, locate, run, live):
        for result in [proxmark.Pm3Result("unknown command", "", 0),
                       proxmark.Pm3Result("uploaded 2235 bytes to emulator memory", "", 1)]:
            run.return_value = result
            with self.assertRaises(proxmark.ProxmarkError):
                emulator.emulate(self.tag)
        live.assert_not_called()

    @patch.object(proxmark, "locate_pm3", return_value=None)
    def test_missing_client(self, locate):
        with self.assertRaises(proxmark.ProxmarkNotFoundError):
            emulator.emulate(self.tag)

    @patch.object(emulator, "emulate")
    @patch.object(proxmark, "locate_pm3", side_effect=AssertionError("dry-run used hardware"))
    def test_cli_json_dry_run_is_offline(self, locate, emulate):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(["--json", "emulate", "Zuma", "--language", "English", "--dry-run", "--yes"])
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["commands"][-1], "hf 15 sim")
        self.assertEqual(payload["image"]["Card"]["uid"], "1D363020500304E0")
        emulate.assert_not_called()

    @patch.object(proxmark.subprocess, "Popen")
    def test_live_runner_streams_and_has_no_timeout(self, popen):
        process = popen.return_value.__enter__.return_value
        process.stdout = iter(["[+] start\n", "Done!\n"])
        process.wait.return_value = 0
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = proxmark.run_live(["hf 15 sim"], port="/dev/test", pm3_bin="pm3")
        self.assertEqual(popen.call_args.args[0], ["pm3", "-p", "/dev/test", "-f", "-c", "hf 15 sim"])
        self.assertNotIn("timeout", popen.call_args.kwargs)
        self.assertEqual(result.stdout, output.getvalue())
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
