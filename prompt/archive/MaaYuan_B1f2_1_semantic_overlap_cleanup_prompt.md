# MaaYuan Phase B1f.2.1 — semantic overlap 收口修正

## 当前背景

当前仓库：

- `D:\Users\Yan\Projects\MaaYuan-v5-dev`
- 当前工作分支应为：`feat/yuanstar-capture-probe`
- 本轮只修改 MaaYuan probe 相关代码，不修改 YuanStar、YuanHub、Backend。
- 当前 B1f.2 已经完成：
  - 物理 overlap 与 OCR 语义 overlap 分离；
  - 基于 YuanStar runtime geometry 推导完整行 envelope；
  - 根据前后帧 row lattice + 真实 shift 判断共享区域中是否存在完整 OCR 行；
  - `ocr_overlap_pair_required` 已不再依赖单纯的 `overlap_px >= row_pitch * ...` 阈值；
  - 历史真实回归样本中：
    - 581px → physical overlap ~179px → `ambiguous` → pair=true
    - 596.62px → ~163px → `definitely_no_full_row` → pair=false
    - 611.13px → ~149px → `definitely_no_full_row` → pair=false
    - 621.93 / 640.24 / 651px → pair=false
- 当前已有 39 项 probe 单测通过。
- 当前不要重做滑动参数，不改变现有单滑校准参数：
  - `[360,930] -> [360,540]`
  - `700ms`
  - `settle_ms=2500`
- 当前不要运行新的 MuMu swipe；本轮先完成代码语义收口和测试。真实 MuMu smoke 留到下一步人工配合执行。

---

# 本轮目标

只修两个明确的小问题：

1. **terminal partial confirmed 后的 `relation` 不得再写死 `"overlap"`，必须与 `ocr_overlap_pair_required` 同源。**
2. **当 motion / overlap evidence 不可靠时，不应继续输出可误解的 semantic overlap 结论；改为明确的 `not_applicable_unreliable_motion`，并强制 `ocr_overlap_pair_required=false`。**

不要扩展范围。

---

# 任务 0：先检查 Git 状态

先执行并报告：

```powershell
git status --short
git branch --show-current
git log -1 --oneline
```

要求：

- 不要 `git reset`
- 不要 `git pull`
- 不要 `git merge`
- 不要 `git stash`
- 不要切换现有工作分支
- 不要删除用户当前未提交修改
- 本轮结束前不要 commit / push，除非后续用户明确要求

如果工作区存在与本轮无关的修改，只记录，不碰。

---

# 任务 1：修 terminal partial confirmed 的 relation 语义

目标文件预计：

```text
agent/custom/action/star_backpack_capture_probe.py
agent/tests/test_star_backpack_capture_probe.py
```

当前 `_run_feedback_probe()` 在 terminal partial 被 no-move confirmation 确认后，存在类似：

```python
final_evaluation.update(
    {
        "accepted": True,
        "relation": "overlap",
        ...
    }
)
```

这会造成一个语义不一致风险：

- `ocr_overlap_pair_required == false`
- `image_pair == None`
- 但 `relation == "overlap"`

这是不允许的。

## 正确规则

`relation` 必须与 `ocr_overlap_pair_required` 同源：

```python
relation = "overlap" if ocr_overlap_pair_required else None
```

或者采用等价、更加集中且不重复的实现。

要求：

- terminal partial confirmed 后：
  - 如果语义判断确实要求 OCR pair：
    - `relation == "overlap"`
    - 可以生成 `image_pair`
  - 如果语义判断不要求 OCR pair：
    - `relation is None`
    - `image_pair is None`
- 不允许 relation 与 image_pair/semantic state 自相矛盾。
- 不要为了这个问题改变 terminal partial 的确认流程本身。
- 不要改变 `section_complete`、no-move confirmation 的业务语义。
- 不要重新引入“只要物理 overlap 就 relation=overlap”的旧逻辑。

## 测试更新

找到旧测试中类似：

```python
self.assertEqual(metrics["relation"], "overlap")
```

如果该测试对应的语义 overlap 实际并不需要 pair，则应改为：

```python
self.assertIsNone(metrics["relation"])
self.assertIsNone(metrics["image_pair"])
```

但不要机械改断言。

先根据测试构造的 shift / row geometry 计算它在当前 semantic overlap 模型下到底应不应该 pair，然后断言应与 semantic truth 一致。

建议新增一个明确测试，保证：

```text
terminal partial confirmed
+ ocr_overlap_pair_required == false
=> relation == None
=> image_pair == None
```

同时至少保留一个：

```text
ocr_overlap_pair_required == true
=> relation == "overlap"
```

的覆盖，避免把 relation 永久关掉。

---

# 任务 2：不可靠 motion 时，semantic overlap 标记为 not applicable

当前 `evaluate_feedback_candidate()` 的顺序大致是：

1. motion estimate
2. same-position / local overlap
3. semantic row overlap
4. 再判断 `has_confident_motion` / `has_reliable_overlap`

这样会出现一种诊断污染：

- motion 本身不可靠
- 但 row lattice + 某个错误 shift 仍可能算出：
  - `ambiguous`
  - `definitely_full_row`
- 最终虽然 `accepted=false`，但 metrics 中 semantic 字段会误导后续调试。

## 正确规则

只有在 motion / overlap evidence 足够可靠时，semantic row overlap 才是可解释的。

建议实现方式：

### A. 先得到 raw semantic overlap

可以继续调用现有：

```python
evaluate_semantic_row_overlap(...)
```

但在 `has_reliable_overlap == false` 且不属于 no-move 的情况下，将最终暴露给 metrics 的 semantic 结果覆盖为：

```python
{
    "semantic_overlap_state": "not_applicable_unreliable_motion",
    "ocr_overlap_pair_required": False,
    "full_row_candidates": [],
    "reason": "unreliable_motion_not_an_adjacent_pair",
}
```

同时保留仍有诊断价值的：

- `visual_overlap`
- `physical_overlap_px`
- `actual_shift_px`
- row lattice / centers（如果希望保留）
- runtime

但必须让业务/语义字段明确表示“不可解释”。

### B. no-move 继续保持原语义

已有：

```text
not_applicable_no_move
```

不要改掉。

所以优先级应类似：

1. `no_move` → `not_applicable_no_move`
2. `not has_reliable_overlap` → `not_applicable_unreliable_motion`
3. 否则 → 使用正常 semantic overlap：
   - `definitely_full_row`
   - `ambiguous`
   - `definitely_no_full_row`

## 重要边界

不要把“accepted=false”简单等同于“不可靠 motion”。

例如以下情况可能 motion evidence 是可靠的，但因为效率/范围不符合而 accepted=false：

- `efficiency_correction_required`
- `terminal_partial_candidate`
- true overshoot

这些情况下 semantic overlap 仍然可能有诊断价值，因此不要全部改成 not applicable。

判断依据必须是：

```python
has_reliable_overlap
```

或与它严格等价的“motion + local overlap evidence 可靠”条件，而不是 `accepted`。

---

# 任务 3：测试要求

至少补充/修正以下覆盖。

## 3.1 unreliable motion

构造 unrelated image 或明显不可靠 motion，要求：

```python
accepted is False
semantic_overlap_state == "not_applicable_unreliable_motion"
ocr_overlap_pair_required is False
relation is None
image_pair is None  # 如果跑完整 probe
```

并且不要错误落入：

- `definitely_full_row`
- `ambiguous`

## 3.2 no move

保留现有：

```python
semantic_overlap_state == "not_applicable_no_move"
ocr_overlap_pair_required is False
```

保证本轮修改没有覆盖掉它。

## 3.3 reliable but not accepted

至少保留一个 reliable motion 但 accepted=false 的测试，例如：

- terminal partial candidate
- true overshoot
- efficiency correction

要求 semantic overlap 仍正常计算，而不是 `not_applicable_unreliable_motion`。

也就是说：

```text
has_reliable_overlap == true
accepted == false
```

时 semantic state 仍可以是：

```text
definitely_full_row
ambiguous
definitely_no_full_row
```

## 3.4 terminal partial relation consistency

必须新增或调整测试，验证：

```text
relation == "overlap"
IFF
ocr_overlap_pair_required == true
```

至少覆盖 terminal partial confirmed 场景。

## 3.5 regression

现有所有 probe tests 都必须继续通过。

---

# 任务 4：实现时避免的事情

本轮不要：

- 修改滑动参数
- 修改 560–660 normal motion band
- 修改 610–630 target
- 修改 row pitch 166.5
- 修改 YuanStar geometry constants，除非发现明确代码错误并先报告
- 引入 OCR
- 调用 OCR
- 修改 YuanStar
- 修改业务 collector
- 修改生产自动采集流程
- 重新设计 terminal logic
- 修改 GUI 文案
- 新增复杂状态机
- 做设备泛化
- 自动操作 MuMu
- 自动执行新的 swipe
- commit / push

这轮只做语义一致性收口。

---

# 任务 5：验证

运行最小充分验证：

```text
1. Python compile
2. probe 单测
3. git diff --check
```

如果项目已有定向测试命令，优先用现有命令。

不要为了“更全面”去跑无关的大型测试套件。

验证后执行：

```powershell
git status --short
git diff -- agent/custom/action/star_backpack_capture_probe.py agent/tests/test_star_backpack_capture_probe.py
```

检查是否只有预期变化。

---

# 任务 6：runtime sync

代码与测试通过后，可以执行**现有 targeted runtime sync**，但：

- 只同步本轮 MaaYuan probe 相关文件
- 不启动/关闭 MaaYuan
- 不操控 MuMu
- 不发 swipe
- 不跑真实 smoke
- 不碰 runtime 其他配置

同步完成后验证源文件和 runtime 对应目标的 SHA-256 一致。

如果 sync 脚本本身无需修改，就不要修改它。

---

# 任务 7：最终报告格式

最后只按下面格式报告，不要扩展下一阶段：

## B1f.2.1 result
`PASS / PARTIAL / FAIL`

## Git
- branch
- HEAD
- changed files
- commit/push: NO

## Fix 1 — relation consistency
- 原问题
- 实际修复
- terminal partial confirmed 后 relation 与 `ocr_overlap_pair_required` 的最终规则
- 对应测试

## Fix 2 — unreliable motion semantic state
- 新 state 名称
- 触发条件
- 与 `not_applicable_no_move` 的优先级
- reliable-but-not-accepted 是否仍保留正常 semantic state
- 对应测试

## Regression
- Python compile
- probe tests：总数 / PASS
- git diff --check
- runtime sync：是否完成
- SHA-256：是否一致

## Scope
明确说明：
- 未修改滑动参数
- 未修改 YuanStar
- 未调用 OCR
- 未执行新的 MuMu swipe
- 未 commit
- 未 push

## Next
只写一句：

> 下一步等待用户打开 MuMu + MaaYuan 后，执行 2–3 次真实单滑 regression，核对 physical overlap / row phase / semantic state / pair 与肉眼画面是否一致。

---

# 验收标准

本轮只有同时满足以下条件才可 PASS：

1. terminal partial 不再写死 `relation="overlap"`；
2. `relation` 与 `ocr_overlap_pair_required` / `image_pair` 一致；
3. unreliable motion 明确输出 `not_applicable_unreliable_motion`；
4. unreliable motion 强制 `ocr_overlap_pair_required=false`；
5. no-move 仍保持 `not_applicable_no_move`；
6. reliable-but-not-accepted 仍正常执行 semantic row overlap；
7. probe 全部单测通过；
8. 没有 OCR 调用；
9. 没有修改滑动参数；
10. 没有自动执行 MuMu swipe；
11. 没有 commit / push。
