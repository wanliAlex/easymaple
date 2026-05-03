"""HTTP client for Roboflow's serverless YOLO endpoint.

Posts a base64-encoded image and returns raw detections (list of
{x, y, width, height, class, confidence}).
"""
from __future__ import annotations

import base64
import io
import os
from pathlib import Path
from typing import Any

import requests
from PIL import Image

DEFAULT_MODEL_ID = "rune-solver-msvzh-z3rhg/1"
DEFAULT_API_URL = "https://serverless.roboflow.com"


class RoboflowClient:
    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        api_url: str = DEFAULT_API_URL,
        api_key: str | None = None,
        confidence: float = 0.4,
        overlap: float = 0.3,
        timeout: float = 10.0,
    ) -> None:
        key = api_key or os.environ.get("ROBOFLOW_API_KEY")
        if not key:
            raise ValueError("provide api_key or set $ROBOFLOW_API_KEY")
        self.api_key = key
        self.api_url = api_url.rstrip("/")
        self.model_id = model_id
        self.confidence = confidence
        self.overlap = overlap
        self.timeout = timeout

    def _encode(self, image: Image.Image | str | Path) -> bytes:
        if isinstance(image, Image.Image):
            buf = io.BytesIO()
            image.convert("RGB").save(buf, format="PNG")
            return base64.b64encode(buf.getvalue())
        return base64.b64encode(Path(image).read_bytes())

    def infer(self, image: Image.Image | str | Path) -> list[dict[str, Any]]:
        body = self._encode(image)
        url = f"{self.api_url}/{self.model_id}"
        params = {
            "api_key": self.api_key,
            "confidence": self.confidence,
            "overlap": self.overlap,
        }
        resp = requests.post(
            url,
            params=params,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("predictions", [])
