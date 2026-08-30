from io import BytesIO

import pytest
from fastapi import HTTPException
from PIL import Image

from app.services.media import image_response, normalize_image


def image_bytes(format_name: str) -> bytes:
    image = Image.new("RGB", (24, 16), "red")
    output = BytesIO()
    image.save(output, format=format_name)
    return output.getvalue()


@pytest.mark.parametrize(("format_name", "expected_type", "suffix"), [
    ("JPEG", "image/jpeg", ".jpg"), ("PNG", "image/png", ".png"), ("WEBP", "image/webp", ".webp"),
])
def test_supported_images_are_decoded_and_normalized(format_name, expected_type, suffix):
    normalized, media_type, normalized_suffix = normalize_image(image_bytes(format_name))
    with Image.open(BytesIO(normalized)) as image:
        assert image.format == format_name
    assert (media_type, normalized_suffix) == (expected_type, suffix)


@pytest.mark.parametrize("payload", [b"not really a jpeg", b"\xff\xd8\xffbroken", b"<script>alert(1)</script>"])
def test_fake_or_corrupt_images_are_rejected(payload):
    with pytest.raises(HTTPException) as error:
        normalize_image(payload)
    assert error.value.status_code == 422


def test_unsupported_image_format_is_a_controlled_4xx():
    with pytest.raises(HTTPException) as error:
        normalize_image(image_bytes("GIF"))
    assert error.value.status_code == 422


def test_image_download_uses_safe_inline_headers():
    response = image_response(b"image", "image/jpeg")
    assert response.media_type == "image/jpeg"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"] == "inline"
