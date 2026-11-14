"""ES256 keys, JWKS and compact JWS (RFC 7515) helpers.

Keys are generated on first start and kept in the data directory (never in the
repo). The gateway key signs Offer Attestations, the Agent Card and Order
Confirmations. Each buyer organisation has its own key (held by the buyer's
"wallet" — simulated here) that signs Intent Mandates.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class SigningKey:
    def __init__(self, kid: str, private_key: ec.EllipticCurvePrivateKey):
        self.kid = kid
        self.private_key = private_key

    @property
    def public_jwk(self) -> dict:
        nums = self.private_key.public_key().public_numbers()
        return {"kty": "EC", "crv": "P-256", "alg": "ES256", "use": "sig", "kid": self.kid,
                "x": b64u(nums.x.to_bytes(32, "big")), "y": b64u(nums.y.to_bytes(32, "big"))}

    def sign(self, payload: dict, typ: str = "JWT") -> str:
        return jwt.encode(payload, self.private_key, algorithm="ES256", headers={"kid": self.kid, "typ": typ})


def load_or_create(path: Path | None, kid: str) -> SigningKey:
    if path and path.exists():
        pk = serialization.load_pem_private_key(path.read_bytes(), password=None)
        return SigningKey(kid, pk)
    pk = ec.generate_private_key(ec.SECP256R1())
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pk.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    return SigningKey(kid, pk)


def jws_header(token: str) -> dict:
    return json.loads(b64u_dec(token.split(".")[0]))


def jws_payload_unverified(token: str) -> dict:
    return json.loads(b64u_dec(token.split(".")[1]))


def verify_jws(token: str, jwks: list[dict]) -> tuple[bool, dict | None, str]:
    """Return (ok, payload, detail). Never raises."""
    try:
        header = jws_header(token)
        if header.get("alg") != "ES256":
            return False, None, f"unsupported alg {header.get('alg')}"
        jwk = next((k for k in jwks if k.get("kid") == header.get("kid")), None)
        if not jwk:
            return False, None, f"unknown kid {header.get('kid')}"
        key = ECAlgorithm.from_jwk(json.dumps(jwk))
        payload = jwt.decode(token, key, algorithms=["ES256"],
                             options={"verify_exp": False, "verify_nbf": False, "verify_aud": False,
                                      "verify_iat": False, "verify_iss": False})
        return True, payload, f"ES256 signature valid (kid {header['kid']})"
    except Exception as e:  # noqa: BLE001 - any failure means "not verified"
        return False, None, f"signature invalid: {type(e).__name__}"
