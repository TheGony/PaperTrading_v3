# -*- coding: utf-8 -*-
"""
trading_logs/trade_detail.csv 기반 매매 품질 분석 스크립트
실행: python analyze_trades.py [날짜범위: 최근 N일]
"""
import sys
import csv
import os
from collections import defaultdict

LOG_PATH = os.path.join('trading_logs', 'trade_detail.csv')


def load_trades(days=None):
    if not os.path.exists(LOG_PATH):
        print(f'파일 없음: {LOG_PATH}')
        return []

    rows = []
    with open(LOG_PATH, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    if days and rows:
        dates = sorted({r['날짜'] for r in rows}, reverse=True)
        target = set(dates[:days])
        rows = [r for r in rows if r['날짜'] in target]

    return rows


def _f(val, default=None):
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def analyze(rows):
    if not rows:
        print('데이터 없음')
        return

    total = len(rows)
    wins  = [r for r in rows if _f(r.get('수익률(%)'), 0) > 0]
    losses = [r for r in rows if _f(r.get('수익률(%)'), 0) <= 0]

    win_rates  = [_f(r['수익률(%)']) for r in wins]
    loss_rates = [_f(r['수익률(%)']) for r in losses]

    avg_win  = sum(win_rates)  / len(win_rates)  if win_rates  else 0
    avg_loss = sum(loss_rates) / len(loss_rates) if loss_rates else 0
    win_rate = len(wins) / total * 100 if total else 0
    expectancy = (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss)

    print('=' * 60)
    print(f'  분석 대상: {total}건  ({sorted({r["날짜"] for r in rows})[0]} ~ {sorted({r["날짜"] for r in rows})[-1]})')
    print('=' * 60)

    # ── 1. 전체 기댓값 ─────────────────────────────────────
    print('\n[1] 전체 기댓값 (Expectancy)')
    print(f'  승률:      {win_rate:.1f}%  ({len(wins)}승 {len(losses)}패)')
    print(f'  평균 수익: {avg_win:+.2f}%')
    print(f'  평균 손실: {avg_loss:+.2f}%')
    print(f'  기댓값:    {expectancy:+.3f}%  {"✅ 양수" if expectancy > 0 else "❌ 음수 → 전략 재검토 필요"}')

    # ── 2. 전략별 기댓값 ────────────────────────────────────
    print('\n[2] 전략별 기댓값')
    for strategy in ['MOMENTUM', 'ORB']:
        st_rows = [r for r in rows if r.get('구간') == strategy]
        if not st_rows:
            continue
        st_wins   = [_f(r['수익률(%)']) for r in st_rows if _f(r['수익률(%)'], 0) > 0]
        st_losses = [_f(r['수익률(%)']) for r in st_rows if _f(r['수익률(%)'], 0) <= 0]
        st_wr = len(st_wins) / len(st_rows) * 100
        st_aw = sum(st_wins)   / len(st_wins)   if st_wins   else 0
        st_al = sum(st_losses) / len(st_losses) if st_losses else 0
        st_ex = (st_wr / 100 * st_aw) + ((1 - st_wr / 100) * st_al)
        print(f'  {strategy}: {len(st_rows)}건 | 승률 {st_wr:.0f}% | 기댓값 {st_ex:+.3f}%')

    # ── 3. MFE/MAE 분석 ────────────────────────────────────
    print('\n[3] Edge Ratio (MFE / |MAE|)')
    mfes = [_f(r.get('MFE(%)')) for r in rows if _f(r.get('MFE(%)')) is not None]
    maes = [_f(r.get('MAE(%)')) for r in rows if _f(r.get('MAE(%)')) is not None]
    if mfes and maes:
        avg_mfe = sum(mfes) / len(mfes)
        avg_mae = abs(sum(maes) / len(maes)) if maes else 1
        edge_ratio = avg_mfe / avg_mae if avg_mae else 0
        print(f'  평균 MFE: {avg_mfe:+.2f}%')
        print(f'  평균 MAE: {sum(maes)/len(maes):+.2f}%')
        print(f'  Edge Ratio: {edge_ratio:.2f}  {"✅ 진입 타이밍 양호" if edge_ratio >= 1.5 else "⚠️ 진입 타이밍 개선 필요" if edge_ratio >= 1.0 else "❌ 진입 자체 문제"}')

        # MFE 구간 분포
        mfe_neg   = sum(1 for m in mfes if m < 0)
        mfe_lo    = sum(1 for m in mfes if 0 <= m < 1)
        mfe_mid   = sum(1 for m in mfes if 1 <= m < 3)
        mfe_hi    = sum(1 for m in mfes if m >= 3)
        n = len(mfes)
        print(f'  MFE 분포: <0%: {mfe_neg/n*100:.0f}% | 0~1%: {mfe_lo/n*100:.0f}% | 1~3%: {mfe_mid/n*100:.0f}% | ≥3%: {mfe_hi/n*100:.0f}%')

    # ── 4. 매도 사유별 통계 ────────────────────────────────
    print('\n[4] 매도 사유별 평균 수익률')
    reason_stats = defaultdict(list)
    for r in rows:
        reason = r.get('매도사유', '')
        key = '손절' if '손절' in reason else ('트레일링' if '트레일링' in reason else ('데드크로스' if '데드크로스' in reason else ('조기손절' if '조기' in reason else '기타')))
        reason_stats[key].append(_f(r['수익률(%)'], 0))
    for key, vals in sorted(reason_stats.items()):
        avg = sum(vals) / len(vals)
        print(f'  {key}: {len(vals)}건 | 평균 {avg:+.2f}%')

    # ── 5. 진입 변수 분석 ──────────────────────────────────
    print('\n[5] 진입 RSI 구간별 승률')
    rsi_buckets = {'~50': [], '50~60': [], '60~70': [], '70~': []}
    for r in rows:
        rsi = _f(r.get('진입RSI'))
        if rsi is None:
            continue
        pl  = _f(r['수익률(%)'], 0)
        if rsi < 50:
            rsi_buckets['~50'].append(pl)
        elif rsi < 60:
            rsi_buckets['50~60'].append(pl)
        elif rsi < 70:
            rsi_buckets['60~70'].append(pl)
        else:
            rsi_buckets['70~'].append(pl)
    for label, pls in rsi_buckets.items():
        if not pls:
            continue
        wr = sum(1 for p in pls if p > 0) / len(pls) * 100
        avg = sum(pls) / len(pls)
        print(f'  RSI {label}: {len(pls)}건 | 승률 {wr:.0f}% | 평균 {avg:+.2f}%')

    print('\n[6] 외인/기관 매수 여부별 승률')
    for fg_label, cond in [('외인○', lambda r: r.get('외인기관') == '○'),
                            ('외인×', lambda r: r.get('외인기관') == '×')]:
        subset = [r for r in rows if cond(r)]
        if not subset:
            continue
        wr = sum(1 for r in subset if _f(r['수익률(%)'], 0) > 0) / len(subset) * 100
        avg = sum(_f(r['수익률(%)'], 0) for r in subset) / len(subset)
        print(f'  {fg_label}: {len(subset)}건 | 승률 {wr:.0f}% | 평균 {avg:+.2f}%')

    print('\n[7] KOSPI 시장 환경별 승률')
    mkt_buckets = {'하락(-1%↓)': [], '보합(-1~+1%)': [], '상승(+1%↑)': []}
    for r in rows:
        kospi = _f(r.get('KOSPI등락(%)'))
        if kospi is None:
            continue
        pl = _f(r['수익률(%)'], 0)
        if kospi < -1:
            mkt_buckets['하락(-1%↓)'].append(pl)
        elif kospi <= 1:
            mkt_buckets['보합(-1~+1%)'].append(pl)
        else:
            mkt_buckets['상승(+1%↑)'].append(pl)
    for label, pls in mkt_buckets.items():
        if not pls:
            continue
        wr = sum(1 for p in pls if p > 0) / len(pls) * 100
        avg = sum(pls) / len(pls)
        print(f'  {label}: {len(pls)}건 | 승률 {wr:.0f}% | 평균 {avg:+.2f}%')

    print('\n' + '=' * 60)


if __name__ == '__main__':
    days = int(sys.argv[1]) if len(sys.argv) > 1 else None
    rows = load_trades(days)
    analyze(rows)
