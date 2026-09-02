"""本地 mock info-plate 服务：模拟 3 个监控 API + HTML 首页（含分页）。

启动:
    python -m tests.mock_alarm_server
默认监听 http://127.0.0.1:58080
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

_HOST = "127.0.0.1"
_PORT = 58080


def _mock_rate(config_id: str) -> dict:
    return {
        "name": "下单失败监控",
        "configId": config_id,
        "count": 42,
        "yesterdayCount": 15,
        "lastWeekCount": 38,
    }


def _mock_config(config_id: str) -> dict:
    return {
        "name": "下单失败监控",
        "remark": "订单创建失败监控",
        "tableId": 10026,
        "configId": config_id,
        "faasParam": json.dumps({
            "tableId": 10026,
            "conditions": [{"column": "env", "type": "str", "condition": ["prod"]}],
        }),
    }


_TOTAL_DETAIL = 80


def _mock_detail(limit: int = _TOTAL_DETAIL) -> list:
    scenarios = ["提单", "支付", "取消订单", "查询订单"]
    pages = ["下单页", "购物车", "结算页"]
    main_msg, main_flag, main_url = ("Connection timeout", "network_error", "/api/order/create")
    noises = [
        ("500 Internal Server Error", "server_error", "/api/order/commit"),
        ("库存不足", "biz_error", "/api/order/check"),
    ]
    out = []
    for i in range(limit):
        if i < int(limit * 0.85):
            msg, flag, url = main_msg, main_flag, main_url
        else:
            msg, flag, url = noises[(i - int(limit * 0.85)) % len(noises)]
        out.append({
            "id": i + 1,
            "time": f"2026-09-01 10:{20 + i // 60:02d}:{i % 60:02d}",
            "adiu": f"u{1000 + i}",
            "diu": f"d{2000 + i}",
            "upload_time": f"2026-09-01 10:{20 + i // 60:02d}:{i % 60:02d}",
            "ajx_ver": "1.2.3",
            "tag": "order",
            "sub_tag": "create",
            "scene": scenarios[i % len(scenarios)],
            "operate_msg": "click submit",
            "page_name": pages[i % len(pages)],
            "order_id": f"ORD{20260901000000 + i}",
            "bundle_name": "com.example.app",
            "env": "prod",
            "content": "button clicked",
            "eagleeye_trace_id": f"trace-xxx-{i}",
            "uid": f"u{12345 + i}",
            "div1": "main",
            "err_flag": flag,
            "err_msg": msg,
            "url": url,
        })
    return out


_HTML_PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>Info-Plate Mock 监控平台</title>
<style>
body{font-family:-apple-system,Segoe UI,Arial,sans-serif;margin:24px;background:#f6f7f9}
.card{background:#fff;border-radius:8px;padding:16px 20px;margin-bottom:16px;
 box-shadow:0 1px 3px rgba(0,0,0,.08)}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:16px;margin:0 0 12px;color:#333}
.kv{display:flex;gap:24px;color:#555;font-size:13px;flex-wrap:wrap}
.kv b{color:#222}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:8px 10px;text-align:left;border-bottom:1px solid #eee}
th{background:#fafafa;color:#555;font-weight:600}
.tag{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;background:#fff0f0;color:#c33}
.ok{color:#18a148}.warn{color:#c47d00}.err{color:#d93025}
code{background:#f0f0f0;padding:1px 6px;border-radius:3px}
.pager{display:flex;align-items:center;gap:6px;margin-top:12px;color:#555;font-size:13px;flex-wrap:wrap}
.pager button{padding:4px 10px;border:1px solid #ddd;background:#fff;border-radius:4px;
 cursor:pointer;min-width:32px}
.pager button:hover:not(:disabled){border-color:#1677ff;color:#1677ff}
.pager button:disabled{opacity:.4;cursor:not-allowed}
.pager button.active{background:#1677ff;color:#fff;border-color:#1677ff}
.pager .dots{padding:0 4px;color:#aaa}
.pager .info{margin-left:auto;color:#888}
</style></head><body>

<div class="card">
  <h1>📊 下单失败监控</h1>
  <div class="kv">
    <span>指标: <b>下单失败次数</b></span>
    <span>配置ID: <code>12345</code></span>
    <span>数据范围: <b>2026-09-01 10:00 ~ 10:30</b></span>
  </div>
</div>

<div class="card">
  <h2>监控速率</h2>
  <div class="kv">
    <span>当前: <b class="err">42</b></span>
    <span>昨日: <b>15</b></span>
    <span>上周: <b>38</b></span>
    <span>日环比: <span class="tag">↑ 180%</span></span>
  </div>
</div>

<div class="card">
  <h2>错误明细</h2>
  <table>
    <thead><tr>
      <th>#</th><th>时间</th><th>错误</th><th>接口</th><th>场景</th><th>UID</th>
    </tr></thead>
    <tbody id="tbody"><tr><td colspan="6" style="color:#888">加载中…</td></tr></tbody>
  </table>
  <div class="pager" id="pager"></div>
</div>

<script>
(async () => {
  const API = '/api/ability/monitorDetail';
  const PAGE_SIZE = 20;
  let current = 1, total = 0, totalPages = 1;

  async function load(page) {
    const res = await fetch(API + '?_=' + Date.now(), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        columns:['time','err_msg','err_flag','url','scene','uid'],
        where:[{column:'time',type:'str',condition:['','']}],
        conditions:[], tableId:10026, orderByKey:'time',
        page: page, pageSize: PAGE_SIZE,
      }),
    });
    const json = await res.json();
    const data = json.data || {};
    const rows = data.list || [];
    total = data.total || rows.length;
    totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    current = page;
    renderRows(rows);
    renderPager();
  }

  function renderRows(rows) {
    document.getElementById('tbody').innerHTML = rows.map((r,i)=>
      `<tr><td>${(current-1)*PAGE_SIZE+i+1}</td>
       <td>${r.time||''}</td>
       <td style="color:${r.err_flag==='network_error'?'#d93025':'#c47d00'}">${r.err_msg||''}</td>
       <td><code>${r.url||''}</code></td>
       <td>${r.scene||''}</td><td>${r.uid||''}</td></tr>`
    ).join('') || `<tr><td colspan="6" style="color:#888">暂无数据</td></tr>`;
  }

  function renderPager() {
    const p = document.getElementById('pager');
    const parts = [];
    parts.push(`<button ${current===1?'disabled':''} data-p="${current-1}">‹ 上一页</button>`);
    const nums = [];
    for (let i=1;i<=totalPages;i++) {
      if (i===1 || i===totalPages || Math.abs(i-current)<=1) nums.push(i);
      else if (nums[nums.length-1] !== '...') nums.push('...');
    }
    for (const n of nums) {
      if (n === '...') parts.push(`<span class="dots">…</span>`);
      else parts.push(`<button class="${n===current?'active':''}" data-p="${n}">${n}</button>`);
    }
    parts.push(`<button ${current===totalPages?'disabled':''} data-p="${current+1}">下一页 ›</button>`);
    parts.push(`<span class="info">共 ${total} 条，每页 ${PAGE_SIZE} 条</span>`);
    p.innerHTML = parts.join('');
    p.querySelectorAll('button[data-p]').forEach(b=>{
      b.onclick = () => load(parseInt(b.dataset.p,10));
    });
  }

  load(1);
})();
</script>

</body></html>
"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[MOCK] {self.address_string()} - {fmt % args}")

    def _json(self, obj: dict, status: int = 200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html: str, status: int = 200):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._json({})

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path in ("/", "/monitor/searchall"):
            self._html(_HTML_PAGE)
            return

        cfg_id = (qs.get("id") or ["12345"])[0]

        if path.endswith("/api/monitor/getMonitorRate") or path.endswith("/monitor/getMonitorRate"):
            self._json({"code": 200, "msg": "ok", "data": _mock_rate(cfg_id)})
            return

        if path.endswith("/api/monitor/queryBusinessMarketConfig") or path.endswith("/monitor/queryBusinessMarketConfig"):
            cfg = _mock_config(cfg_id)
            self._json({"code": 200, "msg": "ok", "data": cfg})
            return

        self._json({"code": 404, "msg": f"not found: {path}"}, status=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            body = {}

        if path.endswith("/api/ability/monitorDetail") or path.endswith("/ability/monitorDetail"):
            limit = max(1, int(body.get("pageSize") or 10))
            page = max(1, int(body.get("page") or 1))
            all_items = _mock_detail(limit=_TOTAL_DETAIL)
            start = (page - 1) * limit
            chunk = all_items[start:start + limit]
            self._json({"code": 200, "msg": "ok", "data": {
                "list": chunk,
                "total": len(all_items),
                "page": page,
                "pageSize": limit,
            }})
            return

        self._json({"code": 404, "msg": f"not found: {path}"}, status=404)


class MockAlarmServer:
    def __init__(self, host: str = _HOST, port: int = _PORT):
        self.host = host
        self.port = port
        self._srv: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self):
        self._srv = ThreadingHTTPServer((self.host, self.port), _Handler)
        print(f"[MOCK] alarm mock server listening on {self.base_url}")
        self._srv.serve_forever()

    def start_in_thread(self) -> "MockAlarmServer":
        self._thread = threading.Thread(target=self.start, daemon=True)
        self._thread.start()
        import time
        time.sleep(0.3)
        return self

    def stop(self):
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()
            print("[MOCK] server stopped")


if __name__ == "__main__":
    print("打开浏览器访问:", f"http://{_HOST}:{_PORT}/")
    MockAlarmServer(host=_HOST, port=_PORT).start()