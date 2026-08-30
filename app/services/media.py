"""Small, server-side media security boundary for uploaded images."""
from __future__ import annotations

from io import BytesIO

from fastapi import HTTPException, Response, status
from PIL import Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 40_000_000
_FORMATS = {"JPEG": ("image/jpeg", ".jpg"), "PNG": ("image/png", ".png"), "WEBP": ("image/webp", ".webp")}


def normalize_image(content: bytes) -> tuple[bytes, str, str]:
    """Decode and re-encode a supported image, removing metadata/polyglots."""
    try:
        with Image.open(BytesIO(content)) as verified:
            image_format = verified.format
            if image_format not in _FORMATS:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Поддерживаются только JPEG, PNG и WebP")
            verified.verify()
        with Image.open(BytesIO(content)) as source:
            image = ImageOps.exif_transpose(source)
            image.load()
            media_type, suffix = _FORMATS[image_format]
            if image_format == "JPEG" and image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            output = BytesIO()
            options = {"quality": 92, "optimize": True} if image_format in {"JPEG", "WEBP"} else {"optimize": True}
            image.save(output, format=image_format, **options)
            return output.getvalue(), media_type, suffix
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Файл не является корректным изображением JPEG, PNG или WebP")


def image_response(content: bytes, media_type: str) -> Response:
    return Response(content, media_type=media_type, headers={
        "Content-Disposition": "inline",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    })
