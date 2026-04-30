"""
ORB 미발동 원인 분석 스크립트
사용: python test_orb_analysis.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from util.login import fn_au10001
from api.chart import fn_ka10080, fn_ka10080_full

STK_CD   = '375500'
ORB_HIGH = 102300
ORB_LOW  = 100000
ORB_RSI_LOW  = 55
ORB_RSI_HIGH = 68
ORB_VOL_MULT = 1.5
ORB_CHASE    = 1.01
ORB_MAX      = 2

def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None
    ordered = list(reversed(prices[:period + 1]))
    gains, losses = [], []
    for i in range(1, len(ordered)):
        diff = ordered[i] - ordered[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + (avg_gain / avg_loss)))


def main():
    print("token...")
    token = fn_au10001()
    if not token:
        print("FAIL")
        return

    print(f"\n{STK_CD} candle fetch...")
    candles_full = fn_ka10080_full(STK_CD, 400, 'N', '', token)
    prices, volumes, _, _ = fn_ka10080(STK_CD, 400, 'N', '', token)

    if not candles_full:
        print("NO DATA")
        return

    print(f"\ntotal candles: {len(candles_full)}")
    print("--- raw cntr_tm samples (first 5) ---")
    for c in candles_full[:5]:
        print(f"  cntr_tm={repr(c['cntr_tm'])}  cur_prc={c['cur_prc']}")
    print("--- raw cntr_tm samples (last 5) ---")
    for c in candles_full[-5:]:
        print(f"  cntr_tm={repr(c['cntr_tm'])}  cur_prc={c['cur_prc']}")

    # cntr_tm -> HHMM
    def _hhmm(t):
        t = str(t).strip()
        return t[8:12] if len(t) >= 14 else t[0:4]

    def _hhmm_disp(t):
        h = _hhmm(t)
        return f"{h[:2]}:{h[2:]}"

    needed = 21
    total  = len(candles_full)

    print(f"\n{'time':<8} {'price':>8} {'vol':>10} {'HHMM':>6}")
    print("-" * 40)
    for idx in range(total - 1, -1, -1):
        c    = candles_full[idx]
        hhmm = _hhmm(c['cntr_tm'])
        print(f"{_hhmm_disp(c['cntr_tm']):<8} {c['cur_prc']:>8.0f} {c['trde_qty']:>10.0f}  {hhmm}")

    print("\n--- ORB condition check (09:35~10:30) ---")
    print(f"{'time':<8} {'price':>8} {'above':>6} {'nochase':>8} {'vol_x':>7} {'rsi':>6}  result")
    print("-" * 70)

    orb_bought = 0
    for idx in range(total - 1, -1, -1):
        c    = candles_full[idx]
        hhmm = _hhmm(c['cntr_tm'])
        if not ('0935' <= hhmm <= '1030'):
            continue

        prices_at = prices[total - 1 - idx:]
        if len(prices_at) < needed:
            print(f"{_hhmm_disp(c['cntr_tm']):<8} -- not enough data ({len(prices_at)}/{needed})")
            continue

        cur_price = prices_at[0]
        vi        = total - 1 - idx
        vol_curr  = volumes[vi]     if vi     < len(volumes) else 0
        vol_prev  = volumes[vi + 1] if vi + 1 < len(volumes) else 0
        rsi       = calc_rsi(prices_at)

        above_orb = cur_price > ORB_HIGH
        no_chase  = cur_price <= ORB_HIGH * ORB_CHASE
        vol_ok    = vol_prev > 0 and vol_curr >= vol_prev * ORB_VOL_MULT
        rsi_ok    = rsi is not None and ORB_RSI_LOW < rsi <= ORB_RSI_HIGH
        count_ok  = orb_bought < ORB_MAX
        vol_ratio = (vol_curr / vol_prev) if vol_prev > 0 else 0
        rsi_s     = f"{rsi:.1f}" if rsi else "N/A"

        if above_orb and no_chase and vol_ok and rsi_ok and count_ok:
            result = "OK -> entry"
            orb_bought += 1
        else:
            reasons = []
            if not above_orb:       reasons.append(f"price<={ORB_HIGH}")
            if above_orb and not no_chase: reasons.append(f"chase>{ORB_HIGH*ORB_CHASE:.0f}")
            if not vol_ok:          reasons.append(f"vol={vol_ratio:.1f}x<{ORB_VOL_MULT}x")
            if not rsi_ok:          reasons.append(f"RSI={rsi_s}")
            if not count_ok:        reasons.append(f"count={orb_bought}/{ORB_MAX}")
            result = "SKIP: " + " / ".join(reasons)

        print(f"{_hhmm_disp(c['cntr_tm']):<8} {cur_price:>8.0f} {'Y' if above_orb else 'N':>6} {'Y' if no_chase else 'N':>8} {vol_ratio:>7.2f} {rsi_s:>6}  {result}")

    print(f"\nORB entry count: {orb_bought}")


if __name__ == '__main__':
    main()
