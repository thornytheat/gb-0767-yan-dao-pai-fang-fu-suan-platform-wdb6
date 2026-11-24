# 烟道排放复算台

环保值班员用烟道分钟监测、启停记录和报送小时单复算排放浓度。首页显示分钟有效性矩阵、小时浓度柱与报送差值，可逐级回到原件行号。

## 启动

```sh
docker compose up --build
```

打开 `http://localhost:18466/`。本地也可用 Python 3.12 运行。

```sh
python -m pip install -r requirements-test.txt
python -m flask --app app.main run --port 18466
python -m pytest -q
```

默认留档写入 `var/monitor.sqlite3`。Compose 使用 `monitor-data` 卷。需要清空自建环境时，可停止服务，再移除该卷或指定的本地数据库文件。

## 复算与交接

1. 选择「异常与迟补样例」，首页应测为 120，显示有效 91、工况免计 8、缺证 21。
2. 在「分钟有效性裁决」选「仅缺证」，查看氧量超界、同版冲突和仪器校准。工况重叠分钟在两份记录间以停机优先。
3. 在「报送差异对账」核对 08:00 复算 30.50、报送 29.75、差额 +0.75 mg/Nm³。09:00 的 44 个有效分钟低于 45 门槛。
4. 点击「归档复算」并重跑。相同原件复用运行编号。在「监测证据签发」下载带输入摘要、原值、裁决与勾稽的 JSON。
5. 选择「时钟回拨样例」并打开「报送差异对账」：回拨前后同刻采样各自保留（不互当修订），受影响两小时在校时确认前标「校时待确认·暂挂」、不出正式差额；在归档页提交交接凭据确认后，跨整点读数按真实时刻重算移出与移入小时，两班冲突凭据只接受先入库的一套。

五个预览接口均为 `GET /api/samples/{dirty|clean|rollback}/{stage}`，各工序按需计算；`stage` 值见深度登记（含 `clock` 校时视图）。自有数据通过 `POST /api/runs` 的 `files` 对象提交字符串 `window`、`minutes`、`modes`、`reports`，可选 `clock`（时钟回拨原件），也可提交 `{"sample":"dirty"}`。`GET /api/runs/{id}/{stage}` 查询归档，每次归档仅写入一个 SQLite 事务。`GET /api/runs` 列出历史，`GET /api/export/{id}` 签发证据。含 `clock` 的归档可用 `POST /api/runs/{id}/clock-confirmation`，body 为 `{"ticket":"交接凭据"}`：同凭据幂等，冲突凭据返回 409 `CLOCK_CONFIRM_CONFLICT`，确认后读回与证据单均为重算结果。

- [数据定义与计算边界](docs/DATA-DICTIONARY.md)
- [模块与陷阱验证](docs/DEPTH.md)
- [证据单复核步骤](docs/CERTIFICATE.md)
