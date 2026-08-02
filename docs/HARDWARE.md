# Hardware guide

Everything you need to know about the reader and the tags: what to buy, how
to set up the Proxmark3, and how to fix it when a write doesn't take.

## 1. The reader: Proxmark3 Easy "512M" clone

This repo is written against a Proxmark3 Easy clone (sold as "Proxmark3
512M" on AliExpress) — a 512 KB ARM MCU board — running the
[Iceman (RfidResearchGroup) firmware](https://github.com/RfidResearchGroup/proxmark3),
built with `PLATFORM=PM3GENERIC`.

### Install on macOS (Apple Silicon)

```sh
xcode-select --install
brew tap RfidResearchGroup/proxmark3
brew install --with-generic proxmark3          # --with-generic = PM3GENERIC, i.e. PM3 Easy / "512M"
# if that fails:
brew install --HEAD --with-generic proxmark3
```

### Flash the firmware

1. Unplug the Proxmark3.
2. Hold its button down while plugging it back in.
3. Release the button once 2 of the 4 LEDs stay on (bootloader mode).
4. Run:
   ```sh
   pm3-flash-all
   ```

Notes:
* Firmware and client must always be the same version — after
  `brew upgrade proxmark3`, re-run `pm3-flash-all`.
* MCU size (256/512 KB) is auto-detected while flashing; a 512 KB board
  needs no `SKIP_*` trimming.
* The serial device usually appears as `/dev/tty.usbmodemiceman1` (older
  firmware: `/dev/tty.usbmodem881`). Pass it explicitly with `./tonie --port
  /dev/tty.usbmodemiceman1 ...` if auto-detection picks the wrong one.
* Since client v4.19552, Rosetta 2 is no longer required on Apple Silicon.

## 2. Tag compatibility — the part that wastes money if you get it wrong

### What the Toniebox actually checks

Tonie figures use NXP ICODE SLIX-L chips (ISO 15693 / NFC-V). A stock
Toniebox validates the **first three UID bytes: `E0 04 03`** (`E0` = ISO
15693, `04` = NXP, `03` = ICODE SLIX-L). If they don't match, the box does
*nothing at all* — no sound, no LED, no error. The Tonie's identity is
carried entirely by the UID; the 32 bytes of user memory are cloned for
fidelity but aren't what the cloud lookup uses.

On an **unmodified** Toniebox, the only way to make a blank tag play
something is to clone the UID of a real Tonie the cloud already knows.
Assigning custom content to a tag's own UID requires a modified box
(TeddyCloud / HackieboxNG) and is out of scope for this repo.

### Buying guide

| Tag | Works on a stock box? | Why |
|-----|:---:|-----|
| Magic **SLIX-L**, changeable UID (e.g. [rfidfriend.com](http://rfidfriend.com), magic variant) | ✅ | **This is what you need.** Right chip class, UID can be set to a real Tonie's `E0 04 03…`. |
| Generic "magic ISO15693 / ICODE SLI / SLIX / TAG-it, UID changeable" | ❌ | UID can be set to `E00403…`, but the chip is SLI/SLIX class and fails the box's privacy-password check. |
| Genuine SLIX-L, fixed UID (the TeddyCloud product) | ❌ | UID is unknown to the cloud on an unmodified box — no reader can change a genuine tag's UID. |
| Genuine SLIX (common AliExpress "programmable RFID sticker") | ❌ | Wrong UID prefix (`E0 04 02`) *and* no privacy-password support. |

Contact `rfidfriend@gmail.com` if it's unclear which variant a listing is —
they sell both the magic (works here) and fixed-UID (TeddyCloud-only)
SLIX-L tags, and the listings look similar.

Two independent confirmations that magic SLIX-L from rfidfriend.com works on
a stock box: upstream issue
[nortakales/flipper-zero-tonies#170](https://github.com/nortakales/flipper-zero-tonies/issues/170),
and [SLI-Writer](https://github.com/Julienbxl/SLI-Writer), which lists
"SLIX-L Tags: rfidfriend.com in normal mode" as supported and documents the
write sequence this repo reuses (§3 below).

### Why "plain SLIX" listings look like they should work but don't

Every positive review of plain "programmable" SLIX stickers on a Toniebox
describes a **patched** box (HackieboxNG's OFW patch, which allows tags
*without* privacy-password support). On a stock box these tags are dead on
arrival: fixed `E0 04 02…` UID, wrong chip class. "Programmable" there
refers to the memory contents, not the UID.

### Test tags

Cheap AliExpress magic ISO 15693 tags (ICODE SLI, SLIX2, TAG-it TI2048, …)
accept the same magic UID write frames as SLIX-L. They will **not** satisfy
a stock Toniebox, but they're ideal for exercising the whole CLI path —
write, read-back, verify, error handling — without burning the more
expensive SLIX-L tags. `./tonie doctor --probe-magic` works the same way on
these.

### The 2-minute check

Run `./tonie doctor --probe-magic` with a tag on the antenna:

| Outcome | Meaning | What to do |
|---------|---------|------------|
| Magic write ok, UID becomes `E0 04 03…`, chip reports SLIX-L | Magic SLIX-L ✅ | Everything in this repo works as designed. |
| Magic write ok, but the chip is SLI/SLIX/TAG-it class | Magic, wrong class ⚠️ | Write succeeds, but a stock box will most likely still ignore the tag. Fine as a development/test tag. |
| UID unchanged after the write | Fixed-UID tag ❌ | Cloning is physically impossible with this tag. Buy magic SLIX-L. |

### Fallback: Flipper Zero

If the Proxmark3 path fails on a given batch of tags, the same `.nfc` files
in `data/tonies/` are Flipper-native — try
[SLI-Writer](https://github.com/Julienbxl/SLI-Writer) on a Flipper Zero
instead.

## 3. The `hf 15` command reference

| Command | Purpose |
|---------|---------|
| `hf 15 info` | tag present? shows UID, chip type |
| `hf 15 wrbl --ua -b <0-7> -d AABBCCDD` | write one 4-byte block, non-addressed (flags `0x02`) |
| `hf 15 wrbl --ua -o -b <0-7> -d AABBCCDD` | same with the OPTION flag (`0x42`) — retry variant |
| `hf 15 raw -acw -d 02E00940<b7><b6><b5><b4>` | magic UID write, high half |
| `hf 15 raw -acw -d 02E00941<b3><b2><b1><b0>` | magic UID write, low half |
| `hf 15 rdbl --ua -b <0-7>` | read one block back (verification) |
| `hf 15 dump --ns` | read all blocks, don't save to file |

`hf 15 raw` flags: `-a` activate field, `-c` append CRC, `-w` wait longer
(writes). `--ua` means unaddressed; without it, `hf 15` scans for a tag and
writes *addressed*, which is not what we want here.

### ⚠️ Why this repo never calls `csetuid`

`hf 15 csetuid --v2` can **permanently brick a magic SLIX-L tag**. The
Proxmark3 firmware's `SetTag15693Uid_v2` sends a Gen2 "layout" command
(`... 47 3f 03 8b 00`) before writing the UID; SLI-Writer, the known-working
reference implementation, sends only the two UID frames and states
explicitly that the layout command is "intentionally NOT sent... will brick
SLIX-L magic cards."

The safe equivalent — what this repo actually sends — is those two frames by
hand:

```
hf 15 raw -acw -d 02E00940<uid[7]><uid[6]><uid[5]><uid[4]>
hf 15 raw -acw -d 02E00941<uid[3]><uid[2]><uid[1]><uid[0]>
```

Each half is sent **reversed** (`uid[0]` = the first byte of the `.nfc`
file's `UID:` line = `E0`), because the card stores the UID LSB-first. For
`UID: E0 04 03 50 20 30 36 1D`:

```
hf 15 raw -acw -d 02E009401D363020
hf 15 raw -acw -d 02E00941500304E0
```

`hf 15 csetuid` *without* `--v2` is a different, older magic protocol. It
won't brick the tag, but it doesn't work on these tags either. There is
deliberately no `--gen2` flag or automatic gen1→gen2 fallback anywhere in
this CLI — only the two raw frames above are ever sent.

Do **not** use `hf 15 restore -f …` either: it requires a full binary tag
struct dump whose layout changes between Proxmark3 releases.

## 4. Expert notes

* `.nfc` files include `Password Privacy: 7F FD 6E 5B` — the well-known
  Tonies privacy password. This repo never writes passwords by default;
  `hf 15 slixwritepwd` / `passprotect*` can permanently lock a tag out of
  further writes, so only touch those manually if you know what you're
  doing.
* `Privacy Mode` in every upstream `.nfc` file is `false`, so the write flow
  never needs to disable privacy mode before writing.

## 5. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `pm3`/`proxmark3` not found | not installed, or not on `PATH` | Re-run the install steps above; check `which pm3`. |
| `./tonie doctor` shows no serial device | Proxmark3 not in normal mode, USB issue, or driver/permissions | Unplug/replug without holding the button; check `ls /dev/tty.usbmodem*`; on Linux you may need to be in the `dialout` group. |
| No tag found | tag not on the antenna, or antenna misaligned | Center the tag directly on the Proxmark3's antenna coil; move away from other RFID/metal. |
| UID write doesn't take (`./tonie write` exits with code 5) | not a magic SLIX-L tag | Run `./tonie doctor --probe-magic` to find out which kind of tag this is; see the buying guide above. |
| Verification reports "inconclusive" | pm3 output didn't match the expected format (firmware/client version difference) | Re-run with `--verbose` to see the raw output; the write likely still succeeded — `tonie read` to double check. |
| Verification reports a mismatch (exit code 6) | write partially failed | Retry the write; if it keeps failing, try `--retries` higher or reseat the tag on the antenna. |
