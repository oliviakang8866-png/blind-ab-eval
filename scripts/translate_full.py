#!/usr/bin/env python3
"""
Full translation: votes CSV -> per-row output with real model codes, both
models' image links, and both models' autoqc results attached — plus a
summary (choice win rate + pass rate) grouped by real model code.

Two independent resolution paths, kept separate on purpose:
  - A_model/B_model/choice/quality: resolved via THIS ROW's A_model/B_model
    (version1/version2), which tells us which physical slot (A or B) each
    real model code was shown in for this row.
  - autoqc + links: resolved directly from the mapping CSV's model_type1/
    model_type2 (no A/B hop needed — qc/link columns for
    generated_image_url1 always belong to model_type1, and url2 to
    model_type2, regardless of how the blind test later shuffled them into
    A/B).

IMPORTANT — joined by row_index, not item_id: the same item_id can appear
more than once in the source dataset (the same product sampled against
different users), each time with a completely different template/generated
image and possibly a different model_type1/model_type2. Joining by item_id
alone silently collapses those into one (whichever row happens to be read
last wins), corrupting every vote tied to the shadowed row. row_index is
guaranteed unique (0..N-1, one CSV row each) and is already present on every
vote row, so it's the only safe join key here.

Usage:
    python3 translate_full.py \\
        --votes "AI Try on GSB - 工作表2.csv" \\
        --mapping "Copy of ailook模型版本对比 - 100sample_shuffle.csv" \\
        --output votes_full_with_qc.csv \\
        --exclude-evaluators test toggle_test
"""
import argparse
import csv

from analyze_gsb import analyze_choice, analyze_quality, print_report


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--votes', required=True)
    p.add_argument('--mapping', required=True)
    p.add_argument('--output', default='votes_full_with_qc.csv')
    p.add_argument('--exclude-evaluators', nargs='*', default=[])
    return p.parse_args()


def load_mapping(path):
    """row_index (as string, matching the votes CSV's row_index column) ->
    dict with model codes, links, and qc fields for both models.

    Keyed by row_index, NOT item_id — the same item_id can legitimately
    appear on more than one row (same product, different user photo), so
    item_id alone is not a safe join key. See module docstring."""
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    mapping = {}
    for i, r in enumerate(rows):
        mapping[str(i)] = {
            'item_id': r['item_id'],
            'model_type1': r['model_type1'].strip(),
            'model_type2': r['model_type2'].strip(),
            'url1': r['generated_image_url1'].strip(),
            'url2': r['generated_image_url2'].strip(),
            'qc_label1': r.get('generated_image_url1_qc_label', '').strip(),
            'qc_dino1': r.get('generated_image_url1_qc_dino_score', '').strip(),
            'qc_face1': r.get('generated_image_url1_qc_face_similarity', '').strip(),
            'qc_label2': r.get('generated_image_url2_qc_label', '').strip(),
            'qc_dino2': r.get('generated_image_url2_qc_dino_score', '').strip(),
            'qc_face2': r.get('generated_image_url2_qc_face_similarity', '').strip(),
        }
    return mapping


def translate_rows(votes, mapping):
    translated = []
    unmatched = []
    for row in votes:
        m = mapping.get(row['row_index'])
        if m is None:
            unmatched.append(row['row_index'])
            continue
        if m['item_id'] != row['item_id']:
            # Should never happen if the vote was cast against this same
            # dataset build, but fail loudly rather than silently mis-map.
            raise ValueError(
                f"row_index {row['row_index']}: item_id mismatch — vote has "
                f"{row['item_id']!r}, mapping has {m['item_id']!r}. The votes "
                f"CSV may be from a different dataset build than --mapping."
            )

        model_type1, model_type2 = m['model_type1'], m['model_type2']

        # Path 1: A/B position -> version1/version2 -> real model code, using
        # THIS ROW's own A_model/B_model.
        def resolve(value):
            if value == 'version1':
                return model_type1
            if value == 'version2':
                return model_type2
            return value

        new_row = dict(row)
        new_row['A_model'] = resolve(row['A_model'])
        new_row['B_model'] = resolve(row['B_model'])
        new_row['choice'] = resolve(row['choice'])

        # Re-key quality status/reason from A/B position to real model code,
        # using the now-resolved A_model/B_model on this same row.
        if new_row['A_model'] == model_type1:
            q1_status, q1_reason = row['A_quality_status'], row['A_quality_reason']
            q2_status, q2_reason = row['B_quality_status'], row['B_quality_reason']
        else:
            q1_status, q1_reason = row['B_quality_status'], row['B_quality_reason']
            q2_status, q2_reason = row['A_quality_status'], row['A_quality_reason']
        new_row[f'{model_type1}_quality_status'] = q1_status
        new_row[f'{model_type1}_quality_reason'] = q1_reason
        new_row[f'{model_type2}_quality_status'] = q2_status
        new_row[f'{model_type2}_quality_reason'] = q2_reason

        # Path 2: link + autoqc, resolved directly from the mapping row —
        # no A/B hop, generated_image_url1/model_type1 are always paired.
        new_row[f'{model_type1}_url'] = m['url1']
        new_row[f'{model_type1}_qc_label'] = m['qc_label1']
        new_row[f'{model_type1}_qc_dino_score'] = m['qc_dino1']
        new_row[f'{model_type1}_qc_face_similarity'] = m['qc_face1']
        new_row[f'{model_type2}_url'] = m['url2']
        new_row[f'{model_type2}_qc_label'] = m['qc_label2']
        new_row[f'{model_type2}_qc_dino_score'] = m['qc_dino2']
        new_row[f'{model_type2}_qc_face_similarity'] = m['qc_face2']

        translated.append(new_row)
    return translated, unmatched


def main():
    args = parse_args()

    with open(args.votes, newline='', encoding='utf-8') as f:
        votes = list(csv.DictReader(f))

    if args.exclude_evaluators:
        votes = [r for r in votes if r['evaluator'] not in set(args.exclude_evaluators)]

    mapping = load_mapping(args.mapping)
    translated, unmatched = translate_rows(votes, mapping)

    if unmatched:
        print(f'WARNING: {len(unmatched)} vote rows had no match in the mapping CSV, skipped: {unmatched[:10]}')

    # Union of all keys across rows (model-code-named columns differ if both
    # model codes ever appear as model_type1 in different rows).
    fieldnames = []
    seen = set()
    for row in translated:
        for k in row:
            if k not in seen:
                seen.add(k)
                fieldnames.append(k)

    with open(args.output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(translated)
    print(f'Wrote {args.output} ({len(translated)} rows, {len(fieldnames)} columns)')

    print_report('BY REAL MODEL CODE', translated)


if __name__ == '__main__':
    main()
