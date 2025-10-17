"""
Utility: generate a development JWT for testing Authorization: Bearer flows.

Usage (PowerShell):

  .venv\\Scripts\\python -m api.scripts.make_dev_jwt --secret change-me --sub you@example.com

Optional claims:
  --aud my-audience
  --iss my-issuer
  --exp-seconds 3600
"""
from __future__ import annotations

import argparse
import time
import jwt  # type: ignore[import]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secret", required=True, help="HMAC secret to sign with (HS256)")
    ap.add_argument("--sub", default="tester", help="subject claim")
    ap.add_argument("--aud", help="audience claim")
    ap.add_argument("--iss", help="issuer claim")
    ap.add_argument("--exp-seconds", type=int, default=3600, help="expiration window in seconds")
    args = ap.parse_args()

    now = int(time.time())
    payload = {"sub": args.sub, "iat": now, "exp": now + args.exp_seconds}
    if args.aud:
        payload["aud"] = args.aud
    if args.iss:
        payload["iss"] = args.iss

    token = jwt.encode(payload, args.secret, algorithm="HS256")
    print(token)


if __name__ == "__main__":
    main()
