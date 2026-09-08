import importlib.util
import json
import sys
import tempfile
import unittest
from unittest import mock
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import cv2


AGENT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_ROOT))

_MODULE_PATH = AGENT_ROOT / "custom" / "action" / "star_backpack_capture_probe.py"
_SPEC = importlib.util.spec_from_file_location("star_backpack_capture_probe_test", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
compute_visual_overlap = _MODULE.compute_visual_overlap
estimate_vertical_motion = _MODULE.estimate_vertical_motion
evaluate_feedback_candidate = _MODULE.evaluate_feedback_candidate
evaluate_semantic_row_overlap = _MODULE.evaluate_semantic_row_overlap
estimate_row_lattice = _MODULE._estimate_row_lattice
local_overlap_confirmation = _MODULE._local_overlap_confirmation
apply_direct_overlap_anchors = _MODULE._apply_direct_overlap_anchors
find_direct_normal_band_candidate = _MODULE._find_direct_normal_band_candidate
merge_direct_normal_candidate = _MODULE._merge_direct_normal_candidate
MotionHypothesis = _MODULE._MotionHypothesis
select_motion_hypothesis = _MODULE._select_motion_hypothesis
parse_capture_probe_params = _MODULE.parse_capture_probe_params
StarBackpackCaptureProbe = _MODULE.StarBackpackCaptureProbe


class _FakeScreencapTask:
    def __init__(self, image):
        self.images = [image] if isinstance(image, np.ndarray) else list(image)
        self.screencap_calls = 0
        self.swipes = []

    def post_screencap(self):
        return self

    def wait(self):
        return self

    def get(self):
        image = self.images[min(self.screencap_calls, len(self.images) - 1)]
        self.screencap_calls += 1
        return image

    def post_swipe(self, *gesture):
        self.swipes.append(gesture)
        return self


class _FakeCaptureContext:
    def __init__(self, image):
        self.tasker = SimpleNamespace(controller=_FakeScreencapTask(image))


def _complex_scene(height=360, width=240, seed=1):
    rng = np.random.default_rng(seed)
    image = rng.integers(0, 70, size=(height, width, 3), dtype=np.uint8)
    for index, y in enumerate(range(25, height, 43)):
        color = tuple(int(value) for value in rng.integers(90, 255, size=3))
        cv2.circle(image, (35 + (index % 4) * 55, y), 14, color, 2)
        cv2.line(image, (5, y + 10), (width - 6, y - 7), color, 1)
        cv2.putText(
            image,
            f"{seed}-{index}",
            (100, min(height - 6, y + 7)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.36,
            color,
            1,
            cv2.LINE_AA,
        )
    return image


def _shift_up(before, shift, seed=99):
    rng = np.random.default_rng(seed)
    tail = rng.integers(
        0, 256, size=(shift, before.shape[1], before.shape[2]), dtype=np.uint8
    )
    return np.vstack([before[shift:, :, :], tail])


def _periodic_scene_with_unique_tail(height=900, width=300, period=68, seed=701):
    tile = _complex_scene(height=period, width=width, seed=seed)
    image = np.tile(tile, (height // period + 1, 1, 1))[:height].copy()
    for index, y in enumerate((570, 635, 700, 765, 830)):
        color = (20 + index * 35, 250 - index * 25, 80 + index * 20)
        cv2.rectangle(image, (22 + index * 32, y), (65 + index * 32, y + 32), color, -1)
        cv2.putText(
            image,
            f"UNIQUE-{index}",
            (105, y + 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            color,
            2,
            cv2.LINE_AA,
        )
    return image


def _feedback_config(safe_min=100, safe_max=230):
    return {
        "max_micro_attempts": 2,
        "local_search_radius_px": 20,
        "diagnostic_safe_shift_px": (safe_min, safe_max),
        "diagnostic_expected_shift_px": (25, 700),
        "diagnostic_physical_shift_px": (20, 700),
        "diagnostic_target_shift_px": (150, 200),
        "diagnostic_normal_safe_shift_px": (safe_min, safe_max),
        "diagnostic_row_pitch_px": 166.5,
        "diagnostic_micro_trigger_shift_px": 100,
        "diagnostic_min_confidence": 0.20,
        "diagnostic_min_local_overlap_score": 0.60,
        "diagnostic_no_move_similarity": 0.97,
        "diagnostic_no_move_shift_px": 20,
    }


def _b1d_feedback_config():
    return {
        "max_micro_attempts": 2,
        "local_search_radius_px": 20,
        "diagnostic_safe_shift_px": (300, 600),
        "diagnostic_expected_shift_px": (250, 700),
        "diagnostic_physical_shift_px": (30, 700),
        "diagnostic_target_shift_px": (610, 630),
        "diagnostic_normal_safe_shift_px": (560, 650),
        "diagnostic_row_pitch_px": 166.5,
        "diagnostic_micro_trigger_shift_px": 300,
        "diagnostic_min_confidence": 0.20,
        "diagnostic_min_local_overlap_score": 0.60,
        "diagnostic_no_move_similarity": 0.97,
        "diagnostic_no_move_shift_px": 20,
    }


class StarBackpackCaptureProbeParamsTests(unittest.TestCase):
    def test_capture_only_uses_safe_defaults(self):
        self.assertEqual(
            parse_capture_probe_params({}),
            {"mode": "capture_only", "debug_dir": "debug/star-backpack-probe"},
        )

    def test_pair_probe_requires_explicit_roi(self):
        with self.assertRaisesRegex(ValueError, "compare_roi"):
            parse_capture_probe_params(
                {
                    "mode": "pair_probe",
                    "swipe": {
                        "start": [1, 2],
                        "end": [3, 4],
                        "duration_ms": 400,
                    },
                }
            )

    def test_pair_probe_requires_explicit_swipe(self):
        with self.assertRaisesRegex(ValueError, "swipe"):
            parse_capture_probe_params(
                {"mode": "pair_probe", "compare_roi": [0, 0, 40, 40]}
            )

    def test_capture_only_saves_raw_png_and_metadata_without_swiping(self):
        image = np.zeros((13, 17, 3), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as directory:
            result = StarBackpackCaptureProbe().run(
                _FakeCaptureContext(image),
                SimpleNamespace(
                    custom_action_param={
                        "mode": "capture_only",
                        "debug_dir": directory,
                    }
                ),
            )
            self.assertTrue(getattr(result, "success", False))
            run_dir = next(Path(directory).iterdir())
            metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertTrue((run_dir / "capture.png").is_file())
            self.assertEqual(
                {key: metadata[key] for key in ("mode", "width", "height", "channels", "dtype", "file")},
                {
                    "mode": "capture_only",
                    "width": 17,
                    "height": 13,
                    "channels": 3,
                    "dtype": "uint8",
                    "file": "capture.png",
                },
            )

    def test_feedback_pipeline_enables_single_swipe_calibration_with_stable_settle(self):
        pipeline_path = (
            AGENT_ROOT.parent
            / "assets"
            / "resource"
            / "base"
            / "pipeline"
            / "star_backpack_feedback_probe.json"
        )
        pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
        params = pipeline["开发调试-星石背包反馈滑动探针"]["action"]["param"][
            "custom_action_param"
        ]
        parsed = parse_capture_probe_params(params)
        self.assertTrue(parsed["single_swipe_calibration"])
        self.assertEqual(parsed["coarse_swipe"], (360, 930, 360, 540, 700))
        self.assertEqual(parsed["settle_ms"], 2500)


class StarBackpackCaptureProbeVisualTests(unittest.TestCase):
    def test_identical_images_have_high_same_position_score(self):
        image = np.random.default_rng(10).integers(
            0, 256, size=(100, 60, 3), dtype=np.uint8
        )
        metrics = compute_visual_overlap(image, image.copy(), 0.20, 0.90)
        self.assertGreater(metrics["same_position_score"], 0.99)
        self.assertEqual(metrics["classification"], "diagnostic_only")

    def test_known_vertical_overlap_is_found(self):
        rng = np.random.default_rng(20)
        before = rng.integers(0, 256, size=(100, 50, 3), dtype=np.uint8)
        shift = 30
        after = np.vstack(
            [
                before[shift:, :, :],
                rng.integers(0, 256, size=(shift, 50, 3), dtype=np.uint8),
            ]
        )
        metrics = compute_visual_overlap(before, after, 0.20, 0.90)
        self.assertEqual(metrics["best_overlap_px"], 100 - shift)
        self.assertGreater(metrics["best_overlap_score"], 0.99)
        self.assertEqual(metrics["best_shift_px"], shift)

    def test_unrelated_images_do_not_report_high_confidence_overlap(self):
        first = np.random.default_rng(30).integers(
            0, 256, size=(100, 60, 3), dtype=np.uint8
        )
        second = np.random.default_rng(40).integers(
            0, 256, size=(100, 60, 3), dtype=np.uint8
        )
        metrics = compute_visual_overlap(first, second, 0.20, 0.90)
        self.assertLess(metrics["best_overlap_score"], 0.30)


class StarBackpackCaptureProbeFeedbackTests(unittest.TestCase):
    def test_semantic_overlap_requires_complete_row_envelope_not_physical_height(self):
        image = np.zeros((760, 240, 3), dtype=np.uint8)
        result = evaluate_semantic_row_overlap(
            image,
            image.copy(),
            620,
            166.5,
            prev_row_centers=[690.0],
            candidate_row_centers=[70.0],
        )
        self.assertTrue(result["visual_overlap"])
        self.assertEqual(result["physical_overlap_px"], 140)
        self.assertEqual(result["semantic_overlap_state"], "definitely_no_full_row")
        self.assertFalse(result["ocr_overlap_pair_required"])

    def test_semantic_overlap_marks_complete_row_in_both_shared_regions(self):
        image = np.zeros((760, 240, 3), dtype=np.uint8)
        result = evaluate_semantic_row_overlap(
            image,
            image.copy(),
            560,
            166.5,
            prev_row_centers=[650.0],
            candidate_row_centers=[90.0],
        )
        self.assertTrue(result["visual_overlap"])
        self.assertEqual(result["semantic_overlap_state"], "definitely_full_row")
        self.assertTrue(result["ocr_overlap_pair_required"])
        self.assertTrue(result["full_row_candidates"])

    def test_semantic_overlap_preserves_ambiguous_boundary_conservatively(self):
        image = np.zeros((760, 240, 3), dtype=np.uint8)
        result = evaluate_semantic_row_overlap(
            image,
            image.copy(),
            560,
            166.5,
            prev_row_centers=[625.0],
            candidate_row_centers=[65.0],
        )
        self.assertEqual(result["semantic_overlap_state"], "ambiguous")
        self.assertTrue(result["ocr_overlap_pair_required"])
        self.assertEqual(result["reason"], "envelope_near_shared_region_boundary")

    def test_same_physical_overlap_can_have_different_semantic_row_phase(self):
        image = np.zeros((760, 240, 3), dtype=np.uint8)
        complete = evaluate_semantic_row_overlap(
            image, image.copy(), 560, 166.5,
            prev_row_centers=[650.0], candidate_row_centers=[90.0],
        )
        partial = evaluate_semantic_row_overlap(
            image, image.copy(), 560, 166.5,
            prev_row_centers=[700.0], candidate_row_centers=[140.0],
        )
        self.assertEqual(complete["physical_overlap_px"], partial["physical_overlap_px"])
        self.assertTrue(complete["ocr_overlap_pair_required"])
        self.assertFalse(partial["ocr_overlap_pair_required"])

    def test_row_lattice_estimates_current_frame_phase_from_visual_edges(self):
        image = np.zeros((760, 240, 3), dtype=np.uint8)
        pitch = 166.5
        radius = pitch * 0.34
        expected_phase = 80.0
        for center in np.arange(expected_phase, image.shape[0], pitch):
            for offset in (-radius, radius, -radius * 0.77, radius * 1.39):
                y = int(round(center + offset))
                if 0 <= y < image.shape[0]:
                    cv2.line(image, (0, y), (image.shape[1] - 1, y), (255, 255, 255), 2)
        lattice = estimate_row_lattice(image, pitch)
        self.assertAlmostEqual(lattice["phase_px"], expected_phase, delta=3)
        self.assertGreaterEqual(len(lattice["row_centers"]), 4)

    def test_orb_ransac_recovers_known_vertical_motion(self):
        before = _complex_scene(seed=101)
        estimate = estimate_vertical_motion(before, _shift_up(before, 118, seed=102))
        self.assertAlmostEqual(estimate.shift_y, 118, delta=4)
        self.assertGreaterEqual(estimate.inlier_count, 8)
        self.assertGreater(estimate.confidence, 0.20)

    def test_orb_estimate_does_not_jump_to_repeated_background_period(self):
        height, width, period, shift = 360, 240, 45, 97
        tile = _complex_scene(height=period, width=width, seed=201)
        before = np.tile(tile, (height // period + 1, 1, 1))[:height].copy()
        cv2.putText(before, "UNIQUE-A", (18, 118), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        cv2.rectangle(before, (160, 210), (215, 260), (17, 243, 91), -1)
        after = _shift_up(before, shift, seed=202)
        estimate = estimate_vertical_motion(before, after)
        self.assertAlmostEqual(estimate.shift_y, shift, delta=5)
        self.assertGreater(estimate.confidence, 0.20)

    def test_hypothesis_clustering_selects_true_large_positive_motion(self):
        before = _periodic_scene_with_unique_tail()
        actual_shift = 560
        after = _shift_up(before, actual_shift, seed=702)
        estimate = estimate_vertical_motion(before, after, (250, 700))
        self.assertAlmostEqual(estimate.shift_y, actual_shift, delta=7)
        self.assertIsNotNone(estimate.selected_hypothesis)
        self.assertGreater(len(estimate.motion_hypotheses), 1)
        self.assertGreater(estimate.selected_hypothesis["match_count"], 4)

    def test_reverse_motion_alias_is_rejected_before_hypothesis_selection(self):
        before = np.random.default_rng(711).integers(
            0, 256, size=(480, 240, 3), dtype=np.uint8
        )
        downward = np.vstack(
            [
                np.random.default_rng(712).integers(
                    0, 256, size=(100, 240, 3), dtype=np.uint8
                ),
                before[:-100, :, :],
            ]
        )
        estimate = estimate_vertical_motion(before, downward, (25, 400))
        self.assertLessEqual(estimate.confidence, 0.01)
        self.assertIsNone(estimate.selected_hypothesis)
        self.assertGreater(estimate.direction_rejected_match_count, 0)

    def test_out_of_range_local_confirmation_is_explicitly_invalid(self):
        image = _complex_scene(seed=721)
        score, shift, valid = local_overlap_confirmation(image, image, -70, 20)
        self.assertIsNone(score)
        self.assertIsNone(shift)
        self.assertFalse(valid)

    def test_identical_image_has_dual_no_move_evidence(self):
        image = _complex_scene(seed=301)
        result = evaluate_feedback_candidate(image, image.copy(), _feedback_config())
        self.assertGreater(result["same_position_score"], 0.99)
        self.assertLess(abs(result["shift_estimate"]["shift_y"]), 3)
        self.assertEqual(result["reason"], "bottom_no_move")
        self.assertEqual(result["semantic_overlap_state"], "not_applicable_no_move")
        self.assertFalse(result["ocr_overlap_pair_required"])

    def test_unrelated_image_is_rejected(self):
        first = np.random.default_rng(401).integers(
            0, 256, size=(360, 240, 3), dtype=np.uint8
        )
        second = np.random.default_rng(402).integers(
            0, 256, size=(360, 240, 3), dtype=np.uint8
        )
        result = evaluate_feedback_candidate(
            first, second, _feedback_config()
        )
        self.assertFalse(result["accepted"])
        self.assertLess(result["shift_estimate"]["confidence"], 0.35)
        self.assertEqual(result["reason"], "unsafe_gap_risk")
        self.assertEqual(
            result["semantic_overlap_state"],
            "not_applicable_unreliable_motion",
        )
        self.assertFalse(result["ocr_overlap_pair_required"])
        self.assertEqual(result["full_row_candidates"], [])
        self.assertEqual(
            result["semantic_overlap_reason"],
            "unreliable_motion_not_an_adjacent_pair",
        )
        self.assertIsNone(result["relation"])

    def test_unrelated_full_probe_has_no_image_pair(self):
        prev = np.random.default_rng(411).integers(
            0, 256, size=(360, 240, 3), dtype=np.uint8
        )
        unrelated = np.random.default_rng(412).integers(
            0, 256, size=(360, 240, 3), dtype=np.uint8
        )
        params = {
            "mode": "feedback_probe",
            "debug_dir": "unused",
            "compare_roi": [0, 0, 240, 360],
            "coarse_swipe": {
                "start": [360, 930], "end": [360, 560], "duration_ms": 700
            },
            "micro_swipe": {
                "start": [360, 930], "end": [360, 800], "duration_ms": 500
            },
            "settle_ms": 0,
            "feedback": _feedback_config(),
        }
        with tempfile.TemporaryDirectory() as directory:
            params["debug_dir"] = directory
            result = StarBackpackCaptureProbe().run(
                _FakeCaptureContext([prev, unrelated]),
                SimpleNamespace(custom_action_param=params),
            )
            self.assertTrue(getattr(result, "success", False))
            run_dir = next(Path(directory).iterdir())
            metrics = json.loads(
                (run_dir / "feedback-metrics.json").read_text(encoding="utf-8")
            )
        self.assertFalse(metrics["accepted"])
        self.assertEqual(
            metrics["semantic_overlap_state"],
            "not_applicable_unreliable_motion",
        )
        self.assertFalse(metrics["ocr_overlap_pair_required"])
        self.assertIsNone(metrics["relation"])
        self.assertIsNone(metrics["image_pair"])

    def test_terminal_confirmation_accepts_temporary_candidate_at_bottom(self):
        prev = _complex_scene(seed=501)
        first_candidate = _shift_up(prev, 55, seed=502)
        params = {
            "mode": "feedback_probe",
            "debug_dir": "unused",
            "compare_roi": [0, 0, 240, 360],
            "coarse_swipe": {
                "start": [360, 930], "end": [360, 560], "duration_ms": 700
            },
            "micro_swipe": {
                "start": [360, 930], "end": [360, 800], "duration_ms": 500
            },
            "settle_ms": 0,
            "feedback": _feedback_config(),
        }
        with tempfile.TemporaryDirectory() as directory:
            params["debug_dir"] = directory
            context = _FakeCaptureContext([prev, first_candidate, first_candidate])
            result = StarBackpackCaptureProbe().run(
                context, SimpleNamespace(custom_action_param=params)
            )
            self.assertTrue(getattr(result, "success", False))
            run_dir = next(Path(directory).iterdir())
            metrics = json.loads(
                (run_dir / "feedback-metrics.json").read_text(encoding="utf-8")
            )
            self.assertTrue(metrics["accepted"])
            self.assertEqual(metrics["relation"], "overlap")
            self.assertTrue(metrics["ocr_overlap_pair_required"])
            self.assertIsNotNone(metrics["image_pair"])
            self.assertEqual(metrics["efficiency_status"], "terminal_partial")
            self.assertTrue(metrics["terminal_partial_confirmed"])
            self.assertEqual(len(metrics["attempts"]), 2)
            self.assertIn("motion_hypotheses", metrics["shift_estimate"])
            self.assertIn("selected_hypothesis", metrics["shift_estimate"])
            self.assertIn("direction_rejected_match_count", metrics["shift_estimate"])
            self.assertTrue(metrics["local_overlap_valid"])
            self.assertEqual(len(context.tasker.controller.swipes), 2)
            self.assertTrue((run_dir / "prev.png").is_file())
            self.assertTrue((run_dir / "candidate.png").is_file())

    def test_feedback_accepts_safe_candidate_and_rejects_unsafe_overshoot(self):
        prev = _complex_scene(seed=601)
        params = {
            "mode": "feedback_probe",
            "debug_dir": "unused",
            "compare_roi": [0, 0, 240, 360],
            "coarse_swipe": {
                "start": [360, 930], "end": [360, 560], "duration_ms": 700
            },
            "micro_swipe": {
                "start": [360, 930], "end": [360, 800], "duration_ms": 500
            },
            "settle_ms": 0,
            "feedback": _feedback_config(),
        }
        for candidate, expected_accepted, expected_reason in (
            (_shift_up(prev, 160, seed=602), True, "diagnostic_only"),
            (_shift_up(prev, 275, seed=603), False, "unsafe_gap_risk"),
        ):
            with self.subTest(expected_accepted=expected_accepted):
                with tempfile.TemporaryDirectory() as directory:
                    params["debug_dir"] = directory
                    context = _FakeCaptureContext([prev, candidate])
                    result = StarBackpackCaptureProbe().run(
                        context, SimpleNamespace(custom_action_param=params)
                    )
                    self.assertTrue(getattr(result, "success", False))
                    run_dir = next(Path(directory).iterdir())
                    metrics = json.loads(
                        (run_dir / "feedback-metrics.json").read_text(encoding="utf-8")
                    )
                    self.assertEqual(metrics["accepted"], expected_accepted)
                    self.assertEqual(metrics["reason"], expected_reason)
                    self.assertEqual(len(context.tasker.controller.swipes), 1)

    def test_correct_large_shift_still_rejects_outside_safe_range(self):
        before = _periodic_scene_with_unique_tail()
        candidate = _shift_up(before, 560, seed=731)
        feedback = _feedback_config(safe_min=140, safe_max=520)
        feedback["diagnostic_expected_shift_px"] = (250, 700)
        result = evaluate_feedback_candidate(before, candidate, feedback)
        self.assertGreater(result["shift_estimate"]["shift_y"], 540)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["reason"], "unsafe_gap_risk")

    def test_normal_motion_band_selects_each_locked_real_distribution(self):
        before = np.random.default_rng(801).integers(
            0, 256, size=(760, 260, 3), dtype=np.uint8
        )
        for shift, seed in ((596, 802), (622, 803), (640, 804)):
            with self.subTest(shift=shift):
                estimate = estimate_vertical_motion(
                    before,
                    _shift_up(before, shift, seed=seed),
                    (250, 700),
                    (30, 700),
                )
                self.assertAlmostEqual(estimate.shift_y, shift, delta=6)
                self.assertGreater(estimate.confidence, 0.20)
                self.assertEqual(
                    estimate.selected_hypothesis["selection_mode"],
                    "normal_motion_full_overlap",
                )
                self.assertFalse(estimate.selected_hypothesis["fallback_used"])

    def test_near_bottom_strong_230_hypothesis_beats_weak_expected_396_hypothesis(self):
        strong_near_bottom = MotionHypothesis(
            matches=[object()] * 175,
            shift_y=230.0,
            median_abs_deviation=1.0,
            x_coverage=0.80,
            y_coverage=0.70,
            mean_descriptor_distance=24.0,
        )
        weak_expected = MotionHypothesis(
            matches=[object()] * 12,
            shift_y=396.0,
            median_abs_deviation=1.5,
            x_coverage=0.35,
            y_coverage=0.30,
            mean_descriptor_distance=45.0,
        )
        selected, reason, hypotheses = select_motion_hypothesis(
            [strong_near_bottom, weak_expected], (250, 700), (30, 700)
        )
        self.assertIs(selected, strong_near_bottom)
        self.assertFalse(reason["inside_legacy_expected_range"])
        self.assertEqual(reason["selection_mode"], "terminal_fallback")
        self.assertTrue(reason["fallback_used"])
        self.assertEqual(reason["match_count"], 175)
        self.assertEqual(len(hypotheses), 2)

    def test_normal_band_gate_beats_higher_count_low_periodic_alias(self):
        low_alias = MotionHypothesis(
            matches=[object()] * 220,
            shift_y=289.0,
            median_abs_deviation=0.5,
            x_coverage=0.95,
            y_coverage=0.80,
            mean_descriptor_distance=12.0,
            anchor_score=0.94,
            anchor_height_px=120,
            full_overlap_score=0.99,
            full_overlap_height_px=459,
            full_overlap_gray_score=0.99,
            full_overlap_gradient_score=0.99,
        )
        true_normal = MotionHypothesis(
            matches=[object()] * 12,
            shift_y=622.0,
            median_abs_deviation=1.0,
            x_coverage=0.40,
            y_coverage=0.35,
            mean_descriptor_distance=45.0,
            anchor_score=0.87,
            anchor_height_px=120,
            full_overlap_score=0.81,
            full_overlap_height_px=126,
            full_overlap_gray_score=0.81,
            full_overlap_gradient_score=0.81,
        )
        selected, reason, _ = select_motion_hypothesis(
            [low_alias, true_normal], (250, 700), (30, 700)
        )
        self.assertIs(selected, true_normal)
        self.assertEqual(reason["selection_mode"], "normal_motion_full_overlap")
        self.assertEqual(reason["normal_motion_candidate_count"], 1)
        self.assertEqual(reason["selected_by"], "full_overlap_score")

    def test_direct_normal_candidate_wins_with_zero_orb_feature_support(self):
        low_alias = MotionHypothesis(
            matches=[object()] * 220,
            shift_y=318.0,
            median_abs_deviation=0.5,
            x_coverage=0.95,
            y_coverage=0.80,
            mean_descriptor_distance=12.0,
            anchor_score=0.94,
            anchor_height_px=120,
            full_overlap_score=0.99,
            full_overlap_height_px=430,
            full_overlap_gray_score=0.99,
            full_overlap_gradient_score=0.99,
        )
        direct_true = MotionHypothesis(
            matches=[],
            shift_y=640.0,
            median_abs_deviation=0.0,
            x_coverage=1.0,
            y_coverage=1.0,
            mean_descriptor_distance=None,
            anchor_score=0.89,
            anchor_height_px=108,
            full_overlap_score=0.88,
            full_overlap_height_px=108,
            full_overlap_gray_score=0.87,
            full_overlap_gradient_score=0.89,
            proposal_source="direct_normal_band",
        )
        selected, reason, _ = select_motion_hypothesis(
            [low_alias, direct_true], (250, 700), (30, 700)
        )
        self.assertIs(selected, direct_true)
        self.assertEqual(reason["proposal_source"], "direct_normal_band")
        self.assertEqual(reason["match_count"], 0)
        self.assertEqual(reason["mean_descriptor_distance"], None)

    def test_direct_search_supplements_orb_only_low_periodic_aliases(self):
        before = np.random.default_rng(807).integers(
            0, 256, size=(760, 240, 3), dtype=np.uint8
        )
        after = _shift_up(before, 622, seed=808)
        aliases = [
            MotionHypothesis(
                matches=[object()] * count,
                shift_y=float(shift),
                median_abs_deviation=1.0,
                x_coverage=0.80,
                y_coverage=0.70,
                mean_descriptor_distance=24.0,
            )
            for shift, count in ((151, 90), (318, 60), (484, 35))
        ]
        with mock.patch.object(
            _MODULE, "_cluster_positive_vertical_matches", return_value=aliases
        ):
            estimate = estimate_vertical_motion(before, after, (250, 700), (30, 700))
        self.assertAlmostEqual(estimate.shift_y, 622, delta=2)
        self.assertEqual(
            estimate.selected_hypothesis["proposal_source"], "direct_normal_band"
        )
        self.assertEqual(
            estimate.selected_hypothesis["selection_mode"],
            "normal_motion_full_overlap",
        )
        self.assertTrue(estimate.direct_normal_search["candidate_injected"])
        self.assertLess(estimate.direct_normal_search["elapsed_ms"], 200)

    def test_direct_candidate_dedupes_against_existing_orb_normal_branch(self):
        before = np.random.default_rng(809).integers(
            0, 256, size=(760, 240, 3), dtype=np.uint8
        )
        direct, diagnostics = find_direct_normal_band_candidate(
            before, _shift_up(before, 622, seed=810)
        )
        self.assertIsNotNone(direct)
        self.assertTrue(diagnostics["candidate_injected"])
        orb_true = MotionHypothesis(
            matches=[object()] * 12,
            shift_y=622.0,
            median_abs_deviation=1.0,
            x_coverage=0.40,
            y_coverage=0.35,
            mean_descriptor_distance=45.0,
        )
        merged = merge_direct_normal_candidate([orb_true], direct)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].proposal_source, "merged")
        self.assertEqual(len(merged[0].matches), 12)
        self.assertAlmostEqual(merged[0].shift_y, direct.shift_y, delta=0.01)

    def test_sparse_merged_direct_candidates_keep_normal_motion_eligibility(self):
        cases = (
            (625, 2, 125, 913),
            (601, 1, 268, 914),
        )
        for shift, orb_match_count, alias_shift, seed in cases:
            with self.subTest(shift=shift, orb_match_count=orb_match_count):
                before = _complex_scene(height=760, width=240, seed=seed)
                after = _shift_up(before, shift, seed=seed + 100)
                sparse_orb = MotionHypothesis(
                    matches=[object()] * orb_match_count,
                    shift_y=float(shift),
                    median_abs_deviation=1.0,
                    x_coverage=0.40,
                    y_coverage=0.35,
                    mean_descriptor_distance=45.0,
                )
                periodic_alias = MotionHypothesis(
                    matches=[object()] * 20,
                    shift_y=float(alias_shift),
                    median_abs_deviation=1.0,
                    x_coverage=0.70,
                    y_coverage=0.70,
                    mean_descriptor_distance=24.0,
                )
                with mock.patch.object(
                    _MODULE,
                    "_cluster_positive_vertical_matches",
                    return_value=[periodic_alias, sparse_orb],
                ):
                    estimate = estimate_vertical_motion(
                        before, after, (25, 700), (30, 700)
                    )
                self.assertAlmostEqual(estimate.shift_y, shift, delta=2)
                self.assertEqual(
                    estimate.selected_hypothesis["proposal_source"], "merged"
                )
                self.assertEqual(
                    estimate.selected_hypothesis["match_count"], orb_match_count
                )
                self.assertEqual(
                    estimate.selected_hypothesis["selection_mode"],
                    "normal_motion_full_overlap",
                )
                self.assertFalse(estimate.selected_hypothesis["fallback_used"])
                self.assertTrue(estimate.direct_normal_search["candidate_injected"])

    def test_merged_without_validated_direct_support_stays_out_of_normal_pool(self):
        alias = MotionHypothesis(
            matches=[object()] * 20,
            shift_y=268.0,
            median_abs_deviation=1.0,
            x_coverage=0.70,
            y_coverage=0.70,
            mean_descriptor_distance=24.0,
        )
        merged_without_direct = MotionHypothesis(
            matches=[object()],
            shift_y=601.0,
            median_abs_deviation=1.0,
            x_coverage=0.40,
            y_coverage=0.35,
            mean_descriptor_distance=45.0,
            anchor_score=0.96,
            anchor_height_px=120,
            full_overlap_score=0.95,
            full_overlap_height_px=147,
            full_overlap_gray_score=0.95,
            full_overlap_gradient_score=0.95,
            proposal_source="merged",
        )
        selected, reason, _ = select_motion_hypothesis(
            [alias, merged_without_direct],
            (25, 700),
            (30, 700),
            {
                "candidate_injected": False,
                "best_shift_px": 601,
                "best_score": 0.95,
            },
        )
        self.assertIsNotNone(selected)
        self.assertEqual(reason["normal_motion_candidate_count"], 0)
        self.assertEqual(reason["selection_mode"], "terminal_fallback")
        self.assertTrue(reason["fallback_used"])

    def test_direct_normal_search_does_not_inject_for_terminal_or_no_move(self):
        before = np.random.default_rng(811).integers(
            0, 256, size=(760, 240, 3), dtype=np.uint8
        )
        for candidate in (before.copy(), _shift_up(before, 200, seed=812)):
            with self.subTest(candidate="no_move" if candidate is before else "terminal"):
                direct, diagnostics = find_direct_normal_band_candidate(before, candidate)
                self.assertIsNone(direct)
                self.assertFalse(diagnostics["candidate_injected"])

    def test_full_overlap_requires_at_least_eighty_shared_pixels(self):
        before = np.random.default_rng(805).integers(
            0, 256, size=(760, 240, 3), dtype=np.uint8
        )
        after = _shift_up(before, 690, seed=806)
        insufficient = MotionHypothesis(
            matches=[object()] * 8,
            shift_y=690.0,
            median_abs_deviation=1.0,
            x_coverage=0.50,
            y_coverage=0.50,
            mean_descriptor_distance=30.0,
        )
        apply_direct_overlap_anchors([insufficient], before, after)
        self.assertIsNone(insufficient.full_overlap_score)
        self.assertEqual(insufficient.full_overlap_height_px, 0)

    def test_semantic_zero_overlap_target_keeps_visual_overlap_out_of_ocr_pair(self):
        before = np.random.default_rng(811).integers(
            0, 256, size=(720, 260, 3), dtype=np.uint8
        )
        target = evaluate_feedback_candidate(
            before, _shift_up(before, 620, seed=812), _b1d_feedback_config()
        )
        self.assertTrue(target["accepted"])
        self.assertEqual(target["efficiency_status"], "semantic_zero_overlap_target")
        self.assertGreater(target["physical_overlap_px"], 0)
        self.assertTrue(target["visual_overlap"])
        self.assertFalse(target["ocr_overlap_pair_required"])
        self.assertIsNone(target["relation"])
        self.assertEqual(target["target_shift_range"], [610, 630])
        self.assertEqual(target["safe_shift_range"], [560, 650])
        self.assertEqual(target["physical_shift_range"], [30, 700])

    def test_case_a_593px_keeps_semantic_zero_overlap(self):
        before = _complex_scene(height=760, width=240, seed=921)
        result = evaluate_feedback_candidate(
            before, _shift_up(before, 593, seed=922), _b1d_feedback_config()
        )
        self.assertAlmostEqual(result["actual_shift_px"], 593, delta=3)
        self.assertEqual(
            result["semantic_overlap_state"], "definitely_no_full_row"
        )
        self.assertFalse(result["ocr_overlap_pair_required"])

    def test_normal_acceptance_allows_one_pixel_estimation_boundary(self):
        before = _complex_scene(height=760, width=240, seed=941)
        candidate = _shift_up(before, 600, seed=942)
        estimate = estimate_vertical_motion(before, candidate, (250, 700), (30, 700))
        for measured_shift in (599.6, 599.0):
            with self.subTest(measured_shift=measured_shift):
                with mock.patch.object(
                    _MODULE,
                    "estimate_vertical_motion",
                    return_value=replace(estimate, shift_y=measured_shift),
                ):
                    result = evaluate_feedback_candidate(
                        before, candidate, _b1d_feedback_config()
                    )
                self.assertTrue(result["accepted"])
                self.assertEqual(result["reason"], "diagnostic_only")
                self.assertEqual(
                    result["efficiency_status"], "semantic_zero_overlap_acceptable"
                )

    def test_normal_acceptance_epsilon_does_not_admit_596px(self):
        before = _complex_scene(height=760, width=240, seed=951)
        result = evaluate_feedback_candidate(
            before, _shift_up(before, 596, seed=952), _b1d_feedback_config()
        )
        self.assertFalse(result["accepted"])
        self.assertEqual(result["reason"], "efficiency_correction_required")
        self.assertEqual(result["efficiency_status"], "conservative")

    def test_feedback_metrics_keep_only_unique_motion_diagnostics(self):
        before = _complex_scene(height=760, width=240, seed=931)
        result = evaluate_feedback_candidate(
            before, _shift_up(before, 620, seed=932), _b1d_feedback_config()
        )
        for removed in (
            "motion_hypotheses",
            "selected_hypothesis",
            "direction_rejected_match_count",
            "direct_normal_search",
            "visual_overlap_px",
            "prev_row_centers",
            "candidate_row_centers",
            "anchor_score",
            "selected_hypothesis_reason",
        ):
            self.assertNotIn(removed, result)
        self.assertIn("motion_hypotheses", result["shift_estimate"])
        self.assertIn("selected_hypothesis", result["shift_estimate"])
        self.assertIn("direct_normal_search", result["shift_estimate"])
        for retained in (
            "motion_reliability",
            "actual_shift_px",
            "true_shift_rows",
            "physical_overlap_px",
            "semantic_overlap_state",
            "ocr_overlap_pair_required",
            "full_row_candidates",
            "accepted",
            "reason",
        ):
            self.assertIn(retained, result)

    def test_low_orb_confidence_with_strong_merged_direct_evidence_is_reliable(self):
        before = _complex_scene(height=760, width=240, seed=901)
        candidate = _shift_up(before, 620, seed=902)
        estimate = estimate_vertical_motion(before, candidate, (250, 700), (30, 700))
        self.assertEqual(estimate.selected_hypothesis["proposal_source"], "merged")
        self.assertEqual(
            estimate.selected_hypothesis["selection_mode"],
            "normal_motion_full_overlap",
        )
        self.assertTrue(estimate.direct_normal_search["candidate_injected"])
        low_orb_confidence = replace(estimate, confidence=0.01)
        with mock.patch.object(
            _MODULE, "estimate_vertical_motion", return_value=low_orb_confidence
        ):
            result = evaluate_feedback_candidate(
                before, candidate, _b1d_feedback_config()
            )
        self.assertTrue(result["accepted"])
        self.assertNotEqual(
            result["semantic_overlap_state"], "not_applicable_unreliable_motion"
        )
        self.assertFalse(result["motion_reliability"]["orb_confidence_passed"])
        self.assertTrue(
            result["motion_reliability"]["direct_normal_evidence_passed"]
        )
        self.assertTrue(result["motion_reliability"]["reliable"])
        self.assertEqual(
            result["motion_reliability"]["mode"], "direct_normal_full_overlap"
        )
        self.assertFalse(result["ocr_overlap_pair_required"])
        self.assertIsNone(result["relation"])

    def test_low_confidence_without_strong_direct_evidence_remains_unreliable(self):
        before = _complex_scene(height=760, width=240, seed=911)
        candidate = _shift_up(before, 620, seed=912)
        estimate = estimate_vertical_motion(before, candidate, (250, 700), (30, 700))
        weakened_hypothesis = {
            **estimate.selected_hypothesis,
            "proposal_source": "orb",
        }
        weakened = replace(
            estimate,
            confidence=0.01,
            selected_hypothesis=weakened_hypothesis,
        )
        with mock.patch.object(
            _MODULE, "estimate_vertical_motion", return_value=weakened
        ):
            result = evaluate_feedback_candidate(
                before, candidate, _b1d_feedback_config()
            )
        self.assertFalse(result["accepted"])
        self.assertEqual(
            result["semantic_overlap_state"],
            "not_applicable_unreliable_motion",
        )
        self.assertEqual(result["motion_reliability"]["mode"], "unreliable")
        self.assertFalse(result["motion_reliability"]["reliable"])
        self.assertFalse(
            result["motion_reliability"]["direct_normal_evidence_passed"]
        )
        self.assertFalse(result["ocr_overlap_pair_required"])
        self.assertIsNone(result["relation"])

    def test_direct_anchor_resolves_periodic_alias_in_favor_of_true_shift(self):
        before = np.random.default_rng(814).integers(
            0, 256, size=(760, 240, 3), dtype=np.uint8
        )
        after = _shift_up(before, 522, seed=815)
        periodic_alias = MotionHypothesis(
            matches=[object()] * 220,
            shift_y=356.0,
            median_abs_deviation=1.0,
            x_coverage=0.90,
            y_coverage=0.90,
            mean_descriptor_distance=15.0,
        )
        true_shift = MotionHypothesis(
            matches=[object()] * 12,
            shift_y=522.0,
            median_abs_deviation=1.0,
            x_coverage=0.35,
            y_coverage=0.35,
            mean_descriptor_distance=45.0,
        )
        hypotheses = [periodic_alias, true_shift]
        apply_direct_overlap_anchors(hypotheses, before, after)
        selected, reason, _ = select_motion_hypothesis(hypotheses, (250, 700), (30, 700))
        self.assertIs(selected, true_shift)
        self.assertGreater(true_shift.anchor_score, periodic_alias.anchor_score)
        self.assertEqual(reason["anchor_score"], true_shift.anchor_score)

    def test_efficiency_risk_gets_one_micro_retry_from_original_prev(self):
        prev = np.random.default_rng(816).integers(
            0, 256, size=(760, 240, 3), dtype=np.uint8
        )
        under_advanced = _shift_up(prev, 560, seed=817)
        corrected = _shift_up(prev, 620, seed=818)
        params = {
            "mode": "feedback_probe",
            "debug_dir": "unused",
            "compare_roi": [0, 0, 240, 760],
            "coarse_swipe": {
                "start": [360, 930], "end": [360, 470], "duration_ms": 700
            },
            "micro_swipe": {
                "start": [360, 930], "end": [360, 800], "duration_ms": 500
            },
            "settle_ms": 0,
            "feedback": _b1d_feedback_config(),
        }
        initial = evaluate_feedback_candidate(prev, under_advanced, params["feedback"])
        self.assertEqual(initial["reason"], "efficiency_correction_required")
        with tempfile.TemporaryDirectory() as directory:
            params["debug_dir"] = directory
            context = _FakeCaptureContext([prev, under_advanced, corrected])
            result = StarBackpackCaptureProbe().run(
                context, SimpleNamespace(custom_action_param=params)
            )
            self.assertTrue(getattr(result, "success", False))
            run_dir = next(Path(directory).iterdir())
            metrics = json.loads(
                (run_dir / "feedback-metrics.json").read_text(encoding="utf-8")
            )
            self.assertTrue(metrics["accepted"])
            self.assertEqual(metrics["efficiency_status"], "semantic_zero_overlap_target")
            self.assertFalse(metrics["ocr_overlap_pair_required"])
            self.assertIsNone(metrics["image_pair"])
            self.assertEqual([item["stage"] for item in metrics["attempts"]], ["coarse", "efficiency_micro"])
            self.assertEqual(len(context.tasker.controller.swipes), 2)

    def test_single_swipe_calibration_ends_after_coarse_for_every_diagnostic_reason(self):
        calibration_cases = (
            (
                "efficiency_correction_required",
                np.random.default_rng(816).integers(
                    0, 256, size=(760, 240, 3), dtype=np.uint8
                ),
                560,
                817,
            ),
            (
                "terminal_partial_candidate",
                _complex_scene(height=480, width=240, seed=853),
                200,
                854,
            ),
            (
                "unsafe_gap_risk",
                np.random.default_rng(855).integers(
                    0, 256, size=(720, 240, 3), dtype=np.uint8
                ),
                660,
                856,
            ),
            (
                "bottom_no_move",
                _complex_scene(height=480, width=240, seed=857),
                0,
                858,
            ),
        )
        for expected_reason, prev, shift, seed in calibration_cases:
            with self.subTest(reason=expected_reason):
                candidate = (
                    prev.copy() if shift == 0 else _shift_up(prev, shift, seed=seed)
                )
                height, width = prev.shape[:2]
                params = {
                    "mode": "feedback_probe",
                    "single_swipe_calibration": True,
                    "debug_dir": "unused",
                    "compare_roi": [0, 0, width, height],
                    "coarse_swipe": {
                        "start": [360, 930], "end": [360, 500], "duration_ms": 700
                    },
                    "micro_swipe": {
                        "start": [360, 930], "end": [360, 800], "duration_ms": 500
                    },
                    "settle_ms": 0,
                    "feedback": _b1d_feedback_config(),
                }
                with tempfile.TemporaryDirectory() as directory:
                    params["debug_dir"] = directory
                    context = _FakeCaptureContext([prev, candidate, candidate])
                    result = StarBackpackCaptureProbe().run(
                        context, SimpleNamespace(custom_action_param=params)
                    )
                    self.assertTrue(getattr(result, "success", False))
                    run_dir = next(Path(directory).iterdir())
                    metrics = json.loads(
                        (run_dir / "feedback-metrics.json").read_text(encoding="utf-8")
                    )
                    self.assertEqual(metrics["reason"], expected_reason)
                    self.assertTrue(metrics["single_swipe_calibration"])
                    self.assertEqual(metrics["gesture_count"], 1)
                    self.assertEqual([item["stage"] for item in metrics["attempts"]], ["coarse"])
                    self.assertEqual(len(context.tasker.controller.swipes), 1)
                    self.assertTrue((run_dir / "prev.png").is_file())
                    self.assertTrue((run_dir / "prev-roi.png").is_file())
                    self.assertTrue((run_dir / "candidate.png").is_file())
                    self.assertTrue((run_dir / "candidate-roi.png").is_file())

    def test_reliable_small_positive_motion_is_terminal_partial_candidate(self):
        before = _complex_scene(height=480, width=240, seed=821)
        result = evaluate_feedback_candidate(
            before, _shift_up(before, 200, seed=822), _b1d_feedback_config()
        )
        self.assertFalse(result["accepted"])
        self.assertEqual(result["reason"], "terminal_partial_candidate")
        self.assertEqual(result["efficiency_status"], "terminal_partial")
        self.assertIn(
            result["semantic_overlap_state"],
            {"definitely_no_full_row", "ambiguous", "definitely_full_row"},
        )

    def test_terminal_partial_is_accepted_only_after_no_move_confirmation(self):
        prev = _complex_scene(height=480, width=240, seed=831)
        partial = _shift_up(prev, 200, seed=832)
        params = {
            "mode": "feedback_probe",
            "debug_dir": "unused",
            "compare_roi": [0, 0, 240, 480],
            "coarse_swipe": {
                "start": [360, 930], "end": [360, 600], "duration_ms": 700
            },
            "micro_swipe": {
                "start": [360, 930], "end": [360, 800], "duration_ms": 500
            },
            "settle_ms": 0,
            "feedback": _b1d_feedback_config(),
        }
        with tempfile.TemporaryDirectory() as directory:
            params["debug_dir"] = directory
            context = _FakeCaptureContext([prev, partial, partial])
            result = StarBackpackCaptureProbe().run(
                context, SimpleNamespace(custom_action_param=params)
            )
            self.assertTrue(getattr(result, "success", False))
            run_dir = next(Path(directory).iterdir())
            metrics = json.loads(
                (run_dir / "feedback-metrics.json").read_text(encoding="utf-8")
            )
            self.assertTrue(metrics["accepted"])
            self.assertTrue(metrics["terminal_partial_confirmed"])
            self.assertTrue(metrics["section_complete"])
            self.assertTrue((run_dir / "candidate.png").is_file())
            self.assertFalse((run_dir / "candidate-02.png").exists())

    def test_terminal_confirmation_omits_relation_without_semantic_pair(self):
        prev = _complex_scene(height=760, width=240, seed=834)
        partial = _shift_up(prev, 650, seed=835)
        feedback = _b1d_feedback_config()
        feedback["diagnostic_safe_shift_px"] = (700, 710)
        feedback["diagnostic_normal_safe_shift_px"] = (700, 710)
        feedback["diagnostic_micro_trigger_shift_px"] = 700
        params = {
            "mode": "feedback_probe",
            "debug_dir": "unused",
            "compare_roi": [0, 0, 240, 760],
            "coarse_swipe": {
                "start": [360, 930], "end": [360, 600], "duration_ms": 700
            },
            "micro_swipe": {
                "start": [360, 930], "end": [360, 800], "duration_ms": 500
            },
            "settle_ms": 0,
            "feedback": feedback,
        }
        with tempfile.TemporaryDirectory() as directory:
            params["debug_dir"] = directory
            context = _FakeCaptureContext([prev, partial, partial])
            result = StarBackpackCaptureProbe().run(
                context, SimpleNamespace(custom_action_param=params)
            )
            self.assertTrue(getattr(result, "success", False))
            run_dir = next(Path(directory).iterdir())
            metrics = json.loads(
                (run_dir / "feedback-metrics.json").read_text(encoding="utf-8")
            )
        self.assertTrue(metrics["accepted"])
        self.assertTrue(metrics["terminal_partial_confirmed"])
        self.assertFalse(metrics["ocr_overlap_pair_required"])
        self.assertIsNone(metrics["relation"])
        self.assertIsNone(metrics["image_pair"])

    def test_terminal_confirmation_that_moves_rejoins_normal_feedback(self):
        prev = _complex_scene(height=720, width=240, seed=836)
        partial = _shift_up(prev, 200, seed=837)
        normal_candidate = _shift_up(prev, 620, seed=838)
        params = {
            "mode": "feedback_probe",
            "debug_dir": "unused",
            "compare_roi": [0, 0, 240, 720],
            "coarse_swipe": {
                "start": [360, 930], "end": [360, 600], "duration_ms": 700
            },
            "micro_swipe": {
                "start": [360, 930], "end": [360, 800], "duration_ms": 500
            },
            "settle_ms": 0,
            "feedback": _b1d_feedback_config(),
        }
        with tempfile.TemporaryDirectory() as directory:
            params["debug_dir"] = directory
            context = _FakeCaptureContext([prev, partial, normal_candidate])
            result = StarBackpackCaptureProbe().run(
                context, SimpleNamespace(custom_action_param=params)
            )
            self.assertTrue(getattr(result, "success", False))
            run_dir = next(Path(directory).iterdir())
            metrics = json.loads(
                (run_dir / "feedback-metrics.json").read_text(encoding="utf-8")
            )
            self.assertTrue(metrics["accepted"])
            self.assertEqual(metrics["efficiency_status"], "semantic_zero_overlap_target")
            self.assertFalse(metrics["ocr_overlap_pair_required"])
            self.assertIsNone(metrics["image_pair"])
            self.assertFalse(metrics["section_complete"])
            self.assertEqual(len(context.tasker.controller.swipes), 2)

    def test_true_overshoot_remains_fail_safe(self):
        before = _complex_scene(height=720, width=260, seed=841)
        result = evaluate_feedback_candidate(
            before, _shift_up(before, 660, seed=842), _b1d_feedback_config()
        )
        self.assertFalse(result["accepted"])
        self.assertEqual(result["reason"], "unsafe_gap_risk")


if __name__ == "__main__":
    unittest.main()
