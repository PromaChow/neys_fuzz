"""Summary of one ProbFuzz run (replaces summary.sh + the *_smape.py scripts).

Per program and per configured tool/algorithm, three flags as in ProbFuzz's summary.csv:
  Crash  the program did not finish (exception, timeout, no DONE marker)
  Num    the output contains inf/nan or a value outside [0,1]
  Acc    the result differs from the exact oracle: SMAPE above the threshold (and absolute difference above 1e-9)
SMAPE(a,b) = |a-b| / ((|a|+|b|)/2), with 0 when both are 0. A tuple missing from the output counts as probability 0.
"""
import glob
import json
import math
import os


def smape(a, b):
    d = abs(a) + abs(b)
    return 0.0 if d == 0 else 2 * abs(a - b) / d


def parse(path):
    """-> (finished, {(rel, tuple): value}, text)"""
    found = sorted(glob.glob(path.rsplit('_', 1)[0] + '_*'))
    if not found:
        return False, {}, ''
    path = found[0]
    text = open(path).read()
    vals = {}
    for line in text.splitlines():
        if line.startswith('RESULT '):
            _, rel, t, v = line.split(' ')
            vals[(rel, t)] = float(v)
    return ('DONE' in text.splitlines()), vals, text


def compare(want, got, threshold):
    worst = 0.0
    for key, w in want.items():
        g = got.get(key, 0.0)
        if abs(w - g) > 1e-9:
            worst = max(worst, smape(w, g))
    return worst, worst > threshold


def summarize(directory, config):
    threshold = config.get('smape_threshold', 1e-4)
    runs = [(c['tool'], c['algorithm']) for c in config['runConfigurations'] if c['enabled'] and c['tool'] != 'oracle']
    header = ['Program'] + ['%s_%s_%s' % (t, a, f) for t, a in runs for f in ('Crash', 'Num', 'Acc')] + ['MaxSMAPE']
    rows, detail = [header], {}
    for pdir in sorted(glob.glob(os.path.join(directory, '*/'))):
        name = os.path.basename(pdir.rstrip('/'))
        pid = name.rsplit('_', 1)[1]
        _, want, _ = parse(os.path.join(pdir, 'oracle_exact_out_%s' % pid))
        row, worst_all = [name], 0.0
        for t, a in runs:
            fin, got, text = parse(os.path.join(pdir, '%s_%s_out_%s' % (t, a, pid)))
            crash = not fin
            num = any(math.isnan(v) or math.isinf(v) or v < 0 or v > 1 for v in got.values())
            worst, bad = (0.0, False) if crash else compare(want, got, threshold)
            worst_all = max(worst_all, worst)
            row += ['*' if crash else '-', '*' if num else '-', '*' if bad else '-']
            if crash or num or bad:
                detail.setdefault(name, {})['%s_%s' % (t, a)] = {
                    'crash': crash, 'num': num, 'smape': worst,
                    'error': (text.strip().splitlines() or [''])[-1][:200] if crash else None}
        rows.append(row + ['%.3g' % worst_all])
    with open(os.path.join(directory, 'summary.csv'), 'w') as f:
        f.write("\n".join(",".join(r) for r in rows) + "\n")
    with open(os.path.join(directory, 'findings.json'), 'w') as f:
        json.dump(detail, f, indent=1)
    # totals per tool
    print("tool_algorithm: programs with Crash / Num / Acc flags")
    for i, (t, a) in enumerate(runs):
        cols = [(r[1 + 3 * i], r[2 + 3 * i], r[3 + 3 * i]) for r in rows[1:]]
        print("  %-24s %4d / %4d / %4d  of %d" % ('%s_%s' % (t, a), sum(c[0] == '*' for c in cols),
                                                  sum(c[1] == '*' for c in cols), sum(c[2] == '*' for c in cols), len(cols)))
