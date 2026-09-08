# B1f.3 收口：接受边界微调 + 回归 + commit

## 推荐模型
- **GPT-5.6 Terra High**
- 这轮是明确的小范围收口、阈值边界修正、回归和 Git 提交，不需要 Sol。
- 不扩展架构，不新增无必要诊断字段。

## 当前事实（以本轮真实 MuMu probe 为准）

最新真实 probe：
- coarse swipe: `[360,930] -> [360,540]`
- `settle_ms = 2500`
- `single_swipe_calibration = true`
- 实测 `shift_y = 599.5992916917621 px`
- `true_shift_rows = 3.6011969470976704`
- `physical_overlap_px = 160.40070830823788`
- `semantic_overlap_state = definitely_no_full_row`
- `ocr_overlap_pair_required = false`
- `motion_reliability.reliable = true`
- `motion_reliability.mode = orb_and_direct`
- `local_overlap_valid = true`
- `local_overlap_score = 0.6535921692848206`
- 当前唯一异常：因为 normal acceptance 下界实际比较为 `>= 600`，599.599 被判成
  `efficiency_correction_required`，导致 `accepted=false`。

肉眼结果和语义结果均符合目标：约 3.6 行推进，存在物理 overlap，但没有完整 OCR 行 overlap，不应因为 0.4px 的估计误差再触发 micro correction。

---

## 目标

只做一个最小修正：

> 正常推进下界的判定应允许极小的亚像素/估计误差，不能让 599.6px 因为比 600px 少 0.4px 就进入 correction。

然后完成回归、runtime sync 校验，并在确认 diff 后 **commit 当前 B1 probe 累计工作**。

---

## 约束

1. 不修改当前 swipe 参数：
   - `[360,930] -> [360,540]`
   - `700ms`
   - `settle_ms=2500`
2. 不修改 target range `[610,630]`。
3. 不修改 normal safe range `[560,650]`。
4. 不修改 semantic row overlap 几何。
5. 不修改 OCR / YuanStar。
6. 不新增新的 metrics 字段。
7. 不重新设计 motion estimator。
8. 不执行新的 MuMu swipe；本轮真实 probe 已足够作为 acceptance evidence。
9. 不 pull / reset / rebase / stash。
10. commit 前必须先检查 `git status` 和 `git diff --check`。

---

## 修正建议

在 `evaluate_feedback_candidate()` 的 normal acceptance 边界上使用一个**极小、明确的像素容差**，只解决浮点/估计边界抖动。

优先方案：

```python
NORMAL_ACCEPTANCE_EPSILON_PX = 1.0
```

然后 normal accepted 判断等价于：

```python
acceptable_normal_min - NORMAL_ACCEPTANCE_EPSILON_PX <= estimate.shift_y <= normal_safe_max
```

或使用逻辑完全等价、但更局部的写法。

### 必须满足

- 599.599px：accepted
- 599.0px：accepted（如果正好落在 epsilon 范围）
- 明显低于 599px 的值，例如 596px：仍然不能因为这个修正被误放行
- 560px 这一类本来需要 efficiency correction 的场景仍保持原行为
- 620px target 场景保持 target
- 660px overshoot 仍 fail-safe
- no-move / terminal 行为不变

不要把下界整体从 600 改成 590/595，也不要放大容差。

---

## 测试

在现有 `test_star_backpack_capture_probe.py` 中只补必要边界测试，优先：

1. `599.6px`（或可稳定模拟的 599/600 临界实数）进入 accepted normal。
2. `596px` 仍是 `efficiency_correction_required`。
3. 现有：
   - 560 correction
   - 620 target
   - 660 overshoot
   - no-move
   - terminal partial
   全部继续通过。

运行：
- Python compile
- probe test suite
- `git diff --check`

不要为了测试方便扩大生产阈值。

---

## runtime sync

完成代码和测试后，运行现有 targeted runtime sync：

```powershell
.\tools\sync_yuanstar_probe_runtime.ps1 -RuntimePath "D:\Users\Yan\Projects\MaaYuan-v5-runtime"
```

确认：
- source/runtime 5 个 probe artifact SHA-256 一致
- 不需要再启动 MuMu 做新 probe

---

## commit 前审查

请输出：

```text
git status --short
git diff --stat
```

检查本轮/累计 B1 probe worktree 中：
- probe action
- probe tests
- probe pipeline / registration
- sync tool
- 必要的 archived prompts

不要把无关文件带进 commit。

如果发现明显无关改动，先报告，不要擅自丢弃。

---

## commit

如果测试、runtime sync、diff 检查都通过，创建一个本地 commit。

建议 commit message：

```text
feat: stabilize star backpack capture probe
```

或如果你判断当前累计内容更适合：

```text
feat: add feedback-driven star backpack capture probe
```

**本轮只 commit，不 push。**

---

## 最终报告

简洁输出：

1. Result: PASS / PARTIAL / FAIL
2. 599.6px 边界最终 classification
3. tests 数量与结果
4. runtime sync / SHA-256
5. `git status`（commit 后）
6. commit hash + message
7. 明确说明：未执行新的 MuMu swipe，未修改 YuanStar/OCR
