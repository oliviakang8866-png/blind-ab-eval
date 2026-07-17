#!/usr/bin/env python3
"""
Translates a blind-ab-eval "votes" CSV export from version1/version2 labels
to the real per-row model codes, then re-runs the choice/pass-rate analysis
grouped by real model code.

The blind report always sets:
    version1 = generated_image_url1  ->  model_type1 (this row's real code)
    version2 = generated_image_url2  ->  model_type2 (this row's real code)
joined by item_id. This mapping is per-row (not a fixed global version1->code
mapping) because model_type1/model_type2 vary row to row in the source data.

Two-hop resolution per row, kept as separate explicit steps so each hop can
be checked independently:
    hop 1 (already in votes.csv): A_quality_status belongs to whichever of
        {version1, version2} is named in A_model for that row.
    hop 2 (this script):          version1/version2 -> real model code, via
        this row's item_id in the mapping CSV.

Usage:
    python3 translate_to_model_codes.py \\
        --votes "AI Try on GSB - votes.csv" \\
        --mapping "Copy of ailook模型版本对比 - 100sample_shuffle.csv" \\
        --output votes_with_model_codes.csv \\
        --exclude-evaluators test toggle_test
"""
import argparse
import csv

from analyze_gsb import analyze_choice, analyze_quality, print_report  # reuse as-is


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--votes', required=True, help='votes.csv exported from the Google Sheet')
    p.add_argument('--mapping', required=True,
                    help='Source CSV containing item_id, model_type1, model_type2 (per-row real model codes)')
    p.add_argument('--output', default='votes_with_model_codes.csv', help='Translated per-row output CSV')
    p.add_argument('--exclude-evaluators', nargs='*', default=[])
    return p.parse_args()


def load_mapping(path):
    """item_id -> (model_type1, model_type2)"""
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    mapping = {}
    for r in rows:
        mapping[r['item_id']] = (r['model_type1'].strip(), r['model_type2'].strip())
    return mapping


def translate_rows(votes, mapping):
    translated = []
    unmatched = []
    for row in votes:
        item_id = row['item_id']
        if item_id not in mapping:
            unmatched.append(item_id)
            continue
        model_type1, model_type2 = mapping[item_id]

        # hop 2: version1/version2 -> real model code, done independently for
        # A_model, B_model, and choice so a bug in one can't silently affect
        # the others.
        def resolve(value):
            if value == 'version1':
                return model_type1
            if value == 'version2':
                return model_type2
            return value  # '', 'both_good', 'both_bad' pass through unchanged

        new_row = dict(row)
        new_row['A_model'] = resolve(row['A_model'])
        new_row['B_model'] = resolve(row['B_model'])
        new_row['choice'] = resolve(row['choice'])
        translated.append(new_row)
    return translated, unmatched


def main():
    args = parse_args()

    with open(args.votes, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        votes = list(reader)

    if args.exclude_evaluators:
        votes = [r for r in votes if r['evaluator'] not in set(args.exclude_evaluators)]

    mapping = load_mapping(args.mapping)
    translated, unmatched = translate_rows(votes, mapping)

    if unmatched:
        print(f'WARNING: {len(unmatched)} vote rows had an item_id not found in the mapping CSV, skipped: {unmatched[:10]}')

    with open(args.output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(translated)
    print(f'Wrote {args.output} ({len(translated)} rows, A_model/B_model/choice now show real model codes)')

    # Sanity spot-check: print first 5 rows' before/after for manual verification
    print('\n--- Spot check (first 5 translated rows) ---')
    for orig, new in zip(votes[:5], translated[:5]):
        print(f"  item_id={orig['item_id']}  choice: '{orig['choice']}' -> '{new['choice']}'   "
              f"A_model: '{orig['A_model']}' -> '{new['A_model']}'   B_model: '{orig['B_model']}' -> '{new['B_model']}'")

    print_report('BY REAL MODEL CODE (translated)', translated)


if __name__ == '__main__':
    main()
