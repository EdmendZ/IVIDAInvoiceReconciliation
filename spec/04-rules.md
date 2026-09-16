# 04 匹配与比对规则（ir-simple-rules-1）

## 1. 不允许自由发挥的边界

本版本匹配用确定性规则，不调用 LLM、embedding、模糊语义或外部商品库。没有可靠映射的商品不得猜测合并；缺失数据不得补 0。相同数量金额只提供比对依据，不能单独证明两张单据有关联。

## 2. 身份与候选

normalize_identity 固定：Unicode NFKC → casefold → 仅保留 Unicode 字母和数字（str.isalnum）。结果空字符串表示缺失，不是可匹配身份。原字段不修改。

供应商身份：双方 business_number 均非空时仅按规范化号码比较；否则双方规范化 name 非空且完全相同才算 equal；不同为 conflict、任一缺失为 unverified。ABN 存在但不同不能用同名覆盖。名称别名暂不支持；操作员可依据原件修正上传字段，上游记录需上游修正。

自动候选前置：receive_note、ready、同部署 scope、未 voided、未被其他发票正式占用、供应商 equal、币种 equal、双方日期存在且绝对间隔≤30日。日期之外候选不会自动预选；手动候选搜索可返回同店全部 ready 收货（分页 API 列表），选中时允许超过30天/缺日期但必须提供理由，主体/币种不允许豁免。

score：PO 双方非空且一致 +40；供应商 equal +20；币种 equal +10；日期差≤7日 +10，8..30日 +5；商品集合交集/发票商品数×20 向下取整。上限100。商品键按下一节，单位不同不算重合。PO 双方非空不同、无商品交集是自动候选阻断；同号跨单据**不单独阻断**，使用来源 ID 区分，不能沿用旧“同号即错误”假设。

自动选择固定：

1. 有 PO：所有通过前置和自动阻断检查、PO 与发票相同的候选组成一个组；1..100 张则预选全组，绝不根据数量碰巧相等去搜索组合。超过100张 needs_selection。
2. 无 PO 相同组：取 score≥60 的最高候选；若只有一个或比第二高至少高20分，则预选一张。并列或差距不足 needs_selection。
3. 没有可选候选：若没有同主体同币种 ready 收货，waiting_counterpart；存在这些记录但缺日期/商品重合/身份关联依据则 needs_selection。
4. invoice 自身供应商缺失或冲突字段待处理：needs_selection＋SUPPLIER_UNVERIFIED，不能显示只是在等收货。

手动选择冻结所选 document_id 集合；新版本到达重新比对，但不会自动扩充集合。新候选到达提示“发现新的收货记录”，用户可更换；不自动改掉明确选择。自动选择随新 ready 收货重新计算。所有自动关系都是预览，最终需要一次人确认。

Candidate reason_codes 固定：PO_MATCH/PO_CONFLICT/SUPPLIER_MATCH/SUPPLIER_UNVERIFIED/SUPPLIER_CONFLICT/CURRENCY_MATCH/CURRENCY_CONFLICT/DATE_NEAR/DATE_MISSING/DATE_OUTSIDE_WINDOW/ITEM_OVERLAP/NO_ITEM_OVERLAP/RECEIVING_IN_USE/SOURCE_VOIDED。无需拼接英文业务说明，用前端中文字典解释，业务原值另外显示。

## 3. 商品与单位

商品键优先 sku 非空，格式 `sku:<normalize>`；否则描述 `description:<normalize>`。空键 → EMPTY_ITEM_KEY，阻断。单位 trim＋casefold 后仅允许以下同义归一：kg/kgs/kilogram/kilograms→kg；g/gram/grams→g；l/litre/litres/liter/liters→l；ml/millilitre/millilitres→ml；each/ea/pc/pcs/piece/pieces→each；carton/cartons/ctn→carton；case/cases→case；bag/bags→bag。其他非空值保留规范化文本，不跨单位转换。

kg 与 g 本版本也不自动换算；包装转换未定义。unit 缺失→UNIT_UNVERIFIED 阻断；同商品双方单位不一致→UNIT_CONFLICT 阻断。聚合键包含单位，不能先把不同单位相加。没有 SKU 一侧与有 SKU 一侧不得靠描述偷偷关联，显示 invoice_only/receive_only，用户可按原件纠正 SKU。

同商品同单位的同侧行可以聚合数量；金额仅所有行金额可得时聚合；行金额缺失但 qty 与 unit_price 已知时使用乘积。聚合单价仅所有行单价已知且单价相同才产生单价；不同价格不做加权平均掩盖分批价格差异，price=unverified，reason=MULTIPLE_PRICES，金额和数量仍独立比较。原行引用必须保留。

## 4. 维度与容差

quantity 容差0，price 0.01 AUD，amount 0.02 AUD，固定存入 preview 和 confirmation，不允许请求传入。币种仅 AUD 可确认；其他币种预览 blocked UNSUPPORTED_CURRENCY，不能把 AUD 容差用于任意币种。

每个维度：缺任一值→unverified（difference=null）；差为0→equal；绝对差≤容差→within_tolerance；其他→different。quantity 基于现有正数 Schema；不支持贷项单/负数。金额先按原单据未税行金额口径计算；现有 qty×unit_price 与 line_total 内部一致性校验保留。

行总状态优先 invoice_only/receive_only，再 different，再 unverified，再 within_tolerance，最后 equal。price/amount unverified 不让整单 outcome blocked；仍能以 quantity_only 确认，必须明确 acknowledge。quantity 未知、空商品键、单位不可比则 blocking。

outcome：任一 blocking→blocked；否则出现行 different/invoice_only/receive_only→difference；其余 consistent。summary.unverified_lines 数缺少 price 或 amount 的行；coverage 为所有可对齐行都已核验的维度交集，quantity 始终为基础；没有对齐行时 outcome=difference，coverage=quantity_only，不宣称验证了商品对应关系。

不跨单据比较 subtotal/tax_total/total，因为 Receive Note 常无完整税费。现有单据内部 ValidationService 的误报需修正：只有所有行 tax_amount 都非空时才比较 tax_total，而非“任一行有税就把其余当0”。这些校验问题作为阻断进入预览；PO 缺失仍只是 warning。

## 5. 正式完成与占用

一致也必须 confirm，不自动完成。完成可确认 quantity_only，但界面不得展示“全部财务匹配”。difference 仅在用户明确 resolved_with_note 时关闭，正式快照继续保存原差异。

整张 Receive Note 被一个已完成发票独占。确认另一个发票使用它返回409 RECEIVING_IN_USE；数据库 PK 是最终保障。无法处理“一张收货单拆给多张发票”，明确提示当前不支持，不将其当系统识别错误。reopen 原发票释放所有占用；并发时由 scope 锁确定一个成功，不允许占用超配。

业务重复发票：同 scope＋规范化 supplier 身份＋规范化 invoice document_number 与另一非 voided 发票相同，阻断确认 DUPLICATE_INVOICE；同号文件不得自动删除，用户可作废重复上传。缺 supplier/number 不可绕过确认。文件重复 hash 在同 scope、同 type 的新上传请求返回现存 DocumentSummary 和相同 task/run（201，duplicate=true 作为 IntakeResponse 必填 bool 字段；首次 false），不重复调模型。

字段更正、上游版本变化、新收货到达均使未完成预览失效；旧 confirmation 永久保留。关闭有差异记录不表示系统替用户向供应商发送了消息或执行退款。
