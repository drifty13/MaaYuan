"""Private B4 main-star transport: manifest construction and multipart upload only."""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from custom.action.inventory_reporting import (
    AUTO_UPLOAD_MODE,
    UploadResult,
    UploadSettings,
    _retry_wait,
    read_upload_settings,
)


STAR_CAPTURE_PATH = "/open-api/star/captures"
_IMAGE_NAME = re.compile(r"^capture-\d{2}\.png$")


def build_main_capture_manifest(
    run_dir: Path, session: dict[str, Any], game_version: str
) -> tuple[dict[str, Any], list[Path]]:
    """Build the smoke manifest without changing B capture diagnostics or images."""
    if session.get("success") is not True or session.get("stop_reason") != "bottom_no_move":
        raise ValueError("只有 bottom_no_move 成功主星采集可以上传")
    if game_version not in {"如鸢", "代号鸢"}:
        raise ValueError("game_version 必须是 如鸢 或 代号鸢")
    image_names = session.get("retained_images")
    if not isinstance(image_names, list) or not image_names:
        raise ValueError("连续采集缺少 retained_images")
    if len(set(image_names)) != len(image_names):
        raise ValueError("连续采集 retained_images 重复")

    resolved_dir = run_dir.resolve()
    paths: list[Path] = []
    for name in image_names:
        if not isinstance(name, str) or not _IMAGE_NAME.fullmatch(name):
            raise ValueError("连续采集图片文件名无效")
        path = (resolved_dir / name).resolve()
        if path.parent != resolved_dir or not path.is_file():
            raise ValueError("连续采集图片不存在")
        paths.append(path)

    # run_dir is immutable for one successful capture, so retries retain this ID
    # without adding mutable transport fields to session.json.
    capture_id = "star-" + uuid.uuid5(uuid.NAMESPACE_URL, resolved_dir.as_uri()).hex
    source_id_by_name = {
        path.name: f"{capture_id}:main:{index:03d}"
        for index, path in enumerate(paths)
    }
    relations: list[dict[str, str]] = []
    raw_relations = session.get("adjacent_relations")
    if not isinstance(raw_relations, list):
        raise ValueError("连续采集 adjacent_relations 无效")
    for relation in raw_relations:
        if not isinstance(relation, dict) or relation.get("relation") != "overlap":
            raise ValueError("连续采集 overlap 关系无效")
        previous = source_id_by_name.get(str(relation.get("previous_image", "")))
        current = source_id_by_name.get(str(relation.get("current_image", "")))
        if not previous or not current:
            raise ValueError("连续采集 overlap 未指向保留图片")
        relations.append(
            {
                "previous_source_image_id": previous,
                "current_source_image_id": current,
                "relation": "overlap",
            }
        )
    return (
        {
            "schema_version": 1,
            "capture_id": capture_id,
            "game_version": game_version,
            "section": "main",
            "stop_reason": "bottom_no_move",
            "images": [
                {
                    "source_image_id": source_id_by_name[path.name],
                    "source_order": index + 1,
                    "file_name": path.name,
                }
                for index, path in enumerate(paths)
            ],
            "adjacent_relations": relations,
        },
        paths,
    )


def _multipart_body(manifest: dict[str, Any], paths: list[Path]) -> tuple[bytes, str]:
    boundary = "----MaaYuanStarCapture" + uuid.uuid4().hex
    chunks: list[bytes] = []

    def add(headers: list[str], payload: bytes) -> None:
        chunks.append(("--" + boundary + "\r\n").encode("ascii"))
        chunks.extend((header + "\r\n").encode("utf-8") for header in headers)
        chunks.append(b"\r\n")
        chunks.append(payload)
        chunks.append(b"\r\n")

    add(
        [
            'Content-Disposition: form-data; name="manifest"',
            "Content-Type: application/json; charset=utf-8",
        ],
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
    )
    for path in paths:
        add(
            [
                f'Content-Disposition: form-data; name="files"; filename="{path.name}"',
                "Content-Type: image/png",
            ],
            path.read_bytes(),
        )
    chunks.append(("--" + boundary + "--\r\n").encode("ascii"))
    return b"".join(chunks), boundary


def upload_successful_main_capture(
    context: Any,
    run_dir: Path,
    session: dict[str, Any],
    game_version: str,
    *,
    timeout_seconds: float = 20.0,
    max_attempts: int = 3,
) -> UploadResult | None:
    """Upload only in existing automatic-upload mode; failures stay non-fatal to capture."""
    settings = read_upload_settings(context)
    if settings.mode != AUTO_UPLOAD_MODE:
        return None
    manifest, paths = build_main_capture_manifest(run_dir, session, game_version)
    return upload_main_capture_manifest(manifest, paths, settings, timeout_seconds, max_attempts)


def upload_main_capture_manifest(
    manifest: dict[str, Any],
    paths: list[Path],
    settings: UploadSettings,
    timeout_seconds: float = 20.0,
    max_attempts: int = 3,
) -> UploadResult:
    if settings.mode != AUTO_UPLOAD_MODE or not settings.token:
        raise ValueError("只有配置 Token 的自动上报模式可以上传星石截图")
    if timeout_seconds <= 0 or max_attempts < 1:
        raise ValueError("星石截图上传参数无效")
    body, boundary = _multipart_body(manifest, paths)
    request = urllib_request.Request(
        settings.base_url + STAR_CAPTURE_PATH,
        data=body,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {settings.token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "MaaYuan-StarCapture/1",
        },
        method="POST",
    )
    for attempt in range(max_attempts):
        try:
            with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
                status_code = int(getattr(response, "status", response.getcode()))
                response_body = response.read().decode("utf-8", errors="replace")
            if 200 <= status_code < 300:
                return UploadResult(True, status_code, f"HTTP {status_code}")
            if status_code >= 500 and attempt + 1 < max_attempts:
                _retry_wait(attempt)
                continue
            return UploadResult(False, status_code, _response_message(status_code, response_body))
        except urllib_error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            if exc.code >= 500 and attempt + 1 < max_attempts:
                _retry_wait(attempt)
                continue
            return UploadResult(False, int(exc.code), _response_message(exc.code, response_body))
        except (urllib_error.URLError, TimeoutError, OSError) as exc:
            if attempt + 1 < max_attempts:
                _retry_wait(attempt)
                continue
            return UploadResult(False, None, f"网络连接失败：{getattr(exc, 'reason', exc)}")
    raise RuntimeError("星石截图上传重试循环异常结束")


def _response_message(status_code: int, response_body: str) -> str:
    try:
        payload = json.loads(response_body)
        message = payload.get("message") or (payload.get("error") or {}).get("message")
        if isinstance(message, str) and message.strip():
            return f"HTTP {status_code}：{message.strip()}"
    except (json.JSONDecodeError, AttributeError):
        pass
    return f"HTTP {status_code}"
