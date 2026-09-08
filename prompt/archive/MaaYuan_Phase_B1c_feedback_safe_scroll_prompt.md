# MaaYuan Phase B1c：反馈式安全翻页，消除固定 swipe 累积漂移

## 背景结论

真实 MuMu smoke 已确认：

- MaaFramework controller 截图固定为 `720 × 1280`
- `settle_ms = 1800` 足以得到稳定画面
- 同一组 `post_swipe(start/end/duration)` 多次运行后，实际页面位移并不完全一致
- 因此不能继续用“固定手势 = 固定内容位移”的假设
- 如果连续依赖固定 stride，误差会累积，存在某一整行被跳过的风险
- 现有全 ROI NCC `best_shift_px` 会被星石页面的周期性四列/金色圆盘结构误导，不能作为真实位移依据

项目业务边界已经锁定：

- MaaYuan 只负责图片采集和**图片级相邻 overlap 关系**
- 不做星石 OCR
- 不定位具体重复星石/重复行
- YuanStar 收到 machine batch 后，把相邻 overlap 自动写入现有 `confirmedOverlapPairs`
- 具体 duplicate 仍交给 YuanStar 现有 OCR/reconcile
- 因此允许自动采集链主动保留少量“安全 overlap”，不会再要求用户手工标每个图片 pair

---

# 目标

不要继续微调一个“刚好零 overlap”的 swipe end 坐标。

把 B1 probe 改成**反馈闭环**：

```text
上一张已接受截图 prev
→ 执行一个保守的 coarse swipe
→ 等页面稳定
→ 截 candidate
→ 用真实图像估计实际纵向位移
→ 检查是否仍保留安全 overlap
→ 合格才接受 candidate
→ 不合格则继续小步调整或明确失败
```

核心目标：

> 每一张新截图都根据“前一张真实截图”验证，不根据预期累计位置推算。

因此误差不会跨页累积。

本轮只验证“一次 prev → accepted candidate”的闭环，不做整背包循环。

---

# 1. Git

仓库：

```text
D:\Users\Yan\Projects\MaaYuan-v5-dev
```

预期分支：

```text
feat/yuanstar-capture-probe
```

先：

```powershell
git status --short --branch
git branch --show-current
git diff --check
```

本轮不 commit/push。

---

# 2. 保留已有 B1a/B1b

保留现有：

- `capture_only`
- `pair_probe`
- 两个 GUI 调试任务
- debug 输出
- `settle_ms = 1800` 作为当前真实 calibration 稳定值

不要删除现有诊断能力。

新增第三种 mode：

```text
feedback_probe
```

和第三个临时 GUI 任务：

```text
开发调试｜星石背包反馈滑动探针
```

用户运行前仍必须手动进入：

```text
星石背包 → 主星 → 顶部
```

---

# 3. 不再用全局 NCC 最大值估真实 shift

现有 `compute_visual_overlap()` 可以保留为 diagnostic，但不要再用：

```text
scan all vertical offsets
→ choose highest NCC
```

作为真实 page shift。

星石页面结构高度周期性，会产生错误峰值。

---

# 4. 新增 robust vertical shift estimator

实现一个纯 OpenCV/NumPy helper，例如：

```python
estimate_vertical_motion(before_roi, after_roi) -> MotionEstimate
```

推荐流程：

## A. ORB 特征

对 before/after ROI：

1. 灰度化；
2. 轻量 blur/CLAHE 可选；
3. ORB detect + compute；
4. BFMatcher(HAMMING) 做 kNN；
5. Lowe ratio filter；
6. 只保留“近似竖直滚动”的 match：
   - `abs(dx)` 很小
   - `dy` 方向一致
   - dy 在合理范围

### 重要

不要使用 OCR 文字结果。

ORB 只看图像特征，包括：
- 头像
- 星石纹理
- 等级字形
- 名称字形
- 局部背景

## B. Robust translation

对 good matches 的 `(dx, dy)`：

优先用：
- `cv2.estimateAffinePartial2D(..., method=cv2.RANSAC)`

或等价 robust estimator。

只接受：
- x translation 接近 0
- 足够 inlier
- vertical translation 有稳定中位数/MAD

输出：

```json
{
  "shift_y": 0.0,
  "inlier_count": 0,
  "match_count": 0,
  "inlier_ratio": 0.0,
  "median_abs_deviation": 0.0,
  "confidence": 0.0
}
```

## C. 局部 correlation 验证

得到 ORB/RANSAC 预测的 `shift_y` 后：

不要全局重新扫 offset。

只在：

```text
predicted shift ± 15~25 px
```

的小窗口内做局部 NCC/相关性确认。

这样周期性布局即使存在多个峰值，也不会跳到错误行周期。

---

# 5. no_move 判定

`no_move` 不依赖 ORB 单独判断。

采用双证据：

```text
same-position image similarity 很高
AND
robust shift_y 接近 0 / 无可信移动
```

本轮先输出诊断，不锁最终生产阈值。

---

# 6. 安全翻页策略：宁可 overlap，不允许 gap

不要追求“相邻截图零重复”。

业务安全目标改为：

```text
每个正常 accepted pair
至少保留一段可信的公共内容
最好约 1 个完整星石行
```

因为图片 pair overlap 会由 MaaYuan 自动标记，不再需要用户手工选择图片 pair。

## MVP 策略

使用保守 coarse swipe：

```text
start = [360, 930]
end   = [360, 560]  # diagnostic starting point，可按现有实测微调
duration_ms = 700
settle_ms = 1800
```

这里不是最终生产常量。

目标是故意比“零 overlap”少滑一点，给随机位移误差留下安全余量。

---

# 7. feedback_probe 闭环

流程：

```text
capture prev
↓
coarse swipe
↓
settle
↓
capture candidate
↓
estimate_vertical_motion(prev_roi, candidate_roi)
```

然后：

### A. 位移可信且处在安全窗口

接受 candidate。

输出：

```text
accepted = true
relation = overlap
```

本轮只记录图片 pair overlap，不定位具体重复行。

### B. 移动太少

如果 candidate 与 prev overlap 太多、实际 shift 明显小于目标：

不要立即保存 candidate。

允许最多执行 1~2 次**小步追加 swipe**：

```text
micro swipe
→ settle
→ recapture
→ 重新与原 prev 比较
```

注意始终与“原 prev”比较，不与未接受的中间 candidate 串联。

这样不会累计误差。

### C. 移动过大 / 无法证明安全 overlap

不要继续向下采集。

返回：

```text
accepted = false
reason = unsafe_gap_risk
```

MVP 直接停止并要求重试。

不要自动猜“应该没漏”。

后续如果确有必要，再实现反向微调；本轮不做。

### D. no_move

```text
accepted = false
reason = bottom_no_move
```

after 只用于确认到底，不作为新业务截图。

---

# 8. “安全窗口”本轮不要写死成生产业务阈值

本轮只做 diagnostic，输出：

```json
{
  "shift_estimate": {...},
  "same_position_score": 0.0,
  "local_overlap_score": 0.0,
  "accepted": false,
  "reason": "diagnostic_only",
  "attempts": []
}
```

每个 attempt 记录：

```json
{
  "gesture": {...},
  "shift_y": 0.0,
  "confidence": 0.0,
  "local_overlap_score": 0.0
}
```

第一轮真实 smoke 后再锁：
- coarse swipe
- micro swipe
- safe shift min/max
- no_move threshold
- confidence threshold

---

# 9. 为什么这样不会累计漂移

代码注释和报告必须明确：

错误方案：

```text
预计每页移动 X px
page1 + X
page2 + X
page3 + X
...
```

真实 swipe 有随机误差，因此累计位置会漂。

正确方案：

```text
accepted page A
→ 实际截图 B
→ A/B 直接视觉验证
→ 只有验证通过才接受 B

accepted B
→ 实际截图 C
→ B/C 再独立验证
```

每一步都重新锚定到真实画面，所以误差不会跨页累计。

---

# 10. Controlled overlap 与 YuanStar

本轮要在说明中再次固定：

MaaYuan 只输出：

```text
previous_image_id
current_image_id
relation = overlap
```

不输出：

```text
duplicate row
duplicate star
star name
level
quality
```

因此正常翻页主动保留一个小的安全 overlap 不会新增“用户手工标图片 pair”的负担。

具体重复内容仍由 YuanStar 现有 OCR/reconcile 找。

---

# 11. GUI / Pipeline

新增：

```text
开发调试｜星石背包反馈滑动探针
```

本轮只跑一次 closed-loop。

不要循环整个背包。

任务说明：

```text
请先进入「星石背包 → 主星 → 顶部」。
本任务可能执行一次 coarse swipe 和最多两次 micro swipe，用于验证反馈式安全翻页。
```

---

# 12. Runtime sync

更新：

```text
tools/sync_yuanstar_probe_runtime.ps1
```

安全 patch 三个开发任务：

1. 开发调试｜星石背包截图探针
2. 开发调试｜星石背包单次滑动探针
3. 开发调试｜星石背包反馈滑动探针

继续保证：

- UTF-8 BOM / Windows PowerShell 5.1 中文兼容
- targeted backup
- 不碰 config
- 不碰 MaaYuan.exe
- 不碰 MFAAvalonia
- 不碰 Python runtime

---

# 13. Tests

新增 synthetic tests：

1. 已知纵向平移的复杂纹理图：
   - ORB/RANSAC 能恢复近似 shift
2. 周期性重复背景 + 少量唯一局部特征：
   - 不应跳到错误周期峰值
3. identical：
   - no_move evidence 高
4. completely unrelated：
   - confidence 低 / reject
5. feedback:
   - first attempt shift too small -> micro swipe path
   - safe candidate -> accepted
   - unsafe overshoot -> reject

不安装新依赖。

---

# 14. 本轮不做

不要：

- 整背包循环
- 主/辅/经验切换
- OCR
- YuanHub transport
- Backend
- CaptureBatch 上传
- 自动导航
- commit/push

---

# 15. 最终报告

说明：

- 旧 NCC 为什么不再作为 shift 真值
- ORB/RANSAC estimator 文件和输出
- feedback_probe 流程
- coarse/micro gesture 仅为 diagnostic
- 为什么不会累计漂移
- 为什么受控 overlap 不增加手工 pair 标注
- tests
- runtime sync 命令
- 未 commit/push

最后只要求用户：

1. 关闭 MaaYuan runtime
2. 同步
3. 重开
4. 主星顶部
5. 跑一次 `开发调试｜星石背包反馈滑动探针`
6. 提供该 run 的：
   - prev/before
   - final candidate
   - ROI
   - feedback metrics JSON

不要继续整背包。
