from pydantic import BaseModel, Field


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)
    keys: dict[str, str]


class PushUnsubscribeIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)


class PushStateOut(BaseModel):
    supported: bool
    configured: bool
    subscribed: bool
    permission: str | None = None
