#!/usr/bin/env python3
"""Run terraform with the values from .env.

Loads .env, maps each value to the TF_VAR_* environment variable Terraform
expects, adds -chdir for the infrastructure directory, and passes every other
argument straight through.

    python scripts/tf.py init
    python scripts/tf.py plan
    python scripts/tf.py apply
    python scripts/tf.py output -raw cloudfront_domain_name

Required values are listed in REQUIRED below; a missing one stops here with a
message rather than letting Terraform prompt or build something half-named.

Set TERRAFORM to use a binary other than `terraform` on PATH.

Keep this file ASCII-only.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"
EXAMPLE_ENV = REPO_ROOT / "env.example"
TERRAFORM_DIR = REPO_ROOT / "infrastructure"
TERRAFORM = os.environ.get("TERRAFORM", "terraform")

# .env name -> Terraform variable name.
REQUIRED = {
    "S3_BUCKET": "bucket_name",
    "DOMAIN_NAME": "domain_name",
    "AWS_PROFILE": "aws_profile",
    "COGNITO_DOMAIN_PREFIX": "cognito_domain_prefix",
}

# Optional: these have defaults in variables.tf and terraform.tfvars. Setting
# them in .env overrides those.
OPTIONAL = {
    "AWS_REGION": "aws_region",
}


def die(message):
    print("ERROR: %s" % message, file=sys.stderr)
    raise SystemExit(1)


def load_env():
    if not ENV_FILE.exists():
        die("No .env at %s -- copy %s there and fill it in."
            % (ENV_FILE, EXAMPLE_ENV.name))

    values = {k: v for k, v in dotenv_values(ENV_FILE).items() if v not in (None, "")}

    missing = [name for name in REQUIRED if name not in values]
    if missing:
        die("Missing in .env: %s\n       See %s for what each one is."
            % (", ".join(sorted(missing)), EXAMPLE_ENV.name))

    placeholders = [name for name in REQUIRED if is_placeholder(values[name])]
    if placeholders:
        die("Still on the example values in .env: %s\n       See %s."
            % (", ".join(sorted(placeholders)), EXAMPLE_ENV.name))

    return values


def is_placeholder(value):
    lowered = value.strip().lower()
    return (lowered.startswith("your-")
            or lowered in ("change-me", "default-changeme")
            or "example.com" in lowered)


def main(argv):
    if not argv:
        print(__doc__)
        return 2

    # Config problems first: they are the common case and the fixable one.
    values = load_env()

    if not shutil.which(TERRAFORM):
        die("%s is not on PATH -- install Terraform >= 1.6 and try again." % TERRAFORM)

    env = os.environ.copy()
    for source, target in {**REQUIRED, **OPTIONAL}.items():
        if source in values:
            env["TF_VAR_%s" % target] = values[source]

    command = [TERRAFORM, "-chdir=%s" % TERRAFORM_DIR] + argv
    return subprocess.call(command, env=env)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
