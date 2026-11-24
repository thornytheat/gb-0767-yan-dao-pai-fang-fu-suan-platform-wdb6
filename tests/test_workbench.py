from app.web import PAGES


def test_all_monitor_pages_have_server_rendered_evidence(client):
    assert '分钟有效性矩阵' in client.get('/').get_data(as_text=True)
    for slug,label in PAGES.items():
        response = client.get('/monitor/'+slug)
        assert response.status_code == 200, slug
        assert f'<h1>{label}</h1>' in response.get_data(as_text=True)


def test_export_link_after_archival(client):
    run_id = client.post('/api/runs',json={'sample':'dirty'}).json['run_id']
    page = client.get('/monitor/evidence?run='+run_id).get_data(as_text=True)
    assert f'/api/export/{run_id}' in page
    assert '分钟勾稽差额 <b>0</b>' in page


def test_reports_page_explains_clock_rollback_handover(client):
    page = client.get('/monitor/reports?sample=rollback').get_data(as_text=True)
    assert '时钟回拨小时 · 交接办法' in page
    assert '不得互当修订' in page
    assert '暂不出正式差额' in page
    assert '移出小时' in page and '移入小时' in page
    assert '只接受先入库的一套凭据' in page
    assert '校时待确认·暂挂' in page
    assert '回拨同刻采样保留' in page


def test_reports_page_reflects_confirmed_state(client):
    run_id = client.post('/api/runs', json={'sample': 'rollback'}).json['run_id']
    client.post(f'/api/runs/{run_id}/clock-confirmation', json={'ticket': '甲班-A'})
    page = client.get(f'/monitor/reports?run={run_id}').get_data(as_text=True)
    assert '校时已确认' in page
    # 静态交接说明常驻，但表格里不再有任何「暂挂」小时行。
    assert 'row-pending' not in page
    assert 'pending-flag' not in page


def test_normal_sample_reports_page_has_static_guidance(client):
    page = client.get('/monitor/reports?sample=clean').get_data(as_text=True)
    assert '时钟回拨小时 · 交接办法' in page  # 说明常驻，便于值班随时查阅
