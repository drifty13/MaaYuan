import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


AGENT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_ROOT))

from custom.action import star_capture_transport as transport  # noqa: E402
from custom.action.inventory_reporting import (  # noqa: E402
    AUTO_UPLOAD_MODE,
    UploadSettings,
)


PNG = b"\x89PNG\r\n\x1a\nminimal"


def session():
    return {
        "success": True,
        "stop_reason": "bottom_no_move",
        "retained_images": ["capture-00.png", "capture-01.png"],
        "adjacent_relations": [
            {
                "previous_image": "capture-00.png",
                "current_image": "capture-01.png",
                "relation": "overlap",
            }
        ],
    }


class _Response:
    status = 200

    def getcode(self):
        return self.status

    def read(self):
        return b'{"status_code":200,"data":{"capture_id":"ignored"}}'

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class StarCaptureTransportTests(unittest.TestCase):
    def test_manifest_uses_stable_capture_id_one_based_order_and_preserved_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            for name in session()["retained_images"]:
                (run_dir / name).write_bytes(PNG)
            first, paths = transport.build_main_capture_manifest(run_dir, session(), "如鸢")
            second, _ = transport.build_main_capture_manifest(run_dir, session(), "如鸢")
        self.assertEqual(first["capture_id"], second["capture_id"])
        self.assertEqual([image["source_order"] for image in first["images"]], [1, 2])
        self.assertTrue(first["images"][0]["source_image_id"].endswith(":000"))
        self.assertTrue(first["images"][1]["source_image_id"].endswith(":001"))
        self.assertEqual(len(paths), 2)
        self.assertEqual(first["adjacent_relations"][0]["relation"], "overlap")

    def test_multipart_upload_reuses_token_and_sends_manifest_and_each_png(self):
        settings = UploadSettings(AUTO_UPLOAD_MODE, "secret-token", "https://hub.example")
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            for name in session()["retained_images"]:
                (run_dir / name).write_bytes(PNG)
            manifest, paths = transport.build_main_capture_manifest(run_dir, session(), "如鸢")
            with patch.object(transport.urllib_request, "urlopen", return_value=_Response()) as urlopen:
                result = transport.upload_main_capture_manifest(manifest, paths, settings)
        self.assertTrue(result.success)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://hub.example/open-api/star/captures")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-token")
        body = request.data
        self.assertIn(b'name="manifest"', body)
        self.assertEqual(body.count(b'name="files"'), 2)
        self.assertIn(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), body)

    def test_upload_is_not_attempted_when_local_only_mode_is_selected(self):
        context = SimpleNamespace(
            get_node_data=lambda _name: {"attach": {"mode": "仅保存到本地", "base_url": "https://hub.example"}}
        )
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            for name in session()["retained_images"]:
                (run_dir / name).write_bytes(PNG)
            with patch.object(transport, "upload_main_capture_manifest") as upload:
                result = transport.upload_successful_main_capture(context, run_dir, session(), "如鸢")
        self.assertIsNone(result)
        upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
