# MaaYuan × YuanStar B1f.2：区分物理 overlap 与 OCR 语义 overlap，建立“完整行 envelope”判断

## 目标

继续当前 `MaaYuan-v5-dev` 的星石背包采集探针工作。

这一轮不要再把“物理共享像素高度”直接等价成“YuanStar 需要标记 overlap pair”。

要正式拆成两个概念：

1. **visual / physical overlap**
   - 两张相邻截图在画面上是否存在共享内容；
   - 用于证明没有跳页、辅助估计真实位移；
   - 可以存在较明显的共享画面。

2. **OCR-semantic overlap**
   - 共享画面中，是否存在**至少一整行星石能够在前后两张图里都作为完整 OCR 行出现**；
   - 只有这一条件成立，才应该给 YuanStar 写入 `ProductOverlapPair / confirmedOverlapPairs`；
   - 若只有半行、只有名称、只有圆盘下半、缺等级等，即使物理上有 overlap，也不应标成 OCR overlap pair。

这是这一轮的核心边界。

## 必须保持

- MaaYuan 不做星石 OCR。
- MaaYuan 不识别“这是天府/巨门/破军”。
- MaaYuan 不定位具体 duplicate 星石。
- MaaYuan 只负责截图、真实位移/视觉关系判断、以及是否需要给 YuanStar 标记相邻图片为 overlap pair。
- 具体 duplicate 行和星石内容仍由 YuanStar 现有 OCR / reconcile / review 链路完成。
- 手动图片上传路径保持不变。
- YuanStar 现有 OCR 模型不修改。
- 不修改 Backend / YuanHub 云接口。
- 不改生产 UI 文案与普通用户流程；当前仍是开发探针阶段。

## 当前真实问题

现有规则仍然带有“共享像素高度 / 行距”的硬阈值倾向：

- 物理 overlap 可能有约 150–180 px；
- 但这 150–180 px 可能只是某一行的半截；
- 例如 candidate 顶端只剩上一页某一整行的圆盘下部与名称，等级已经不在；
- 此时：
  - `visual_overlap = true`
  - 但应当 `ocr_overlap_pair_required = false`

相反，如果共享区域里完整包含一整行从等级/头像区域到名称区域的全部必要信息，则：
- `visual_overlap = true`
- `ocr_overlap_pair_required = true`

因此不能继续用单一 `overlap_px >= 某个 row_pitch 比例` 决定语义 overlap。

# 可操作仓库 / 路径

## MaaYuan

`D:\Users\Yan\Projects\MaaYuan-v5-dev`

当前工作分支预期：

`feat/yuanstar-capture-probe`

先执行：

```powershell
Set-Location D:\Users\Yan\Projects\MaaYuan-v5-dev
git status --short --branch
git log -1 --oneline
```

禁止：
- `git reset --hard`
- `git clean`
- `git pull`
- `git merge`
- `git rebase`
- `git stash`
- 删除当前未提交工作

如果分支与预期不同，只报告，不自动切换。

## YuanStar 可维护源码

优先检查当前已用于 YuanHub embed 的可维护工作树，不要把编译 bundle 当源码：

`D:\Users\Yan\AppData\.codex\yuanstar-yuanhub`

YuanStar 本轮默认 **只读审查**。

除非发现为了暴露一个纯几何常量必须做极小重构，否则不要修改 YuanStar。
如果需要修改，先停下来在报告里提出，不要直接改。

# Phase 1：审查 YuanStar 当前“完整行”的真实几何定义

目标：回答以下问题，并给出源码依据。

## 1. 找到当前主星/辅星 OCR 的：

- 行分割 / row segmentation
- 行中心 / row pitch
- 每行有效 ROI
- 等级 ROI
- 名称 ROI
- 品质 / 圆盘相关 ROI
- 任何“残片 / incomplete row / partial row”判断
- 任何“整行 overlap”判定或四列全匹配约束
- 任何会影响“这一行是否算完整可 OCR”的纵向边界

不要只看测试名字，要找到运行时代码。

## 2. 输出一个明确的“完整行 envelope”合同

不要立即写死数值，先从真实代码推导。

建议形式：

```text
row_center_y
ocr_row_top = row_center_y - A
ocr_row_bottom = row_center_y + B
```

或者如果 YuanStar 并不是 row-center 模式：

```text
row_top
required_top_margin
required_bottom_margin
```

核心是最终必须回答：

> 对一行星石而言，从图像纵向上看，至少哪些区域必须同时完整存在，才能算“这一行在这张图里可作为完整 OCR 行处理”？

如果不同类别（主星 / 辅星）几何一致，统一合同。
如果确实不同，明确分开。

## 3. 不要把经验星石混进本轮

本轮先只处理：
- 主星
- 辅星

经验星石后续单独接。

# Phase 2：审查 MaaYuan 当前探针

重点检查当前：

- `agent/custom/action/star_backpack_capture_probe.py`
- `assets/resource/base/pipeline/star_backpack_feedback_probe.json`
- `assets/interface.json`
- `tools/sync_yuanstar_probe_runtime.ps1`
- `agent/tests/test_star_backpack_capture_probe.py`

以及实际相关文件。

确认当前已有：

- real shift / actual displacement
- ORB / descriptor / grayscale / gradient similarity
- direct normal-band proposer
- row pitch / anchor / coverage
- full-overlap / terminal-partial / bottom-no-move
- single_swipe_calibration
- settle 时间
- metrics 输出

不要重复造已有能力。

# Phase 3：实现“row lattice + semantic overlap”判断

## 核心原则

不要 OCR。
不要识别星石名字。
不要识别具体哪一颗重复。

只做轻量几何视觉。

## A. 先检测 candidate / prev 的 row lattice

页面是 4 列规则网格。

优先复用当前已有：
- 灰度
- 梯度
- 边缘
- 相关性
- row pitch
- 周期特征

目标是得到类似：

```text
row_centers_prev = [...]
row_centers_candidate = [...]
estimated_row_pitch ≈ ...
```

要求：

- 每张图独立重新估计 row phase；
- 不要依赖“历史累计 swipe 距离”；
- 不要让一次误差在十几页后累积；
- 真正依据当前画面判断页面停在哪里。

如果当前代码已经有足够 row phase / anchor 信息，应直接复用，而不是另起一套复杂 CV。

## B. 定义完整 OCR row envelope

使用 Phase 1 从 YuanStar 源码推导出的真实几何合同。

例如概念上：

```text
row_center
  ├─ level / portrait 必须存在
  ├─ star disk / quality 必须存在
  └─ name 必须存在
```

不是只看圆盘中心。

## C. 计算 physical shared region

基于实际检测到的 shift，而不是命令 swipe 值：

```text
prev shared region:
[H - shift, H]

candidate shared region:
[0, H - shift]
```

如果现有实现坐标定义不同，按当前真实坐标系计算，不要机械照抄。

## D. 判断是否有完整 row 同时落在共享区域

只有当某一实际 row 的完整 `ocr_row_envelope` 在前后两图共享区域里都完整存在时：

`ocr_overlap_pair_required = true`

否则：

`ocr_overlap_pair_required = false`

即使：

`visual_overlap = true`

也允许 false。

# 安全 margin

不要出现差 1 px 就翻转语义的脆弱硬边界。

为完整 row envelope 增加一个小的保守 margin，优先从当前 ROI 尺寸与真实截图推导。

建议只作为初始范围参考：

`8–12 px`

但最终值由真实几何决定。

三态内部结果可以是：

- `definitely_no_full_row`
- `ambiguous`
- `definitely_full_row`

业务映射：

- `definitely_full_row`
  - 标记 OCR overlap pair

- `definitely_no_full_row`
  - 不标记 OCR overlap pair

- `ambiguous`
  - 保守标记 overlap pair
  - 但 metrics 必须写明是 ambiguous，不得伪装成高置信

# 不要用单一 overlap_px 阈值做最终语义决定

允许保留：

- `visual_overlap_px`
- `shift_px`
- `row_pitch`

作为诊断字段。

但以下模式不得继续作为最终唯一判断：

`overlap_px >= row_pitch * 0.9`

最终决定必须依赖：

`共享区域 + 实际 row phase / row centers + YuanStar-derived complete row envelope`

# Metrics / diagnostics

至少包括：

```json
{
  "visual_overlap": true,
  "physical_overlap_px": 0,
  "actual_shift_px": 0,
  "row_pitch_px": 0,
  "prev_row_centers": [],
  "candidate_row_centers": [],
  "ocr_row_envelope": {
    "top_offset": 0,
    "bottom_offset": 0,
    "safety_margin_px": 0,
    "source": "yuanstar_runtime_geometry"
  },
  "semantic_overlap_state": "definitely_no_full_row | ambiguous | definitely_full_row",
  "ocr_overlap_pair_required": false,
  "full_row_candidates": [],
  "reason": "..."
}
```

如果完整数组太大，可以压缩，但要保留足够调试信息。

# YuanStar CaptureBatch 输出语义

最终对 YuanStar 的 CaptureBatch：

- 图片仍全部正常导入；
- 物理共享画面不直接写 overlap pair；
- 只有 `ocr_overlap_pair_required = true` 时，才写入当前相邻图片 pair；
- 仍然只写：
  - `previous_image_id`
  - `current_image_id`
  - `relation=overlap`
- 不要提前写具体 duplicate 行/星石。

原有 `ProductOverlapPair -> confirmedOverlapPairs` 链路保持。

# 必须保护的现有行为

以下不能被本轮破坏：

- 单次 swipe calibration
- 真实 shift 检测
- terminal partial
- bottom no move
- no-move 终止
- max-pages / incomplete 保护
- 手动上传
- YuanStar OCR
- review
- current inventory
- cloud sync
- existing capture adapter
- current source -> embed bundle 同步链路

# 测试要求

至少补以下测试：

## case A：只有物理 overlap，没有完整 OCR row

共享区域只包含：
- 上一行下半
- 名称
- 或圆盘部分
- 缺等级 / 缺完整 envelope

预期：
- `visual_overlap = true`
- `ocr_overlap_pair_required = false`

## case B：完整一行落在共享区

预期：
- `visual_overlap = true`
- `ocr_overlap_pair_required = true`

## case C：边界 ambiguous

预期：
- state = ambiguous
- 业务层保守标 pair

## case D：no move

保持现有结果。

## case E：terminal partial

保持现有结果，不被 row lattice 误判。

## case F：不同 row phase

同样 shift，但 row phase 不同，语义结果可不同。
证明不再只由 overlap_px 决定。

## 旧测试必须全过

至少执行项目当前相关测试 + Python compile。

## 真实历史截图回归

优先复用用户刚刚已经产生的真实 probe 产物，不要要求重新 MuMu swipe 才能完成第一轮。

重点检查已有几组约：
- 581 px
- 611 px
- 596 / 622 / 640 px 附近

不要根据数字预设答案，要看真实画面：
- 是否仅半行共享
- 是否有整行完整重复

输出逐组判断理由。

如果本地历史 run 目录可定位，直接读取；
找不到则报告缺少哪一组文件，不要造数据。

# 性能要求

- 不调用 OCR；
- 不跑整图昂贵模板识别；
- 优先在现有内容 ROI / shared region 做；
- 记录单次 semantic overlap 判断耗时；
- 正常目标：几十毫秒级；
- 若超过 100ms，必须在报告说明瓶颈；
- 不为了追求 1–2ms 做复杂预优化。

# 本轮不要做

不要扩范围到：

- 主星自动完整多页采集正式任务
- 辅星完整多页采集
- 经验星石
- 自动切 tab
- 自动回顶
- 自动停止完整生产流程
- 网络 transport
- YuanHub 上传
- Backend
- OCR 模型优化
- operator/loadout
- 推荐
- production UI
- commit
- push

这一轮只把：

`物理 overlap != OCR 语义 overlap`

这个合同真正落到代码与测试中。

# Runtime 同步

代码与测试通过后：

如果 MaaYuan runtime 当前未运行，可以执行 targeted sync：

```powershell
Set-Location D:\Users\Yan\Projects\MaaYuan-v5-dev
.\tools\sync_yuanstar_probe_runtime.ps1 `
  -RuntimePath "D:\Users\Yan\Projects\MaaYuan-v5-runtime"
```

如果 runtime 正在运行，不要强行覆盖。
报告用户先关闭 MaaYuan，再同步。

不要碰：
- MaaYuan.exe
- MFAAvalonia
- Python runtime
- 其他任务
- 用户配置
- 日志
- 非本轮 interface 项

# 最终报告格式

## 1. Git / scope
- MaaYuan branch
- HEAD
- changed files
- 是否修改 YuanStar（正常应为否）

## 2. YuanStar geometry audit
明确列出：
- row pitch / row segmentation 来源
- 完整 OCR 行 envelope 是如何从源码推导出的
- 涉及哪些 ROI
- 主星/辅星是否共用
- 源文件与关键函数

## 3. MaaYuan semantic-overlap implementation
明确说明：
- row lattice 如何得到
- physical overlap 如何得到
- complete row 如何判断
- ambiguous 如何处理
- 什么情况下写 ProductOverlapPair

## 4. Real capture regressions
对现有真实 run 逐组列出：

```text
run
actual_shift
physical_overlap
row_phase
semantic_overlap_state
ocr_overlap_pair_required
reason
runtime_ms
```

## 5. Tests
逐项列出命令和结果。

## 6. Runtime sync
- 是否同步
- 若同步，目标 runtime
- 文件哈希/一致性
- 若未同步，原因

## 7. Final verdict

只允许：
- `PASS`
- `PARTIAL`
- `FAIL`

并指出第一个未满足项。

# 成功标准

本轮 PASS 必须满足：

1. 已从 YuanStar 真实源码推导完整行 envelope，而不是拍脑袋阈值；
2. visual overlap 与 OCR-semantic overlap 已分离；
3. 最终是否写 overlap pair 不再由 overlap_px 单阈值决定；
4. 只有完整 OCR 行落入共享区域时才默认写 pair；
5. ambiguous 有保守策略；
6. no-move / terminal-partial / single-swipe calibration 未回归；
7. 不调用 OCR；
8. 历史真实截图回归合理；
9. 未 commit / push。
