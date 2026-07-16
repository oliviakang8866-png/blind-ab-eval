#!/usr/bin/env python3
"""
Build a self-contained blind A/B evaluation HTML page from a CSV.

Generates a GitHub-Pages-ready index.html: each row shows a user photo +
product photo (small header thumbnails), a template/reference image, and two
generated-image options in randomized left/right order (never revealed to the
evaluator). Evaluators pick A/B/both-good/both-bad, leave an optional remark,
and separately mark each option Fail/Pass/High Quality with a multi-select
reason checklist. Every action auto-saves via a POST to a Google Apps Script
web app backend (see assets/Code.gs) that appends rows to a Google Sheet.

Usage:
    python3 build_report.py \\
      --csv path/to/data.csv \\
      --exec-url https://script.google.com/macros/s/XXXX/exec \\
      --option1-col gen_url_v1 --option1-label "v1" \\
      --option2-col gen_url_v2 --option2-label "v2" \\
      --output index.html

Run with --help for the full list of column-mapping flags and their defaults.
"""
import argparse
import csv
import json
import random


DEFAULT_FAIL_REASONS = [
    ('1.1', 'Face Identity Inconsistency（人脸一致性失败）'),
    ('1.2', 'Character Feature Changed（人物特征明显改变)'),
    ('2.1', 'Highly Unnatural Body Proportion（身材比例明显不合理/不美观）'),
    ('2.2', 'Highly Unnatural Head-Body Connection（头身衔接明显不自然）'),
    ('2.3', 'Highly Unnatural Pose / Action/Facial Expression（姿势动作表情明显不自然）'),
    ('2.4', 'CG-like Skin Texture（皮肤呈现明显 CG 感）'),
    ('2.5', 'Other Highly Unnatural Issues（其他人物不自然情况）'),
    ('3.1', 'Unrecognizable or Abnormal Objects（生成异物/物体生成异常）'),
    ('3.2', 'Human Generation Abnormality（人体生成异常）'),
    ('3.3', 'Physically Impossible Scene（违反物理现实）'),
    ('3.4', 'Common Sense Violation（违反生活常识）'),
    ('4.1', 'Over-smoothed / Plastic Texture（商品失去真实质感）'),
    ('5.1', 'Muslim Appearance Generated（生成穆斯林形象）'),
    ('5.2', 'Inappropriate Exposure（不当裸露）'),
    ('5.3', 'Other Unexpected Content（其他非预期内容）'),
    ('6.1', 'Main item Mismatch（主商品不一致）'),
    ('6.2', 'Attach item Mismatch（挂载品不相似）'),
]

DEFAULT_NOT_HQ_REASONS = [
    ('1.1', 'Cluttered Background / Poor Subject Separation（背景杂乱、主体不突出）'),
    ('1.2', 'Low-quality/Normal Background（背景普通或低端）'),
    ('1.3', 'Unappealing Color Tone（色调发黄、发灰、显脏、不通透）'),
    ('2.1', 'Human Occupancy < 50%（人物占比小于50%）'),
    ('2.2', 'Pose / Expression Unnatural（动作表情不自然）'),
    ('2.3', 'Head-Body Connection Slightly Unnatural（头身衔接轻微不自然）'),
    ('2.4', 'Body Proportion Slightly Unnatural（身材比例轻微不自然）'),
    ('2.5', 'Blurred / Low-detail Face（脸部模糊 / 缺少细节）'),
    ('3.1', 'Outfit Not Well Coordinated（穿搭搭配不够协调/和场景不搭配）'),
]


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--csv', required=True, help='Input CSV path')
    p.add_argument('--output', default='index.html', help='Output HTML path (default: index.html)')
    p.add_argument('--exec-url', required=True, help='Deployed Google Apps Script web app /exec URL')
    p.add_argument('--title', default='盲测评分', help='Page <h1> title')
    p.add_argument('--seed', type=int, default=7, help='Random seed for the A/B shuffle (default: 7)')
    p.add_argument('--require-all-rows', action='store_true',
                    help='Force evaluators to finish every row before the submit button unlocks. '
                         'Omit this flag while testing so you can submit early.')

    # Column mapping
    p.add_argument('--user-col', default='user_image_url', help='Column with the user/portrait photo URL')
    p.add_argument('--product-col', default='images', help='Column with the main product photo URL')
    p.add_argument('--category-col', default='global_be_category', help='Column used for the row header label')
    p.add_argument('--item-id-col', default='item_id', help='Column with a unique row/item id')

    p.add_argument('--template-col', default=None,
                    help='Column that already contains the full template image URL. '
                         'Use this OR --template-id-col + --template-base-url, not both.')
    p.add_argument('--template-id-col', default='aigc_generated_image_id',
                    help='Column with a template image ID that needs a base URL prefix')
    p.add_argument('--template-base-url', default='https://mms.img.susercontent.com/',
                    help='Prefix prepended to --template-id-col to build the template image URL')

    p.add_argument('--option1-col', required=True, help='Column with the first comparison image URL')
    p.add_argument('--option1-label', required=True, help='Internal label for option 1 (stored in the Sheet, never shown to evaluators)')
    p.add_argument('--option2-col', required=True, help='Column with the second comparison image URL')
    p.add_argument('--option2-label', required=True, help='Internal label for option 2 (stored in the Sheet, never shown to evaluators)')

    return p.parse_args()


def build_data(args):
    with open(args.csv, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    rnd = random.Random(args.seed)
    data = []
    for i, r in enumerate(rows):
        if args.template_col:
            template_img = r.get(args.template_col, '').strip()
        else:
            tpl_id = r.get(args.template_id_col, '').strip()
            template_img = f'{args.template_base_url}{tpl_id}' if tpl_id else ''

        opts = [
            {'key': args.option1_label, 'url': r.get(args.option1_col, '').strip()},
            {'key': args.option2_label, 'url': r.get(args.option2_col, '').strip()},
        ]
        rnd.shuffle(opts)

        data.append({
            'index': i,
            'item_id': r.get(args.item_id_col, ''),
            'category': r.get(args.category_col, ''),
            'user_img': r.get(args.user_col, '').strip(),
            'template_img': template_img,
            'product_img': r.get(args.product_col, '').strip(),
            'options': opts,
        })
    return data


HTML_TEMPLATE = r'''<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  * { box-sizing: border-box; }
  body {
    background: #000;
    color: #eee;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    margin: 0;
    padding: 24px;
  }
  h1 { font-size: 20px; font-weight: 600; margin: 0 0 8px 0; color: #fff; }
  .subtitle { color: #888; font-size: 13px; margin-bottom: 20px; }

  #name-gate {
    position: fixed; inset: 0; background: rgba(0,0,0,0.95); z-index: 2000;
    display: flex; align-items: center; justify-content: center;
  }
  #name-gate .box {
    background: #111; border: 1px solid #333; border-radius: 12px; padding: 28px;
    width: min(360px, 90vw); text-align: center;
  }
  #name-gate h2 { margin: 0 0 6px 0; font-size: 17px; color: #fff; }
  #name-gate p { color: #999; font-size: 13px; margin: 0 0 16px 0; }
  #name-gate input {
    width: 100%; padding: 10px 12px; border-radius: 8px; border: 1px solid #333;
    background: #0a0a0a; color: #eee; font-size: 14px; margin-bottom: 12px;
  }
  #name-gate button {
    width: 100%; padding: 10px; border-radius: 8px; border: none;
    background: #4a9eff; color: #fff; font-size: 14px; cursor: pointer; font-weight: 600;
  }
  #name-gate button:disabled { background: #333; cursor: not-allowed; }

  #summary {
    position: sticky; top: 0; z-index: 50; background: #111; border: 1px solid #262626;
    border-radius: 10px; padding: 14px 18px; margin-bottom: 20px;
    display: flex; flex-wrap: wrap; gap: 20px; align-items: center;
  }
  .stat { display: flex; flex-direction: column; align-items: center; min-width: 60px; }
  .stat .v { font-size: 20px; font-weight: 700; color: #fff; }
  .stat .l { font-size: 11px; color: #999; margin-top: 2px; }
  .progress-bar { flex: 1; min-width: 140px; height: 8px; background: #262626; border-radius: 4px; overflow: hidden; }
  .progress-fill { height: 100%; background: #4a9eff; transition: width .2s; }
  #evaluator-badge { font-size: 12px; color: #9ecbff; }
  #save-status { font-size: 11px; color: #666; min-width: 70px; }

  .row {
    background: #111; border: 1px solid #262626; border-radius: 10px;
    padding: 16px; margin-bottom: 20px;
  }
  .row.voted { border-color: #2a5a2a; }

  .row-header { display: flex; align-items: center; gap: 14px; margin-bottom: 14px; flex-wrap: wrap; }
  .header-title { font-size: 13px; color: #999; word-break: break-all; }
  .header-thumbs { display: flex; gap: 10px; }
  .header-thumb { display: flex; flex-direction: column; align-items: center; gap: 3px; }
  .header-thumb img {
    width: 52px; height: 52px; object-fit: cover; border-radius: 6px;
    border: 1px solid #2a2a2a; background: #0a0a0a; cursor: zoom-in; display: block;
  }
  .header-thumb .thumb-label { font-size: 9px; color: #777; }

  .row-body { display: flex; gap: 16px; align-items: flex-start; }
  .main-cells { flex: 1; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; min-width: 0; }
  .cell { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .label { font-size: 12px; color: #bbb; text-align: center; min-height: 16px; }
  .img-wrap {
    background: #0a0a0a; border: 1px solid #2a2a2a; border-radius: 8px; overflow: hidden;
    min-height: 100px; display: flex; align-items: center; justify-content: center;
  }
  .img-wrap img { width: 100%; height: auto; max-height: 380px; object-fit: contain; display: block; cursor: zoom-in; }
  .img-link {
    font-size: 10px; color: #6a9edb; text-align: center; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap; display: block; text-decoration: none;
  }
  .img-link:hover { text-decoration: underline; }

  .quality-review { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
  .quality-buttons { display: flex; gap: 6px; }
  .quality-buttons button {
    flex: 1; background: #1c1c1c; border: 1px solid #333; color: #ccc;
    padding: 6px 4px; border-radius: 5px; font-size: 11px; cursor: pointer;
    transition: background .15s, border-color .15s;
  }
  .quality-buttons button:hover { background: #2a2a2a; }
  .quality-buttons button.q-chosen.q-fail { background: #331414; border-color: #d95c5c; color: #ffb0b0; }
  .quality-buttons button.q-chosen.q-pass { background: #33290f; border-color: #d9a441; color: #ffd98a; }
  .quality-buttons button.q-chosen.q-high { background: #123a12; border-color: #6ad16a; color: #b6ffb6; }
  .quality-reasons {
    display: flex; flex-direction: column; gap: 4px; max-height: 170px; overflow-y: auto;
    background: #0a0a0a; border: 1px solid #333; border-radius: 5px; padding: 6px 8px;
  }
  .quality-reasons label {
    display: flex; align-items: flex-start; gap: 6px; font-size: 11px; color: #ccc;
    cursor: pointer; line-height: 1.3;
  }
  .quality-reasons input[type="checkbox"] { margin-top: 2px; flex-shrink: 0; }
  .quality-count { font-size: 10px; color: #666; }

  .vote-sidebar { display: flex; flex-direction: column; gap: 8px; width: 170px; flex-shrink: 0; }
  .vote-sidebar .remark-input { flex-basis: 100%; }

  @media (max-width: 900px) {
    .row-body { flex-direction: column; }
    .vote-sidebar { flex-direction: row; flex-wrap: wrap; width: 100%; }
    .vote-sidebar button { flex: 1 1 100px; }
    .main-cells { grid-template-columns: repeat(3, 1fr); width: 100%; }
  }
  @media (max-width: 640px) {
    .main-cells { grid-template-columns: repeat(2, 1fr); }
  }

  #finish-bar {
    position: sticky; bottom: 0; background: #111; border: 1px solid #262626;
    border-radius: 10px; padding: 16px; margin-top: 8px; text-align: center;
  }
  #finish-bar button {
    padding: 12px 32px; border-radius: 8px; border: none; font-size: 14px; font-weight: 600;
    background: #4a9eff; color: #fff; cursor: pointer;
  }
  #finish-bar button:disabled { background: #333; color: #777; cursor: not-allowed; }
  #finish-bar .hint { font-size: 12px; color: #888; margin-top: 8px; }
  #finish-screen {
    display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.95); z-index: 2000;
    align-items: center; justify-content: center; text-align: center;
  }
  #finish-screen.open { display: flex; }
  #finish-screen .box { background: #111; border: 1px solid #333; border-radius: 12px; padding: 36px; }
  #finish-screen h2 { color: #8fd18f; margin: 0 0 10px 0; }
  #finish-screen p { color: #aaa; font-size: 13px; }

  .vote-sidebar button {
    flex: 1; background: #1c1c1c; border: 1px solid #333; color: #ddd;
    padding: 14px 10px; border-radius: 6px; font-size: 13px; cursor: pointer;
    transition: background .15s, border-color .15s;
  }
  .vote-sidebar button:hover { background: #2a2a2a; }
  .vote-sidebar button.chosen { background: #234; border-color: #4a9eff; color: #9ecbff; }
  .vote-sidebar button.chosen.both-good { border-color: #6ad16a; color: #b6ffb6; background: #123a12; }
  .vote-sidebar button.chosen.both-bad { border-color: #d95c5c; color: #ffb0b0; background: #331414; }
  .remark-input {
    flex: 1; min-height: 80px; resize: vertical; background: #0a0a0a; color: #ddd;
    border: 1px solid #333; border-radius: 6px; padding: 8px 10px; font-size: 12px;
    font-family: inherit; line-height: 1.4;
  }
  .remark-input::placeholder { color: #555; }
  .remark-input:focus { outline: none; border-color: #4a9eff; }
  .remark-status { font-size: 10px; color: #666; text-align: right; min-height: 12px; }

  #lightbox {
    display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.92);
    z-index: 1000; align-items: center; justify-content: center; cursor: zoom-out;
  }
  #lightbox.open { display: flex; }
  #lightbox img { max-width: 92vw; max-height: 92vh; object-fit: contain; box-shadow: 0 0 40px rgba(0,0,0,0.6); }
  #lightbox .close-hint { position: fixed; top: 16px; right: 24px; color: #ccc; font-size: 14px; }
</style>
</head>
<body>

<div id="name-gate">
  <div class="box">
    <h2>开始评分前</h2>
    <p>请输入你的姓名/花名，用于区分每个人提交的打分结果</p>
    <input id="name-input" type="text" placeholder="例如：olivia">
    <button id="name-submit" onclick="submitName()">开始评分</button>
  </div>
</div>

<h1>__TITLE__</h1>
<div class="subtitle">共 __TOTAL__ 条 · 盲测对比（左右顺序随机打乱）· 点击图片可放大 · 打分实时写入 Google Sheet</div>

<div id="summary"></div>
<div id="rows"></div>

<div id="finish-bar">
  <button id="finish-btn" onclick="finishEvaluation()" disabled>提交本次评测（__TOTAL__ 行全部打完后可用）</button>
  <div class="hint" id="finish-hint"></div>
</div>

<div id="lightbox">
  <span class="close-hint">点击任意处关闭 ✕</span>
  <img id="lightbox-img" src="" alt="">
</div>

<div id="finish-screen">
  <div class="box">
    <h2>✓ 已提交，谢谢你的评测！</h2>
    <p id="finish-screen-text"></p>
  </div>
</div>

<script>
const DATA = __DATA_JSON__;
const EXEC_URL = '__EXEC_URL__';
// Flip to true once you've tested the flow — it then forces evaluators to
// finish every row before the submit button unlocks.
const REQUIRE_ALL_ROWS = __REQUIRE_ALL_ROWS__;
const NAME_KEY = 'blind-eval-name';
const VOTES_KEY_PREFIX = 'blind-eval-votes-';
const REMARKS_KEY_PREFIX = 'blind-eval-remarks-';
const QUALITY_KEY_PREFIX = 'blind-eval-quality-';
let evaluator = localStorage.getItem(NAME_KEY) || '';
let votes = {};
let remarks = {};
let quality = {}; // quality[rowIndex] = { A: {status, reasons}, B: {status, reasons} }
let saving = {};

const FAIL_REASONS = __FAIL_REASONS_JSON__;
const NOT_HQ_REASONS = __NOT_HQ_REASONS_JSON__;

function localVotesKey() { return VOTES_KEY_PREFIX + evaluator; }
function loadLocalVotes() {
  try { return JSON.parse(localStorage.getItem(localVotesKey()) || '{}'); } catch (e) { return {}; }
}
function saveLocalVotes() {
  localStorage.setItem(localVotesKey(), JSON.stringify(votes));
}

function localRemarksKey() { return REMARKS_KEY_PREFIX + evaluator; }
function loadLocalRemarks() {
  try { return JSON.parse(localStorage.getItem(localRemarksKey()) || '{}'); } catch (e) { return {}; }
}
function saveLocalRemarks() {
  localStorage.setItem(localRemarksKey(), JSON.stringify(remarks));
}

function localQualityKey() { return QUALITY_KEY_PREFIX + evaluator; }
function loadLocalQuality() {
  try { return JSON.parse(localStorage.getItem(localQualityKey()) || '{}'); } catch (e) { return {}; }
}
function saveLocalQuality() {
  localStorage.setItem(localQualityKey(), JSON.stringify(quality));
}
function getQuality(rowIndex, side) {
  const q = (quality[rowIndex] && quality[rowIndex][side]) || {};
  return { status: q.status || '', reasons: q.reasons || [] };
}

// Turns stored reason codes (e.g. "2.2") back into their full label text for
// the Sheet, so the export is self-explanatory without cross-referencing codes.
function reasonCodesToLabels(status, codes) {
  const list = status === 'fail' ? FAIL_REASONS : status === 'pass' ? NOT_HQ_REASONS : [];
  return codes.map(function(code) {
    const found = list.find(function(pair) { return pair[0] === code; });
    return found ? (found[0] + ' ' + found[1]) : code;
  }).join('; ');
}
function setQuality(rowIndex, side, patch) {
  if (!quality[rowIndex]) quality[rowIndex] = {
    A: { status: '', reasons: [] }, B: { status: '', reasons: [] }
  };
  quality[rowIndex][side] = Object.assign({}, getQuality(rowIndex, side), patch);
}

function esc(s) {
  return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function submitName() {
  const v = document.getElementById('name-input').value.trim();
  if (!v) { alert('请输入姓名'); return; }
  evaluator = v;
  localStorage.setItem(NAME_KEY, v);
  document.getElementById('name-gate').style.display = 'none';
  loadMyVotes();
}

function loadMyVotes() {
  votes = loadLocalVotes();
  remarks = loadLocalRemarks();
  quality = loadLocalQuality();
  renderSummary();
  buildRows();

  // Best-effort: try to also pull remote votes (e.g. opened on a new device).
  // If this is blocked by CORS/network, local votes already rendered above.
  fetch(EXEC_URL + '?action=getMyVotes&evaluator=' + encodeURIComponent(evaluator))
    .then(function(r) { return r.json(); })
    .then(function(remote) {
      if (remote && remote.ok && remote.votes) {
        votes = Object.assign({}, remote.votes, votes);
        saveLocalVotes();
        renderSummary();
        buildRows();
      }
    })
    .catch(function() { /* ignore, local votes already shown */ });
}

function renderSummary() {
  const total = DATA.length;
  const votedCount = Object.keys(votes).length;
  const pct = total ? Math.round(votedCount / total * 100) : 0;
  const el = document.getElementById('summary');
  el.innerHTML =
    '<span id="evaluator-badge">评测人：' + esc(evaluator) + '</span>' +
    '<div class="stat"><span class="v">' + votedCount + '/' + total + '</span><span class="l">已评分</span></div>' +
    '<div class="progress-bar"><div class="progress-fill" style="width:' + pct + '%"></div></div>' +
    '<span id="save-status"></span>';

  const finishBtn = document.getElementById('finish-btn');
  const finishHint = document.getElementById('finish-hint');
  if (votedCount >= total || !REQUIRE_ALL_ROWS) {
    finishBtn.disabled = false;
    finishBtn.textContent = '提交本次评测' + (!REQUIRE_ALL_ROWS && votedCount < total ? '（测试模式，未打满也可点）' : '');
    finishHint.textContent = !REQUIRE_ALL_ROWS ? '⚠️ 测试模式：未强制要求打满全部行数' : '';
  } else {
    finishBtn.disabled = true;
    finishBtn.textContent = '提交本次评测（还差 ' + (total - votedCount) + ' 行）';
    finishHint.textContent = '每行打分会立即保存，这个按钮只是全部完成后的最终确认';
  }
}

function finishEvaluation() {
  const votedCount = Object.keys(votes).length;
  fetch(EXEC_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain;charset=utf-8' },
    body: JSON.stringify({ action: 'complete', evaluator: evaluator }),
  })
    .catch(function() { /* local votes are already saved regardless */ })
    .finally(function() {
      document.getElementById('finish-screen-text').textContent =
        '你一共完成了 ' + votedCount + ' / ' + DATA.length + ' 行打分，结果已经写入统计表格。';
      document.getElementById('finish-screen').classList.add('open');
    });
}

function optionButtonsHtml(row) {
  const v = votes[row.index];
  const items = [
    { key: row.options[0].key, label: 'A 好' },
    { key: row.options[1].key, label: 'B 好' },
    { key: 'both_good', label: '都好' },
    { key: 'both_bad', label: '都不好' },
  ];
  return items.map(it => {
    const chosen = v === it.key;
    let cls = '';
    if (chosen && it.key === 'both_good') cls = 'chosen both-good';
    else if (chosen && it.key === 'both_bad') cls = 'chosen both-bad';
    else if (chosen) cls = 'chosen';
    return '<button class="' + cls + '" onclick="cast(' + row.index + ', \'' + it.key + '\')">' + it.label + '</button>';
  }).join('');
}

function headerThumb(label, url) {
  return '<div class="header-thumb">' +
    '<img src="' + esc(url) + '" loading="lazy" alt="' + esc(label) + '" title="' + esc(url) + '">' +
    '<span class="thumb-label">' + label + '</span>' +
    '</div>';
}

function cast(rowIndex, choice) {
  votes[rowIndex] = choice;
  saveLocalVotes();
  renderRow(rowIndex);
  submitRow(rowIndex);
}

function onRemarkChange(rowIndex, text) {
  remarks[rowIndex] = text;
  saveLocalRemarks();
  submitRow(rowIndex);
}

function setQualityStatus(rowIndex, side, status) {
  const cur = getQuality(rowIndex, side);
  const keepReasons = status === cur.status ? cur.reasons : [];
  setQuality(rowIndex, side, { status: status, reasons: status === 'high_quality' ? [] : keepReasons });
  saveLocalQuality();
  renderRow(rowIndex);
  submitRow(rowIndex);
}

function toggleQualityReason(rowIndex, side, code, checked) {
  const cur = getQuality(rowIndex, side);
  let reasons = cur.reasons.slice();
  if (checked) {
    if (reasons.indexOf(code) === -1) reasons.push(code);
  } else {
    reasons = reasons.filter(function(c) { return c !== code; });
  }
  setQuality(rowIndex, side, { reasons: reasons });
  saveLocalQuality();
  renderQualityCount(rowIndex, side);
  submitRow(rowIndex);
}

function renderQualityCount(rowIndex, side) {
  const el = document.getElementById('qcount-' + rowIndex + '-' + side);
  if (!el) return;
  const n = getQuality(rowIndex, side).reasons.length;
  el.textContent = n > 0 ? '已选 ' + n + ' 项' : '';
}

function submitRow(rowIndex) {
  renderSummary();

  const row = DATA[rowIndex];
  const statusEl = document.getElementById('save-status');
  statusEl.textContent = '保存中…';

  const qA = getQuality(rowIndex, 'A');
  const qB = getQuality(rowIndex, 'B');

  const payload = {
    evaluator: evaluator,
    rowIndex: rowIndex,
    itemId: row.item_id,
    choice: votes[rowIndex] || '',
    remark: remarks[rowIndex] || '',
    aModel: row.options[0].key,
    bModel: row.options[1].key,
    aUrl: row.options[0].url,
    bUrl: row.options[1].url,
    userImg: row.user_img,
    aQualityStatus: qA.status || '',
    aQualityReason: reasonCodesToLabels(qA.status, qA.reasons),
    bQualityStatus: qB.status || '',
    bQualityReason: reasonCodesToLabels(qB.status, qB.reasons),
  };

  fetch(EXEC_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain;charset=utf-8' },
    body: JSON.stringify(payload),
  })
    .then(function(r) { return r.json(); })
    .then(function(res) {
      if (res && res.ok) {
        statusEl.textContent = '已保存 ✓';
      } else {
        statusEl.textContent = '保存失败，请重试';
      }
      setTimeout(function() { if (statusEl.textContent === '已保存 ✓') statusEl.textContent = ''; }, 1500);
    })
    .catch(function() {
      statusEl.textContent = '保存失败，请检查网络后重试';
    });
}

function cell(label, url) {
  return '<div class="cell">' +
    '<div class="label">' + label + '</div>' +
    '<div class="img-wrap"><img src="' + esc(url) + '" loading="lazy" alt="' + esc(label) + '"></div>' +
    '<a class="img-link" href="' + esc(url) + '" target="_blank" rel="noopener" title="' + esc(url) + '">' + esc(url) + '</a>' +
    '</div>';
}

function reasonChecklistHtml(list, rowIndex, side, selected) {
  return list.map(function(pair) {
    const checked = selected.indexOf(pair[0]) !== -1 ? ' checked' : '';
    const id = 'qr-' + rowIndex + '-' + side + '-' + pair[0];
    return '<label for="' + id + '">' +
      '<input type="checkbox" id="' + id + '"' + checked +
        ' onchange="toggleQualityReason(' + rowIndex + ', \'' + side + '\', \'' + pair[0] + '\', this.checked)">' +
      '<span>' + pair[0] + ' ' + esc(pair[1]) + '</span>' +
      '</label>';
  }).join('');
}

function optionCell(label, url, rowIndex, side) {
  return '<div class="cell">' +
    '<div class="label">' + label + '</div>' +
    '<div class="img-wrap"><img src="' + esc(url) + '" loading="lazy" alt="' + esc(label) + '"></div>' +
    '<a class="img-link" href="' + esc(url) + '" target="_blank" rel="noopener" title="' + esc(url) + '">' + esc(url) + '</a>' +
    qualityReviewHtml(rowIndex, side) +
    '</div>';
}

function qualityReviewHtml(rowIndex, side) {
  const q = getQuality(rowIndex, side);
  const buttons = [
    { key: 'fail', label: 'Fail', cls: 'q-fail' },
    { key: 'pass', label: 'Pass', cls: 'q-pass' },
    { key: 'high_quality', label: 'High Quality', cls: 'q-high' },
  ].map(function(b) {
    const chosen = q.status === b.key ? ' q-chosen ' + b.cls : '';
    return '<button class="' + chosen + '" onclick="setQualityStatus(' + rowIndex + ', \'' + side + '\', \'' + b.key + '\')">' + b.label + '</button>';
  }).join('');

  let reasonBlock = '';
  if (q.status === 'fail') {
    reasonBlock =
      '<div class="quality-reasons">' + reasonChecklistHtml(FAIL_REASONS, rowIndex, side, q.reasons) + '</div>' +
      '<div class="quality-count" id="qcount-' + rowIndex + '-' + side + '">' +
        (q.reasons.length > 0 ? '已选 ' + q.reasons.length + ' 项' : '') + '</div>';
  } else if (q.status === 'pass') {
    reasonBlock =
      '<div class="quality-reasons">' + reasonChecklistHtml(NOT_HQ_REASONS, rowIndex, side, q.reasons) + '</div>' +
      '<div class="quality-count" id="qcount-' + rowIndex + '-' + side + '">' +
        (q.reasons.length > 0 ? '已选 ' + q.reasons.length + ' 项' : '') + '</div>';
  }

  return '<div class="quality-review">' +
    '<div class="quality-buttons">' + buttons + '</div>' +
    reasonBlock +
    '</div>';
}

function renderRow(index) {
  const row = DATA[index];
  const v = votes[row.index];
  const el = document.getElementById('row-' + row.index);
  const voted = !!v;
  const optA = row.options[0], optB = row.options[1];

  // Never reveal which model A/B actually are — the mapping only lives in
  // the backend Sheet (A_model/B_model columns) for later analysis, so the
  // evaluator can't build up positional bias across rows.
  el.className = 'row' + (voted ? ' voted' : '');
  el.innerHTML =
    '<div class="row-header">' +
      '<div class="header-thumbs">' +
        headerThumb('用户图', row.user_img) +
        headerThumb('商品图', row.product_img) +
      '</div>' +
      '<div class="header-title">#' + (row.index + 1) + ' · ' + esc(row.category) + '</div>' +
    '</div>' +
    '<div class="row-body">' +
      '<div class="main-cells">' +
        cell('模版图', row.template_img) +
        optionCell('选项 A', optA.url, row.index, 'A') +
        optionCell('选项 B', optB.url, row.index, 'B') +
      '</div>' +
      '<div class="vote-sidebar">' +
        optionButtonsHtml(row) +
        '<textarea class="remark-input" placeholder="备注（可选）" ' +
          'oninput="remarks[' + row.index + ']=this.value" ' +
          'onblur="onRemarkChange(' + row.index + ', this.value)">' + esc(remarks[row.index] || '') + '</textarea>' +
      '</div>' +
    '</div>';
}

function buildRows() {
  const container = document.getElementById('rows');
  container.innerHTML = DATA.map(row => '<div class="row" id="row-' + row.index + '"></div>').join('');
  DATA.forEach(row => renderRow(row.index));
}

document.addEventListener('click', function(e) {
  if (e.target.tagName === 'IMG' && e.target.closest('.img-wrap, .header-thumb')) {
    document.getElementById('lightbox-img').src = e.target.src;
    document.getElementById('lightbox').classList.add('open');
  }
});
document.getElementById('lightbox').addEventListener('click', function() {
  document.getElementById('lightbox').classList.remove('open');
  document.getElementById('lightbox-img').src = '';
});
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    document.getElementById('lightbox').classList.remove('open');
    document.getElementById('lightbox-img').src = '';
  }
});

if (evaluator) {
  document.getElementById('name-gate').style.display = 'none';
  loadMyVotes();
} else {
  renderSummary();
  buildRows();
}
</script>
</body>
</html>
'''


def main():
    args = parse_args()
    data = build_data(args)

    html_doc = (HTML_TEMPLATE
        .replace('__TITLE__', args.title)
        .replace('__TOTAL__', str(len(data)))
        .replace('__DATA_JSON__', json.dumps(data, ensure_ascii=False))
        .replace('__EXEC_URL__', args.exec_url)
        .replace('__REQUIRE_ALL_ROWS__', 'true' if args.require_all_rows else 'false')
        .replace('__FAIL_REASONS_JSON__', json.dumps(DEFAULT_FAIL_REASONS, ensure_ascii=False))
        .replace('__NOT_HQ_REASONS_JSON__', json.dumps(DEFAULT_NOT_HQ_REASONS, ensure_ascii=False))
    )

    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(html_doc)

    print(f'Wrote {args.output} ({len(html_doc)} bytes, {len(data)} rows)')


if __name__ == '__main__':
    main()
