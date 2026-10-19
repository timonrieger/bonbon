#!/usr/bin/env -S uv run --script
# [MISE] description="Save your Learner Lab credentials (AWS Details → AWS CLI → Show)"
# [MISE] raw=true
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Save pasted Learner Lab credentials as the default AWS profile.

In the Learner Lab: Start Lab → AWS Details → AWS CLI: Show → copy the whole block.
The credentials expire when the lab session ends (about 4 hours); run this again then.
"""

import configparser
import sys
from pathlib import Path

print("Paste the block from 'AWS Details → AWS CLI', then press Enter on an empty line:")
lines = []
for line in sys.stdin:
    if not line.strip():
        if lines:
            break
        continue
    lines.append(line)

pasted = configparser.ConfigParser()
pasted.read_string("".join(lines))
if not pasted.sections():
    sys.exit("Nothing recognized. Copy the block starting with [default].")
values = pasted[pasted.sections()[0]]

path = Path.home() / ".aws" / "credentials"
path.parent.mkdir(exist_ok=True)
existing = configparser.ConfigParser()
existing.read(path)
existing["default"] = {
    key: values[key] for key in ("aws_access_key_id", "aws_secret_access_key", "aws_session_token")
}
with path.open("w") as f:
    existing.write(f)
print(f"Saved to {path}. Check with: aws sts get-caller-identity")
