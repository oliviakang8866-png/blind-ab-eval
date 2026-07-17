#!/usr/bin/env python3
"""
Build a live results dashboard (results.html) for a blind-ab-eval deployment.

Reads all vote rows straight from the Apps Script backend at page-load time
(via ?action=getAllVotes) — no CSV re-upload needed, always reflects the
current state of the Google Sheet. Shows, per evaluator and combined:
  - rows completed (GSB + both sides' quality review filled in)
  - per-model Fail / Pass / High Quality counts and rates
  - GSB win counts (model1 good / model2 good / both good / both bad)
  - Fail-reason and Pass-but-not-high-quality-reason breakdowns

IMPORTANT — this page reveals real model identity (if you provide
--row-model-map-csv) and is meant for whoever is running the evaluation, not
the evaluators themselves. Don't link to it from index.html or send it to
evaluators; it's a separate, unlisted URL.

Two ways to run it:

1. Labels in the Sheet are already the real identity (the common case: you
   passed real model names as --option1-label/--option2-label when building
   index.html, and they don't vary row to row):

    python3 build_results_page.py \\
      --exec-url "https://script.google.com/macros/s/XXXX/exec" \\
      --output results.html

2. Labels in the Sheet are generic (version1/version2) because the real
   model varies per row — pass a CSV with a row_index + two model-code
   columns and this script embeds the same row_index-keyed resolution logic
   used by scripts/translate_to_model_codes.py, done client-side in JS
   instead of offline in Python:

    python3 build_results_page.py \\
      --exec-url "https://script.google.com/macros/s/XXXX/exec" \\
      --row-model-map-csv "source_data.csv" \\
      --model1-col model_type1 --model2-col model_type2 \\
      --output results.html
"""
import argparse
import csv
import json


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--exec-url', required=True, help='The same Apps Script /exec URL used in index.html')
    p.add_argument('--title', default='评测结果看板', help='Page <h1> title')
    p.add_argument('--output', default='results.html')
    p.add_argument('--row-model-map-csv', default=None,
                    help='Optional: source CSV to resolve version1/version2 -> real per-row model codes. '
                         'Omit if A_model/B_model in the Sheet are already real, stable model names.')
    p.add_argument('--row-index-col', default=None,
                    help='Column in --row-model-map-csv giving the row index (default: use the CSV row order, 0-based)')
    p.add_argument('--model1-col', default='model_type1')
    p.add_argument('--model2-col', default='model_type2')
    return p.parse_args()


def build_row_model_map(args):
    if not args.row_model_map_csv:
        return {}
    with open(args.row_model_map_csv, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    m = {}
    for i, r in enumerate(rows):
        idx = r[args.row_index_col].strip() if args.row_index_col else str(i)
        m[idx] = [r[args.model1_col].strip(), r[args.model2_col].strip()]
    return m


HTML_TEMPLATE = r'''<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  * { box-sizing: border-box; }
  body {
    background: #000; color: #eee; margin: 0; padding: 24px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  h1 { font-size: 20px; font-weight: 600; margin: 0 0 6px 0; color: #fff; }
  .subtitle { color: #888; font-size: 12px; margin-bottom: 4px; }
  .warn { color: #d9a441; font-size: 12px; margin-bottom: 20px; }

  #toolbar {
    display: flex; gap: 14px; align-items: center; flex-wrap: wrap;
    background: #111; border: 1px solid #262626; border-radius: 10px;
    padding: 12px 16px; margin-bottom: 20px;
  }
  #toolbar select {
    background: #1c1c1c; color: #ddd; border: 1px solid #333; border-radius: 6px;
    padding: 6px 10px; font-size: 13px;
  }
  #toolbar button {
    background: #1c1c1c; border: 1px solid #333; color: #ccc; border-radius: 6px;
    padding: 6px 14px; font-size: 13px; cursor: pointer;
  }
  #toolbar button:hover { background: #2a2a2a; }
  #loading { color: #888; font-size: 13px; }

  .card {
    background: #111; border: 1px solid #262626; border-radius: 10px;
    padding: 18px; margin-bottom: 20px;
  }
  .card h2 { font-size: 14px; color: #fff; margin: 0 0 14px 0; }

  table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid #222; white-space: nowrap; }
  th { color: #999; font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: .02em; }
  td { color: #ddd; }
  tr:hover td { background: #161616; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .pill {
    display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px;
  }
  .pill.good { background: #123a12; color: #b6ffb6; }
  .pill.bad { background: #331414; color: #ffb0b0; }
  .pill.neutral { background: #1c1c1c; color: #999; }

  .stat-row { display: flex; gap: 24px; flex-wrap: wrap; margin-bottom: 6px; }
  .stat { display: flex; flex-direction: column; }
  .stat .v { font-size: 22px; font-weight: 700; color: #fff; }
  .stat .l { font-size: 11px; color: #999; margin-top: 2px; }

  .table-wrap { overflow-x: auto; }
</style>
</head>
<body>

<h1>__TITLE__</h1>
<div class="subtitle">实时读取 Google Sheet 打标结果 · __MAPPING_NOTE__</div>
<div class="warn">⚠️ 这个页面会展示真实模型对应关系，不要把链接发给评测人员</div>

<div id="toolbar">
  <label>筛选打分人：
    <select id="evaluator-filter" onchange="render()">
      <option value="">全部</option>
    </select>
  </label>
  <button onclick="loadData()">刷新数据</button>
  <span id="loading"></span>
</div>

<div id="content"></div>

<script>
const EXEC_URL = '__EXEC_URL__';
const ROW_MODEL_MAP = __ROW_MODEL_MAP_JSON__; // row_index -> [model1, model2], or {} if not needed

let allRows = [];
let allCompletions = [];

function resolveRowModels(row) {
  if (Object.keys(ROW_MODEL_MAP).length === 0) {
    return { aModel: row.A_model, bModel: row.B_model };
  }
  const m = ROW_MODEL_MAP[String(row.row_index)];
  if (!m) return { aModel: row.A_model, bModel: row.B_model };
  const resolve = function(v) { return v === 'version1' ? m[0] : (v === 'version2' ? m[1] : v); };
  return { aModel: resolve(row.A_model), bModel: resolve(row.B_model) };
}

function isRowComplete(row) {
  if (!row.choice) return false;
  if (!row.A_quality_status || !row.B_quality_status) return false;
  if (row.A_quality_status !== 'high_quality' && !row.A_quality_reason) return false;
  if (row.B_quality_status !== 'high_quality' && !row.B_quality_reason) return false;
  return true;
}

function loadData() {
  document.getElementById('loading').textContent = '加载中…';
  fetch(EXEC_URL + '?action=getAllVotes')
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (!d.ok) throw new Error('backend error');
      allRows = d.rows || [];
      allCompletions = d.completions || [];
      populateEvaluatorFilter();
      render();
      document.getElementById('loading').textContent =
        '已加载 ' + allRows.length + ' 条记录 · ' + new Date().toLocaleTimeString();
    })
    .catch(function(e) {
      document.getElementById('loading').textContent = '加载失败: ' + e.message;
    });
}

function populateEvaluatorFilter() {
  const sel = document.getElementById('evaluator-filter');
  const current = sel.value;
  const evaluators = Array.from(new Set(allRows.map(function(r) { return r.evaluator; }))).sort();
  sel.innerHTML = '<option value="">全部</option>' +
    evaluators.map(function(e) { return '<option value="' + esc(e) + '">' + esc(e) + '</option>'; }).join('');
  if (evaluators.indexOf(current) !== -1) sel.value = current;
}

function esc(s) {
  return (s || '').toString().replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function computeStats(rows) {
  const models = new Set();
  rows.forEach(function(r) {
    const m = resolveRowModels(r);
    if (m.aModel) models.add(m.aModel);
    if (m.bModel) models.add(m.bModel);
  });
  const modelList = Array.from(models).sort();

  const choiceCounts = { both_good: 0, both_bad: 0, empty: 0 };
  const modelWin = {};
  const qualityCounts = {}; // model -> {fail, pass, high_quality}
  const failReasons = {};   // model -> {reason: count}
  const notHqReasons = {};  // model -> {reason: count}
  modelList.forEach(function(m) {
    modelWin[m] = 0;
    qualityCounts[m] = { fail: 0, pass: 0, high_quality: 0 };
    failReasons[m] = {};
    notHqReasons[m] = {};
  });

  let completedCount = 0;
  rows.forEach(function(r) {
    const resolved = resolveRowModels(r);
    if (isRowComplete(r)) completedCount++;

    if (r.choice === 'both_good') choiceCounts.both_good++;
    else if (r.choice === 'both_bad') choiceCounts.both_bad++;
    else if (!r.choice) choiceCounts.empty++;
    else {
      const winner = r.choice === 'version1' || r.choice === r.A_model ? resolved.aModel
                    : r.choice === 'version2' || r.choice === r.B_model ? resolved.bModel
                    : r.choice; // already a real code
      if (modelWin[winner] === undefined) modelWin[winner] = 0;
      modelWin[winner]++;
    }

    [['A', resolved.aModel], ['B', resolved.bModel]].forEach(function(pair) {
      const side = pair[0], model = pair[1];
      if (!model) return;
      const status = r[side + '_quality_status'];
      const reason = r[side + '_quality_reason'];
      if (!status) return;
      if (!qualityCounts[model]) qualityCounts[model] = { fail: 0, pass: 0, high_quality: 0 };
      if (qualityCounts[model][status] !== undefined) qualityCounts[model][status]++;
      if (status === 'fail' && reason) {
        reason.split('; ').forEach(function(single) {
          single = single.trim();
          if (!failReasons[model]) failReasons[model] = {};
          failReasons[model][single] = (failReasons[model][single] || 0) + 1;
        });
      } else if (status === 'pass' && reason) {
        reason.split('; ').forEach(function(single) {
          single = single.trim();
          if (!notHqReasons[model]) notHqReasons[model] = {};
          notHqReasons[model][single] = (notHqReasons[model][single] || 0) + 1;
        });
      }
    });
  });

  return {
    modelList: modelList, totalRows: rows.length, completedCount: completedCount,
    choiceCounts: choiceCounts, modelWin: modelWin, qualityCounts: qualityCounts,
    failReasons: failReasons, notHqReasons: notHqReasons,
  };
}

function topReasons(reasonMap, n) {
  return Object.keys(reasonMap)
    .map(function(k) { return [k, reasonMap[k]]; })
    .sort(function(a, b) { return b[1] - a[1]; })
    .slice(0, n || 8);
}

function pct(n, d) { return d ? (n / d * 100).toFixed(1) + '%' : '—'; }

function render() {
  if (!allRows.length) return;
  const filterEvaluator = document.getElementById('evaluator-filter').value;
  const rows = filterEvaluator ? allRows.filter(function(r) { return r.evaluator === filterEvaluator; }) : allRows;
  const stats = computeStats(rows);

  let html = '';

  // Overview cards
  html += '<div class="card"><h2>' + (filterEvaluator ? esc(filterEvaluator) + ' 的打标情况' : '全部评测人合计') + '</h2>';
  html += '<div class="stat-row">';
  html += '<div class="stat"><span class="v">' + stats.totalRows + '</span><span class="l">总打标行数</span></div>';
  html += '<div class="stat"><span class="v">' + stats.completedCount + '</span><span class="l">完全填完（GSB+双边质量）</span></div>';
  html += '<div class="stat"><span class="v">' + allCompletions.length + '</span><span class="l">点击过"提交本次评测"的人数</span></div>';
  html += '</div></div>';

  // GSB breakdown
  html += '<div class="card"><h2>GSB 选择分布</h2><div class="table-wrap"><table><tr><th>选项</th><th class="num">次数</th><th class="num">占比</th></tr>';
  const totalChoice = Object.values(stats.modelWin).reduce(function(a,b){return a+b;}, 0) + stats.choiceCounts.both_good + stats.choiceCounts.both_bad;
  stats.modelList.forEach(function(m) {
    const c = stats.modelWin[m] || 0;
    html += '<tr><td>' + esc(m) + ' good</td><td class="num">' + c + '</td><td class="num">' + pct(c, totalChoice) + '</td></tr>';
  });
  html += '<tr><td>都好</td><td class="num">' + stats.choiceCounts.both_good + '</td><td class="num">' + pct(stats.choiceCounts.both_good, totalChoice) + '</td></tr>';
  html += '<tr><td>都不好</td><td class="num">' + stats.choiceCounts.both_bad + '</td><td class="num">' + pct(stats.choiceCounts.both_bad, totalChoice) + '</td></tr>';
  html += '<tr><td>未选（空）</td><td class="num">' + stats.choiceCounts.empty + '</td><td class="num">—</td></tr>';
  html += '</table></div></div>';

  // Per-model quality breakdown
  html += '<div class="card"><h2>各模型 Fail / Pass / High Quality</h2><div class="table-wrap"><table>';
  html += '<tr><th>模型</th><th class="num">已评分</th><th class="num">Fail</th><th class="num">Pass</th><th class="num">High Quality</th><th class="num">Pass率(Pass+HQ)</th></tr>';
  stats.modelList.forEach(function(m) {
    const q = stats.qualityCounts[m];
    const rated = q.fail + q.pass + q.high_quality;
    html += '<tr><td>' + esc(m) + '</td><td class="num">' + rated + '</td>' +
      '<td class="num">' + q.fail + ' (' + pct(q.fail, rated) + ')</td>' +
      '<td class="num">' + q.pass + ' (' + pct(q.pass, rated) + ')</td>' +
      '<td class="num">' + q.high_quality + ' (' + pct(q.high_quality, rated) + ')</td>' +
      '<td class="num"><span class="pill good">' + pct(q.pass + q.high_quality, rated) + '</span></td></tr>';
  });
  html += '</table></div></div>';

  // Fail / not-high-quality reason breakdown, side by side per model
  stats.modelList.forEach(function(m) {
    html += '<div class="card"><h2>' + esc(m) + ' — 原因明细</h2><div class="stat-row" style="align-items:flex-start;">';
    html += '<div style="flex:1;min-width:260px;"><b style="font-size:12px;color:#ffb0b0;">Top Fail 原因</b><table style="margin-top:8px;">';
    topReasons(stats.failReasons[m], 8).forEach(function(pair) {
      html += '<tr><td>' + esc(pair[0]) + '</td><td class="num">' + pair[1] + '</td></tr>';
    });
    html += '</table></div>';
    html += '<div style="flex:1;min-width:260px;"><b style="font-size:12px;color:#ffd98a;">Top Not-High-Quality 原因（Pass但不完美）</b><table style="margin-top:8px;">';
    topReasons(stats.notHqReasons[m], 8).forEach(function(pair) {
      html += '<tr><td>' + esc(pair[0]) + '</td><td class="num">' + pair[1] + '</td></tr>';
    });
    html += '</table></div>';
    html += '</div></div>';
  });

  // Per-evaluator summary table (always shows everyone, regardless of filter)
  html += '<div class="card"><h2>按评测人拆分</h2><div class="table-wrap"><table>';
  html += '<tr><th>评测人</th><th class="num">打标行数</th><th class="num">完全填完</th>';
  stats.modelList.forEach(function(m) {
    html += '<th class="num">' + esc(m) + ' Fail/Pass/HQ</th>';
  });
  html += '<th class="num">GSB 胜出</th></tr>';
  const evaluators = Array.from(new Set(allRows.map(function(r) { return r.evaluator; }))).sort();
  evaluators.forEach(function(ev) {
    const evRows = allRows.filter(function(r) { return r.evaluator === ev; });
    const evStats = computeStats(evRows);
    html += '<tr><td>' + esc(ev) + '</td><td class="num">' + evRows.length + '</td><td class="num">' + evStats.completedCount + '</td>';
    stats.modelList.forEach(function(m) {
      const q = evStats.qualityCounts[m] || { fail: 0, pass: 0, high_quality: 0 };
      html += '<td class="num">' + q.fail + '/' + q.pass + '/' + q.high_quality + '</td>';
    });
    const winStr = stats.modelList.map(function(m) { return esc(m) + ':' + (evStats.modelWin[m] || 0); }).join('  ');
    html += '<td class="num">' + winStr + '</td></tr>';
  });
  html += '</table></div></div>';

  document.getElementById('content').innerHTML = html;
}

loadData();
</script>
</body>
</html>
'''


def main():
    args = parse_args()
    row_model_map = build_row_model_map(args)
    mapping_note = (
        f'已加载 {len(row_model_map)} 行的真实模型映射' if row_model_map
        else 'A_model/B_model 直接作为模型标识使用（未提供额外映射）'
    )

    html_doc = (HTML_TEMPLATE
        .replace('__TITLE__', args.title)
        .replace('__EXEC_URL__', args.exec_url)
        .replace('__ROW_MODEL_MAP_JSON__', json.dumps(row_model_map, ensure_ascii=False))
        .replace('__MAPPING_NOTE__', mapping_note)
    )

    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(html_doc)
    print(f'Wrote {args.output} ({len(html_doc)} bytes)')


if __name__ == '__main__':
    main()
