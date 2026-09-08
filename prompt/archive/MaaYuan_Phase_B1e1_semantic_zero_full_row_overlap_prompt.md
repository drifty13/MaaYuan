# MaaYuan Phase B1e.1：正常页效率目标修正
## 目标：保留物理视觉 overlap，但正常页 0 个“完整 OCR 行”重叠

## 0. 本轮先纠正一个前提

上一轮把“保留约一整行 overlap”作为正常页目标，这个定义不对。

本项目必须严格区分：

### A. physical / visual overlap
前后截图在像素内容上仍共享一小段区域。

用途：
- 证明没有跳页；
- 做真实 shift / 页面连续性验证；
- 给随机 swipe 漂移留安全余量。

### B. OCR-semantic full-row overlap
同一个完整四列星石行，在前后两张截图里都完整可 OCR。

这才会导致 YuanStar OCR 后出现完整 duplicate row，需要进入现有 overlap/reconcile 语义。

**正常翻页真正目标：**

```text
visual overlap > 0
OCR-semantic full-row overlap = 0
```

也就是：

```text
允许前后图片有物理重叠，
但不要让同一整行在两张图片中都完整出现。
```

MaaYuan 仍不识别具体星石、不 OCR 名称、不定位 duplicate star。

---

# 1. 真实截图重新测量结论

controller：

```text
720 × 1280
```

scroll compare ROI：

```text
640 × 760
```

真实主星页面纵向 row pitch 约：

```text
166～167 px
```

ROI 约能容纳：

```text
4.5 行
```

用户本轮上传的 `prev-roi / candidate-roi` 直接图像对齐显示：

```text
真实 shift 约 522 px
≈ 3.1 行
```

不是此前 metrics 选中的约 `356 px`。

这说明当前 motion hypothesis selector 仍可能在周期性布局里选择错误的 “少一行 alias”。

因此本轮同时修：

1. 正常页效率目标；
2. motion hypothesis 的直接像素 anchor 验证。

---

# 2. 正常页理论甜点区

如果一屏约 4.5 行，实际推进 `d` 行：

```text
physical overlap ≈ 4.5 - d 行
```

要满足：

### 不出现完整行重复
需要：

```text
physical overlap < 1 行
→ d > 3.5 行
```

### 不漏掉上一张底部那一行
上一张最后半行必须能在下一张完整出现，因此：

```text
d < 4.0 行
```

所以正常页真正的目标不是“保留 1 整行”，而是：

```text
3.5 < d < 4.0 行
```

结合 row pitch ≈ 166～167px：

```text
约 585～665px
```

考虑随机 swipe 漂移与边界余量，本轮 diagnostic 目标收窄为：

```text
target shift = 610～630px
```

约：

```text
3.65～3.8 行
```

对应 physical overlap：

```text
760 - shift ≈ 130～150px
```

即：

```text
有明显物理 overlap
但不足以稳定容纳一整行 OCR 内容
```

这正是目标状态。

---

# 3. 用户期望的肉眼状态

正常 candidate 顶部允许两种理想表现：

### 理想 A
上一张最后一个完整行在 candidate 顶部只剩下半截，
**等级区域已经不在 candidate 中**。

例如：

```text
上一张完整：
巨门 / 巨门 / 破军 / 破军

candidate 顶部：
只剩该行下半截，不含等级
```

此行不能再作为 candidate 的完整 OCR 行。

### 理想 B
上一张底部仅部分出现的下一行，在 candidate 中完整出现，
包括等级。

例如：

```text
上一张底部：
贪狼 / 天同 / 天同 / 太阴 只有残片

candidate：
贪狼 / 天同 / 天同 / 太阴 完整
```

此时该行只在 candidate 中完整，因此也不是完整行 duplicate。

不要追求：

```text
同一完整行在 prev/candidate 各出现一次
```

---

# 4. 修正 motion estimator：为 hypothesis 增加 direct overlap anchor

当前真实样本里：
- 周期性 ORB hypothesis 可能同时出现相差约 1 row pitch 的候选；
- 单纯 match_count / RANSAC 仍可能选错 alias。

对每一个正向 motion hypothesis `shift=s`，新增：

```text
direct_overlap_anchor_score
```

## 原理

真实滚动下：

```text
candidate ROI 顶部的一段像素
```

应该直接来自：

```text
prev ROI 的 y = s 附近
```

因此对每个 candidate shift：

```python
prev[s : s + anchor_h]
vs
candidate[0 : anchor_h]
```

做直接像素/边缘相关性。

建议：

```text
anchor_h = min(120px, physical_overlap_px - margin)
```

最低仍需有足够 anchor，例如 64～80px。

可组合：

- RGB/BGR normalized correlation；
- grayscale gradient correlation；
- 少量 blur 后的 SSIM/NCC 等现有依赖可实现方法。

不要 OCR。

## 选择规则

hypothesis selection 综合：

1. direction；
2. ORB evidence；
3. spatial coverage；
4. MAD；
5. **direct_overlap_anchor_score（强权重）**；
6. expected prior 只能 soft bonus。

真实 shared pixels 的 anchor 应优先于“另一行结构看起来很像”的周期 alias。

输出：

```json
{
  "anchor_score": 0.0,
  "anchor_height_px": 0
}
```

到每个 hypothesis。

---

# 5. 正常页效率状态改成“语义 overlap”导向

新增：

```json
"diagnostic_row_pitch_px": 166.5,
"diagnostic_target_shift_px": [610, 630],
"diagnostic_normal_safe_shift_px": [560, 650]
```

本轮仅针对主星 720×1280 页面。

不要推广到辅星/经验星。

## candidate 决策

### A. 610～630
```text
accepted
efficiency_status = semantic_zero_overlap_target
ocr_overlap_pair_required = false
```

### B. 600～650
如果 motion / local anchor 均可信：

```text
accepted
efficiency_status = semantic_zero_overlap_acceptable
ocr_overlap_pair_required = false
```

这里仍保留 physical visual overlap。

### C. 520～600
```text
安全但存在完整行 OCR overlap 的可能
```

不要立即接受为最终正常页。

允许最多 1 次 efficiency micro，继续向下推进。

最终仍：

```text
final candidate vs original prev
```

重新估 shift。

### D. <520
效率明显不足，也最多 1 次 efficiency micro。

### E. >650
```text
unsafe_gap_risk
```

停止，不猜。

---

# 6. coarse / micro

本轮不要用“固定 gesture = 固定 shift”的假设。

只作为初始动作。

建议先：

```text
coarse:
[360,930] -> [360,470]
700ms
settle 1800ms
```

如果真实 smoke 显示经常 overshoot，再回收。

efficiency micro：

```text
一次小步
```

由现有 feedback runner 执行。

最终是否接受只看真实视觉结果。

最多一次 micro，避免为了几十 px 反复等待。

---

# 7. visual overlap 与 CaptureBatch / YuanStar overlapPair 分离

这是本轮最重要的契约修正。

MaaYuan 内部可以记录：

```text
visual_overlap = true
```

用于连续性证明。

但传给 YuanStar 的：

```text
overlapPairs / confirmedOverlapPairs
```

只表示：

> 存在“完整 OCR 行”在两张图中重复。

因此正常 target：

```text
visual_overlap = true
ocr_overlap_pair_required = false
```

不要把正常的 partial visual overlap 写入 YuanStar `confirmedOverlapPairs`。

near-bottom 如果因为触底导致前后确实存在完整重复行，则：

```text
ocr_overlap_pair_required = true
```

仍然只输出图片 pair，不定位具体哪一行/哪颗星石。

---

# 8. 本轮不要做完整 row OCR detector

不要：
- OCR 等级；
- OCR 名称；
- 识别“巨门/破军”等文本；
- 定位 duplicate star。

本轮 `ocr_overlap_pair_required` 先基于：

```text
真实 shift
+ 已校准 row pitch
+ physical overlap 高度
```

做主星 diagnostic 判断。

如果：

```text
physical_overlap_px < diagnostic_row_pitch_px * 0.90
```

可以判为：

```text
semantic full-row overlap 不需要
```

保留 0.90 为 diagnostic margin。

后续真实 smoke 再校准。

---

# 9. bottom / terminal partial 保持 B1d 已通过逻辑

不要破坏：

```text
near-bottom small positive
→ terminal partial
→ confirmation swipe
→ no_move
→ 接受 final candidate
→ section complete
```

以及：

```text
bottom
→ no_move
→ 不保存 confirm frame
→ complete
```

near-bottom 因物理 overlap 很大，允许：

```text
ocr_overlap_pair_required = true
```

这是少数尾页场景，不影响正常页效率。

---

# 10. Metrics

新增：

```json
{
  "row_pitch_px": 166.5,
  "visual_overlap_px": 0,
  "visual_overlap_rows": 0.0,
  "ocr_overlap_pair_required": false,
  "anchor_score": 0.0,
  "true_shift_rows": 0.0
}
```

并保留：
- motion hypotheses
- selected hypothesis
- local overlap
- accepted
- reason

---

# 11. Tests

至少覆盖：

1. 周期性页面：
   - hypotheses 356 / 522 都存在；
   - direct top anchor 在 522 更符合真实 shared pixels；
   - 必须选 522。

2. normal shift 620：
   ```text
   visual overlap > 0
   ocr_overlap_pair_required = false
   accepted
   ```

3. shift 560：
   - 存在完整行 semantic overlap 风险；
   - 触发一次 efficiency correction，而不是直接最终接受。

4. correction 后 620：
   - 与 original prev 重新比较；
   - accepted；
   - no OCR overlap pair。

5. >650：
   - unsafe gap。

6. near-bottom terminal partial：
   - 保持 B1d。

7. bottom no_move：
   - 保持 B1d。

---

# 12. Git / runtime

仓库：

```text
D:\Users\Yan\Projects\MaaYuan-v5-dev
```

分支：

```text
feat/yuanstar-capture-probe
```

先：

```powershell
git status --short --branch
git diff --check
```

不要 commit/push。

更新 runtime sync，保持：
- UTF-8 BOM / PowerShell 5.1
- targeted backup
- 不碰 config / MaaYuan.exe / Python / MFAAvalonia

---

# 13. 真实 smoke

本轮代码完成后只跑：

```text
主星顶部
→ feedback probe
```

提供：

- prev.png
- final candidate.png
- prev-roi.png
- candidate-roi.png
- feedback-metrics.json

验收重点不是“留一整行”。

而是：

```text
true shift 约 610～630px
≈ 3.65～3.8 行

visual overlap 仍存在
但 candidate 顶部不再包含上一张完整 OCR 行
ocr_overlap_pair_required = false
```

肉眼目标：

- 上一张最后完整行只在 candidate 顶部残留下半截且不含等级；
  或
- 上一张底部残行在 candidate 中完整成为首个有效新行。

正常页不应再进入 YuanStar `confirmedOverlapPairs`。
