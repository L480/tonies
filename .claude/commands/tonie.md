---
description: Write a Tonie to the NFC tag on the Proxmark3
argument-hint: <tonie name> [language]
allowed-tools: Bash(./tonie:*)
---

Write the Tonie the user named to the NFC tag currently on the Proxmark3.

Requested Tonie: **$ARGUMENTS**

Steps:

1. Resolve the name first: `./tonie --json search "$ARGUMENTS"`.
   - No match → report the suggestions the CLI prints and ask which one was meant. Stop.
   - Several plausible matches (e.g. the same Tonie in German and English) → show them
     and ask which one. Do not guess. Stop.
   - One clear match → continue.
2. Write it: `./tonie write "<resolved name>" --language <language>`, adding `--pick N`
   if that is what disambiguated it. Let the tool's confirmation prompt reach the user.
3. Report the outcome in one or two lines: which Tonie, the UID, and whether UID and all
   8 blocks verified. On a non-zero exit, quote the tool's own error — it is written to
   be actionable — and do not retry with different flags on your own.

Never invoke `pm3` directly and never use `hf 15 csetuid`; see CLAUDE.md for why.
