# 复核监测证据单

从留档打开签发页，确认运行编号、监测烟道和分钟差额后下载一份 JSON。`originals` 中的原件解码成文本后以 UTF-8 重新编码，逐文件计算 SHA-256，应等于 `manifest.sha256`。

核验 `sha256` 时，从附件取出 `manifest`、`originals` 和 `results` 组成对象。深度排序对象键，以 UTF-8 编码 JSON，保留中文原字符，分隔符使用逗号和冒号且省略空白。结果是内容校验摘要。原件可用 `files` 对象重新归档，以 `run_id` 和逐行判据对照两次计算。

按 `results.validity.rows[].sources` 找分钟原件，`mode_sources` 定位工况；按 `results.reports.rows[].reports` 找报送单据。错误版本及 CSV 结构错误分别见 `oxygen.isolated` 和 `intake.files[].rejected`。

含时钟回拨的留档，未确认时 `results.clock.pending_hours` 列出挂起小时、`results.clock.repeats` 给出回拨同刻保留的原件行；确认后证据单附 `clock_confirmation`（交接凭据、回拨时刻与分钟数），`results` 为按真实时刻重算后的整包，挂起与 `CLOCK_REPEAT` 均清零，分钟勾稽差额仍须为 0。`originals.clock` 始终保留未确认原件文本，其 SHA-256 一并纳入 `manifest.sha256`。
