import base64
import binascii
import re

from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import BaseModel, Field, field_validator

from app.services.push_endpoint import validate_endpoint


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)
    keys: dict[str, str]

    _endpoint_policy = field_validator("endpoint")(validate_endpoint)

    @field_validator("keys")
    @classmethod
    def valid_keys(cls, keys: dict[str, str]) -> dict[str, str]:
        try:
            decoded = {}
            for name, length in (("p256dh", 65), ("auth", 16)):
                value = keys[name]
                if len(value) > 100 or not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", value):
                    raise ValueError
                decoded[name] = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
                if len(decoded[name]) != length:
                    raise ValueError
            ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), decoded["p256dh"])
        except (KeyError, ValueError, binascii.Error):
            raise ValueError("Некорректные ключи push-подписки") from None
        return {name: keys[name] for name in ("p256dh", "auth")}


class PushUnsubscribeIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)


class PushStateOut(BaseModel):
    supported: bool
    configured: bool
    subscribed: bool
    permission: str | None = None
