# Codex Task — B1f2.2：修复 direct-normal 合并候选资格丢失，并收缩 probe metrics

## 模型推荐
- **模型：GPT-5.6 Terra**
- **思考强度：High**
- 原因：这是一个边界明确但涉及候选选择优先级、fallback 语义和回归约束的中等复杂度调试任务。Terra High 足够；**不要升级到 Sol**，除非实际发现问题跨到 YuanStar 几何契约或需要跨仓库架构改动。

## 目标
修复当前 `star_backpack_capture_probe` 中的一个明确选择错误：

> `direct_normal_search` 已经找到了强证据的正常位移候选，但该候选与少量 ORB 支持合并为 `proposal_source="merged"` 后，因为 ORB `match_count < 3`，反而失去 normal-motion 候选资格，最终错误退回到 125px / 268px 的周期 alias。

同时，清理 probe JSON 中**纯重复**、没有额外诊断价值的字段，避免继续膨胀。

---

## 已有真实回归证据

### Run A
- 实际正确 shift：约 **593px**
- 当前已经选中 593
- `semantic_overlap_state = definitely_no_full_row`
- `ocr_overlap_pair_required = false`
- 这一轮主要用于保证不要回归。

### Run B
当前 JSON：
- ORB fallback 选中：**125px**
- 但 `direct_normal_search.best_shift_px = 625`
- `best_score ≈ 0.9067`
- `anchor_score ≈ 0.8844`
- 625 候选已经是 `proposal_source="merged"`
- 但 ORB `match_count = 2`
- 最终错误进入 `terminal_fallback`

**期望：应选约 625px，而不是 125px。**

### Run C
当前 JSON：
- ORB fallback 选中：**268px**
- 但 `direct_normal_search.best_shift_px = 601`
- `best_score ≈ 0.9486`
- `anchor_score ≈ 0.9685`
- 601 候选已经是 `proposal_source="merged"`
- ORB `match_count = 1`
- 最终错误进入 `terminal_fallback`

**期望：应选约 601px，而不是 268px。**

---

# 一、先检查，不要直接重写

1. 确认当前仓库：
   `D:\Users\Yan\Projects\MaaYuan-v5-dev`

2. 确认当前分支：
   `feat/yuanstar-capture-probe`

3. 先执行：
   ```powershell
   git status --short
   git diff --check
   ```

4. 不要 reset / pull / merge / stash。
5. 不要修改 YuanStar。
6. 不要修改已经确认的 swipe 参数：
   - start `[360,930]`
   - end `[360,540]`
   - duration `700ms`
   - settle `2500ms`
7. 不要调用 OCR。
8. 这一轮先不 commit / push。

---

# 二、修复 candidate eligibility

重点检查：
`agent/custom/action/star_backpack_capture_probe.py`

当前问题本质不是 direct search 找不到，而是：

```text
direct_normal_band
    ↓ 与 ORB 合并
merged
    ↓
因为 ORB match_count 太少，被 normal candidate gate 排除
    ↓
terminal_fallback 误选周期 alias
```

## 修改要求

### 1. validated direct support 必须在 merge 后继续有效

如果一个 candidate：

- shift 位于既有 normal motion band；
- 来自已经通过既有 strict direct-normal validation 的 `direct_normal_search`；
- 后续只是与 ORB hypothesis 合并成 `merged`；

那么它仍然必须具备 normal-motion eligibility。

**不要要求它因为变成 `merged` 就重新满足 `ORB match_count >= 3`。**

### 2. 不要把所有 `merged` 都放行

只能放行：

> **确实继承了“已经验证通过的 direct-normal evidence”的 merged candidate**

不要写成：

```python
if proposal_source == "merged":
    eligible = True
```

这种过宽逻辑。

建议使用现有运行时变量/映射判断 direct best shift 是否与 merged candidate 对齐（沿用现有 dedupe tolerance，例如已有的 ±12px 逻辑），而不是为了修这个问题继续增加大量新的 output fields。

### 3. 选择优先级

当存在满足 strict direct-normal evidence 的 normal-band candidate 时：

- 它必须进入 normal-motion candidate pool；
- 不应因为 ORB match 少而被排除；
- terminal fallback 只在真正没有可信 normal-motion candidate 时运行。

### 4. 保留 fail-safe

不得破坏：
- `no_move`
- terminal / bottom no-move
- true overshoot
- genuine terminal partial
- physical range
- semantic row-overlap gate

---

# 三、回归测试要求

优先直接复用已经保存的真实 prev/candidate 图和现有测试入口。

至少覆盖：

### Case A — 593px
- 最终 shift 仍约 593
- 不得被周期 alias 抢走
- semantic 仍为 `definitely_no_full_row`
- `ocr_overlap_pair_required == false`

### Case B — 625px direct + 2 ORB matches
- 最终应选择约 625
- 不得选择约 125
- 不得进入 `terminal_fallback`
- 证明 merged candidate 继承 direct-normal eligibility

### Case C — 601px direct + 1 ORB match
- 最终应选择约 601
- 不得选择约 268
- 不得进入 `terminal_fallback`
- 证明低 ORB match 不会抹掉 validated direct support

### Case D — negative
人工构造一个：
- `proposal_source="merged"`
- 但没有 validated direct-normal support
- ORB evidence 又不足

期望：
- 不得因为 `merged` 本身就被放行。

### Case E — fail-safe
保留至少：
- no-move
- terminal partial
- overshoot

不得回归。

---

# 四、收缩 metrics：只删纯重复，不做新架构

当前 JSON 已经有明显重复。

这轮允许删除**纯重复镜像字段**，但不要搞 debug level、telemetry framework、schema versioning 等额外架构。

优先检查并删除：

1. 顶层 `motion_hypotheses`
   - 如果与 `shift_estimate.motion_hypotheses` 完全重复，只保留一份。

2. 顶层 `selected_hypothesis`
   - 如果与 `shift_estimate.selected_hypothesis` 完全重复，只保留一份。

3. `selected_hypothesis_reason`
   - 如果只是完整复制 selected hypothesis，则删除；
   - 若确有额外 reason，只保留简短 reason/mode，不复制整个对象。

4. `visual_overlap_px` 与 `physical_overlap_px`
   - 若当前语义完全相同，只保留一个；
   - 优先保留 `physical_overlap_px`。

5. 顶层 `prev_row_centers` / `candidate_row_centers`
   - 如果 `row_lattice.prev/candidate.row_centers` 已存在，删除顶层重复。

6. 顶层 `anchor_score`
   - 如果 selected hypothesis 已包含，删除重复。

7. 不要新增更多诊断字段来补偿这些删除。

## 暂时必须保留的调试信息
为了当前 motion 选择调试，至少保留：

- `shift_estimate.motion_hypotheses`
- `shift_estimate.selected_hypothesis`
- `shift_estimate.direct_normal_search`
- `motion_reliability`
- `actual_shift_px`
- `true_shift_rows`
- `physical_overlap_px`
- `semantic_overlap_state`
- `ocr_overlap_pair_required`
- `full_row_candidates`
- `accepted`
- `reason`
- `gesture_count`
- `section_complete`

若某字段已有唯一等价来源，不要再复制第二份。

---

# 五、验证

执行现有 probe 单测与 Python compile。

至少给出：

```text
Python compile
probe tests
git diff --check
```

并报告：

1. Run A/B/C 最终 selected shift；
2. B/C 是否还进入 terminal fallback；
3. negative merged-without-direct-support 是否正确拒绝；
4. metrics 删除了哪些重复字段；
5. JSON 是否仍保留当前调试真正需要的信息。

如果本地已有保存的真实图，就直接离线回归，不需要先让我重新开 MuMu。

---

# 六、runtime sync

代码与测试通过后，执行现有 targeted runtime sync：

```powershell
Set-Location D:\Users\Yan\Projects\MaaYuan-v5-dev
.\tools\sync_yuanstar_probe_runtime.ps1 -RuntimePath "D:\Users\Yan\Projects\MaaYuan-v5-runtime"
```

确认 source/runtime 对应 probe 文件 SHA-256 一致。

**不要主动启动 MaaYuan，不要主动操作 MuMu。**

---

# 七、最终输出格式

最后只给简洁结果：

```text
Result: PASS / PARTIAL / FAIL

Selected shifts:
- A: ...
- B: ...
- C: ...

Eligibility fix:
- ...

Negative regression:
- ...

Metrics cleanup:
- removed: ...
- retained: ...

Tests:
- compile:
- probe tests:
- diff-check:
- runtime sync:

Git:
- branch:
- commit/push: NO
```

如果出现真实阻断，只处理本任务的最小修复，不扩展到 OCR、YuanStar、云端同步、UI 或其他模块。
