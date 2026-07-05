#!/usr/bin/env python3
"""
CovenantOps Agent Execution Receipt — standalone offline verifier.

Verifies that a signed receipt is authentic and untampered, WITHOUT contacting
the CovenantOps Agent server. It only needs the receipt file and the Ed25519 public
key embedded in it (or supplied separately).

Usage:
    python3 verify_receipt.py receipt.json
    python3 verify_receipt.py receipt.json --public-key <base64>

Exit code 0 = valid, 1 = invalid. Requires only the 'cryptography' package.
"""
import argparse
import base64
import hashlib
import json
import sys

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
except ImportError:
    print("This verifier needs the 'cryptography' package:  pip install cryptography")
    sys.exit(2)


def canonical(obj) -> bytes:
    # MUST match the server's canonicalization exactly.
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify a CovenantOps Agent execution receipt offline.")
    ap.add_argument("receipt", help="Path to the receipt JSON file")
    ap.add_argument("--public-key", help="Base64 Ed25519 public key (overrides the one in the receipt)")
    args = ap.parse_args()

    with open(args.receipt, "r", encoding="utf-8") as fh:
        doc = json.load(fh)

    body = doc.get("receipt")
    sig_b64 = doc.get("signature_ed25519_b64")
    pub_b64 = args.public_key or doc.get("public_key_ed25519_b64")
    claimed_hash = doc.get("content_sha256")

    if not (body and sig_b64 and pub_b64):
        print("✗ INVALID: receipt is missing required fields (receipt / signature / public key).")
        return 1

    # 1. Recompute the content hash over the canonical encoding.
    encoded = canonical(body)
    recomputed_hash = hashlib.sha256(encoded).hexdigest()
    hash_ok = (recomputed_hash == claimed_hash)

    # 2. Verify the Ed25519 signature against the canonical bytes.
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_b64))
        pub.verify(base64.b64decode(sig_b64), encoded)
        sig_ok = True
    except (InvalidSignature, Exception):
        sig_ok = False

    print("CovenantOps Agent receipt verification")
    print("  receipt_version :", body.get("receipt_version"))
    print("  trace_id        :", body.get("trace_id"))
    print("  agent_id        :", body.get("agent_id"))
    print("  content hash     :", "MATCH" if hash_ok else "MISMATCH (tampered)")
    print("  Ed25519 signature:", "VALID" if sig_ok else "INVALID")

    if hash_ok and sig_ok:
        print("\n✓ VALID — this receipt is authentic and has not been altered.")
        return 0
    print("\n✗ INVALID — do not trust this receipt.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
