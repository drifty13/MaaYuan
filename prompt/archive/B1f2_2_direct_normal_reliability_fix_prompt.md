# B1f2.2 — 修复 normal-motion 已有强 direct 证据却被低 ORB confidence 误判为 unreliable

## 背景与本轮目标

当前 `StarBackpackCaptureProbe` 已经能够区分：

- **physical / visual overlap**：两张截图在像素层面仍有共享区域；
- **semantic OCR overlap**：共享区域里是否真的存在一整行、且该整行满足 YuanStar 的完整 OCR envelope。

最近 4 次真实 MuMu probe 中，前三次都正确得到：

- shift ≈ 606 / 623 / 628 px
- physical overlap ≈ 132–154 px
- `semantic_overlap_state = definitely_no_full_row`
- `ocr_overlap_pair_required = false`
- `relation = null`

第四次 shift ≈ 596 px，肉眼同样没有完整 OCR 行重叠，且图像证据本身很强：

- selected shift ≈ 596 px
- `proposal_source = merged`
- `selection_mode = normal_motion_full_overlap`
- `fallback_used = false`
- `full_overlap_score ≈ 0.88`
- `anchor_score ≈ 0.91`
- `local_overlap_score ≈ 0.82`

但因为最终 `MotionEstimate.confidence` 偏低（≈0.264），它被覆盖成：

- `semantic_overlap_state = not_applicable_unreliable_motion`
- `accepted = false`
- `reason = unsafe_gap_risk`

这与当前“direct/full-overlap 作为独立强证据”的设计不一致。

### 本轮只修这一件事

**让已经通过 normal-motion full-overlap 强验证的 direct / merged 候选，不再仅仅因为 ORB/RANSAC confidence 偏低而被判为 unreliable motion。**

不要改 swipe 距离，不要改 row geometry，不要改 OCR，不要改 YuanStar，不要改 600px efficiency floor。

---

## Scope / 禁止事项

只允许修改与 probe reliability 组合判定直接相关的最小代码与测试：

- `agent/custom/action/star_backpack_capture_probe.py`
- `agent/tests/test_star_backpack_capture_probe.py`

如确有必要，可同步 probe runtime，但不要扩大业务范围。

### 本轮禁止

- 不修改 `coarse_swipe = [360,930] -> [360,540]`
- 不修改 `700ms`
- 不修改 `settle_ms = 2500`
- 不修改 `target_shift_range`
- 不修改 `safe_shift_range`
- 不修改 `physical_shift_range`
- 不修改 `row_pitch`
- 不修改 YuanStar 的 `card-completeness` / OCR 几何定义
- 不修改 semantic overlap 的 full-row envelope 规则
- 不降低全局 `diagnostic_min_confidence` 来“绕过”问题
- 不放宽 unrelated image / no-move 的 fail-safe
- 不引入 OCR
- 不运行新的 MuMu swipe，除非我后续明确要求
- 不 commit
- 不 push
- 不 reset / pull / merge / stash

先检查当前 git status 和 branch，保持现有工作树。

---

# 1. 先确认误判链路

当前 `evaluate_feedback_candidate()` 中大致存在：

```python
has_confident_motion = estimate.confidence >= feedback["diagnostic_min_confidence"]

has_reliable_overlap = (
    has_confident_motion
    and local_overlap_valid
    and local_overlap_score is not None
    and local_overlap_score >= feedback["diagnostic_min_local_overlap_score"]
)
```

随后：

```python
elif not has_reliable_overlap:
    semantic_overlap_state = "not_applicable_unreliable_motion"
```

问题是：

- `estimate.confidence` 主要还是 ORB/RANSAC 特征质量；
- 但现在 normal-motion 分支已经有另一套独立的 direct/full-overlap 证据；
- `proposal_source = direct_normal_band` 或 `merged`
- `selection_mode = normal_motion_full_overlap`
- `fallback_used = false`
- direct search 也已经确认真实 shift。

因此不能再把“ORB confidence 不够高”直接等价成“motion unreliable”。

---

# 2. 增加独立的 direct-normal reliability 判定

请实现一个清晰、可测试的 helper，例如：

```python
def _has_reliable_direct_normal_motion(estimate: MotionEstimate) -> bool:
    ...
```

命名可微调，但语义必须明确。

## 建议必要条件

只有在以下条件全部满足时，才允许 direct-normal evidence 独立承担 motion reliability：

1. `estimate.selected_hypothesis` 存在；
2. `selection_mode == "normal_motion_full_overlap"`；
3. `fallback_used == False`；
4. `inside_normal_motion_band == True`；
5. `inside_physical_motion_range == True`；
6. `proposal_source` 必须属于：
   - `"direct_normal_band"`
   - `"merged"`
7. `full_overlap_valid == True`；
8. `full_overlap_score >= DIRECT_NORMAL_MIN_SCORE`
   - 直接复用当前已存在的 `DIRECT_NORMAL_MIN_SCORE`
   - 不再另造一套神秘阈值
9. `anchor_score` 存在，并且不得明显弱于 direct branch 已接受标准；
   - 优先同样复用 `DIRECT_NORMAL_MIN_SCORE`
   - 如果你审查当前实现后认为 anchor 不应与 full-overlap 共用阈值，必须在结果中解释，不要静默改数字
10. `direct_normal_search.candidate_injected == True`
11. `direct_normal_search.best_shift_px` 与最终 selected shift 应保持局部一致；
   - 使用当前已有 dedupe/local 容差概念；
   - 不要放宽到跨一个 row pitch 的范围。

### 关键原则

这不是“confidence bypass”。

它应表达成：

> ORB/RANSAC confidence 与 direct normal full-overlap evidence 是两条不同的 motion reliability 证据路径。

---

# 3. 重构 reliability 组合，不改后续业务语义

建议在 `evaluate_feedback_candidate()` 中拆成：

```python
orb_confidence_passed = ...
direct_normal_evidence_passed = ...
has_reliable_motion = (
    orb_confidence_passed
    or direct_normal_evidence_passed
)

has_reliable_overlap = (
    has_reliable_motion
    and local_overlap_valid
    and local_overlap_score is not None
    and local_overlap_score >= feedback["diagnostic_min_local_overlap_score"]
)
```

### 注意

**local overlap confirmation 仍然必须保留。**

不能因为 direct candidate 被选中，就跳过：

- `local_overlap_valid`
- `local_overlap_score >= diagnostic_min_local_overlap_score`

也就是说需要：

**motion reliability + local overlap confirmation**

两层都成立，才进入后续 semantic row-overlap 语义。

这样可以避免 unrelated / accidental periodic alias 被误接受。

---

# 4. 增加审计字段

请在 `feedback-metrics.json` 中增加最少必要的 audit 字段，例如：

```json
{
  "motion_reliability": {
    "reliable": true,
    "mode": "direct_normal_full_overlap",
    "orb_confidence_passed": false,
    "direct_normal_evidence_passed": true
  }
}
```

建议 `mode` 只有：

- `orb_confidence`
- `direct_normal_full_overlap`
- `orb_and_direct`
- `unreliable`

不要影响现有字段兼容性，不删除旧字段。

目的是以后看到真实 probe 时，可以直接知道为什么这帧被认为 motion reliable。

---

# 5. 必须增加针对第四类真实问题的 regression

不要只测试 helper。

必须覆盖 `evaluate_feedback_candidate()` 的完整行为。

## Test A — merged + strong direct evidence + low ORB confidence

构造一组真实可对应的 shifted image，例如 620px 左右：

1. 先用真实 synthetic shifted image 生成正常 estimate；
2. 保留：
   - shift
   - selected hypothesis
   - direct_normal_search
   - strong full-overlap / anchor evidence
3. 只把最终 `MotionEstimate.confidence` 人为压低到明显低于 `diagnostic_min_confidence`；
4. patch `estimate_vertical_motion()` 返回该 estimate；
5. 让 `_local_overlap_confirmation()` 仍然基于真实 before/candidate 图执行，不要 mock 成永远成功。

期望：

- 不得得到 `not_applicable_unreliable_motion`
- `motion_reliability.direct_normal_evidence_passed == true`
- `motion_reliability.orb_confidence_passed == false`
- `motion_reliability.reliable == true`
- 对 620px target：
  - `accepted == true`
  - semantic 结果按现有 geometry 真实计算
  - 如果没有完整 OCR row：
    - `ocr_overlap_pair_required == false`
    - `relation == null`

## Test B — low confidence + 没有 strong direct-normal evidence

构造：

- ORB confidence 低；
- selected hypothesis 不是 `normal_motion_full_overlap`
  或
- `proposal_source` 不是 direct/merged
  或
- `direct_normal_search.candidate_injected == false`
  或
- full-overlap score 不达标。

期望：

- 仍然是 `not_applicable_unreliable_motion`
- 不得因为这次修复而误放行。

## Test C — unrelated image 保持 fail-safe

保留并确认现有 unrelated regression：

- `accepted == false`
- `semantic_overlap_state == not_applicable_unreliable_motion`
- `ocr_overlap_pair_required == false`
- `relation == null`

## Test D — no-move 保持原样

- `bottom_no_move`
- `not_applicable_no_move`
- 不产生 pair。

## Test E — direct-only 既有行为不退化

已有 `direct_normal_band` 测试必须继续通过。

---

# 6. 不要借机改 596px 的 efficiency floor

这次只处理“reliability”。

即便修完以后 596px 被正确认为 motion reliable，也仍允许它保持：

- `efficiency_status = conservative`
- 或根据当前既有 600px floor 得到相应现有状态

不要在这一轮把 596 自动改成 target / acceptable。

我们要先确保：

**motion reliability 修正**
与
**效率区间判定**

是两个独立变量。

---

# 7. 回归要求

至少执行：

```powershell
python -m py_compile agent\custom\action\star_backpack_capture_probe.py
python -m unittest agent.tests.test_star_backpack_capture_probe
git diff --check
```

如果项目现有测试调用方式不同，使用仓库实际可运行命令。

要求：

- 全部 probe tests PASS
- unrelated / no-move / terminal / overshoot 不退化
- 不修改 YuanStar
- 不触发 OCR
- 不做真实 MuMu swipe

---

# 8. runtime sync

代码与测试通过后：

执行当前仓库已有的 targeted runtime sync：

```powershell
.\tools\sync_yuanstar_probe_runtime.ps1 -RuntimePath "D:\Users\Yan\Projects\MaaYuan-v5-runtime"
```

然后核对同步文件 SHA-256 一致。

### 但不要自行开启 MuMu / MaaYuan 做新的 swipe

本轮只把修复同步到 runtime，等我下一步手动 smoke。

---

# 9. 最终汇报格式

请按下面格式返回：

## Result
PASS / PARTIAL / FAIL

## Git
- branch
- HEAD
- changed files
- commit/push: NO

## Root cause
明确说明为什么 merged normal-motion 会被低 ORB confidence 错误覆盖成 unreliable。

## Fix
明确说明：

- ORB confidence evidence
- direct normal full-overlap evidence
- local overlap confirmation

三者现在如何组合。

## New audit fields
列出新增 metrics 字段及含义。

## Regression
列出测试数量与关键场景：

- low ORB + strong merged direct evidence
- weak direct evidence
- unrelated
- no-move
- direct-only normal
- terminal / overshoot

## Runtime sync
- 是否完成
- SHA-256 是否一致

## Scope confirmation
明确确认：

- swipe 参数未改
- 600px efficiency floor 未改
- semantic envelope 未改
- YuanStar 未改
- OCR 未调用
- 未执行新 MuMu swipe
- 未 commit
- 未 push
