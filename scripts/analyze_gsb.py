#!/usr/bin/env python3
"""
Analysis framework for blind-ab-eval "votes" CSV exports.

Resolves the randomized A/B position back to the actual version identity
(A_model / B_model tell you which physical side each row's "A" and "B" were),
then reports two things from the version1/version2 perspective:

  1. Choice — how often each version was picked as the better one in the
     A好/B好/都好/都不好 vote (this field already stores the resolved version
     name directly, e.g. "version1", not "A"/"B" — no remapping needed here).
  2. Pass rate — Fail/Pass/High Quality breakdown per version, remapped from
     the A_quality_status/B_quality_status columns using A_model/B_model.

Usage:
    python3 analyze_gsb.py "AI Try on GSB - votes.csv"
    python3 analyze_gsb.py votes.csv --exclude-evaluators test toggle_test
    python3 analyze_gsb.py votes.csv --per-evaluator
"""
import argparse
import csv
from collections import Counter, defaultdict


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('csv_path', help='Path to the exported votes CSV')
    p.add_argument('--exclude-evaluators', nargs='*', default=[],
                    help='Evaluator names to drop before analyzing (e.g. test accounts)')
    p.add_argument('--per-evaluator', action='store_true',
                    help='Also print a per-evaluator breakdown of choice and pass rate')
    return p.parse_args()


def load_rows(path, exclude_evaluators):
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    excluded = set(exclude_evaluators)
    return [r for r in rows if r['evaluator'] not in excluded]


def resolve_version_quality(row):
    """Returns {'version1': (status, reason), 'version2': (status, reason)}
    for one row, remapping the A/B-position columns to actual version identity."""
    a_model, b_model = row['A_model'], row['B_model']
    a_pair = (row['A_quality_status'], row['A_quality_reason'])
    b_pair = (row['B_quality_status'], row['B_quality_reason'])
    return {a_model: a_pair, b_model: b_pair}


def analyze_choice(rows):
    """`choice` already stores the resolved version name (or both_good/both_bad),
    since the vote buttons submit row.options[i].key directly — not a generic
    'A'/'B' — so no A/B remapping is needed for this metric."""
    counts = Counter(r['choice'] for r in rows if r['choice'])
    total_voted = sum(counts.values())
    versions = sorted({r['A_model'] for r in rows} | {r['B_model'] for r in rows})

    result = {'total_voted': total_voted, 'total_rows': len(rows), 'by_choice': dict(counts)}
    for v in versions:
        win = counts.get(v, 0)
        result[f'{v}_win_count'] = win
        result[f'{v}_win_rate'] = round(win / total_voted, 4) if total_voted else None
    result['both_good_count'] = counts.get('both_good', 0)
    result['both_bad_count'] = counts.get('both_bad', 0)
    result['both_good_rate'] = round(counts.get('both_good', 0) / total_voted, 4) if total_voted else None
    result['both_bad_rate'] = round(counts.get('both_bad', 0) / total_voted, 4) if total_voted else None
    return result


def analyze_quality(rows):
    status_counts = defaultdict(Counter)          # version -> Counter(status)
    fail_reason_counts = defaultdict(Counter)     # version -> Counter(fail reason), status=='fail' only
    not_hq_reason_counts = defaultdict(Counter)   # version -> Counter(not-high-quality reason), status=='pass' only

    for row in rows:
        resolved = resolve_version_quality(row)
        for version, (status, reason) in resolved.items():
            if status:
                status_counts[version][status] += 1
            if reason and status == 'fail':
                for single in reason.split('; '):
                    fail_reason_counts[version][single.strip()] += 1
            elif reason and status == 'pass':
                for single in reason.split('; '):
                    not_hq_reason_counts[version][single.strip()] += 1

    result = {}
    for version, counts in status_counts.items():
        fail = counts.get('fail', 0)
        passed = counts.get('pass', 0)
        high = counts.get('high_quality', 0)
        rated = fail + passed + high
        result[version] = {
            'rated_count': rated,
            'fail_count': fail,
            'pass_count': passed,
            'high_quality_count': high,
            'fail_rate': round(fail / rated, 4) if rated else None,
            'pass_rate_strict': round(passed / rated, 4) if rated else None,  # exactly "pass", excludes high_quality
            'high_quality_rate': round(high / rated, 4) if rated else None,
            'pass_rate_overall': round((passed + high) / rated, 4) if rated else None,  # non-fail rate
            'top_fail_reasons': fail_reason_counts[version].most_common(5),
            'top_not_high_quality_reasons': not_hq_reason_counts[version].most_common(5),
        }
    return result


def print_report(title, rows):
    print(f'\n{"=" * 60}\n{title}  (n={len(rows)} rows)\n{"=" * 60}')

    choice = analyze_choice(rows)
    print(f"\n--- Choice (A好/B好/都好/都不好) ---")
    print(f"已投票行数: {choice['total_voted']} / {choice['total_rows']}")
    for k, v in sorted(choice.items()):
        if k.endswith('_win_count'):
            version = k[: -len('_win_count')]
            rate = choice.get(f'{version}_win_rate')
            print(f"  {version}: 被选为更好 {v} 次  ({rate:.1%})" if rate is not None else f"  {version}: {v} 次")
    print(f"  都好: {choice['both_good_count']} 次 ({choice['both_good_rate']:.1%})" if choice['both_good_rate'] is not None else "")
    print(f"  都不好: {choice['both_bad_count']} 次 ({choice['both_bad_rate']:.1%})" if choice['both_bad_rate'] is not None else "")

    quality = analyze_quality(rows)
    print(f"\n--- Pass rate (Fail / Pass / High Quality, 已做 A/B 位置还原) ---")
    for version in sorted(quality):
        q = quality[version]
        print(f"  {version}  (已评分 {q['rated_count']} 张图):")
        print(f"    Fail: {q['fail_count']} ({q['fail_rate']:.1%})" if q['fail_rate'] is not None else "    Fail: 0")
        print(f"    Pass: {q['pass_count']} ({q['pass_rate_strict']:.1%})" if q['pass_rate_strict'] is not None else "    Pass: 0")
        print(f"    High Quality: {q['high_quality_count']} ({q['high_quality_rate']:.1%})" if q['high_quality_rate'] is not None else "    High Quality: 0")
        print(f"    >> Pass rate (Pass+High Quality / 已评分): {q['pass_rate_overall']:.1%}" if q['pass_rate_overall'] is not None else "    >> Pass rate: N/A")
        if q['top_fail_reasons']:
            print(f"    Top fail reasons:")
            for reason, cnt in q['top_fail_reasons']:
                print(f"      - {reason}  x{cnt}")
        if q['top_not_high_quality_reasons']:
            print(f"    Top not-high-quality reasons (status=pass):")
            for reason, cnt in q['top_not_high_quality_reasons']:
                print(f"      - {reason}  x{cnt}")


def main():
    args = parse_args()
    rows = load_rows(args.csv_path, args.exclude_evaluators)

    print_report('OVERALL', rows)

    if args.per_evaluator:
        by_evaluator = defaultdict(list)
        for r in rows:
            by_evaluator[r['evaluator']].append(r)
        for evaluator in sorted(by_evaluator):
            print_report(f'EVALUATOR: {evaluator}', by_evaluator[evaluator])


if __name__ == '__main__':
    main()
