"""
Offline RTP/volatility simulator for the Rollin 3x3 slot.

Reuses the exact same pure functions the live server uses
(slots.services.spin_reel_stops / derive_grid / evaluate_paylines) so
simulated results are guaranteed representative of production math - this
is not a separate/parallel implementation of the game rules.

Usage:
    python manage.py simulate_slot_rtp --spins 1000000
    python manage.py simulate_slot_rtp --spins 10000000 --wager 50
"""

import time
from collections import Counter
from decimal import Decimal

from django.core.management.base import BaseCommand

from slots.constants import PAYLINES, SYMBOLS
from slots.services import derive_grid, evaluate_paylines, spin_reel_stops

BUCKET_LABELS = ['0x', '0-1x', '1-2x', '2-5x', '5-10x', '10-25x', '25x+']


def bucket_for_multiplier(multiplier):
    if multiplier <= 0:
        return '0x'
    if multiplier < 1:
        return '0-1x'
    if multiplier < 2:
        return '1-2x'
    if multiplier < 5:
        return '2-5x'
    if multiplier < 10:
        return '5-10x'
    if multiplier < 25:
        return '10-25x'
    return '25x+'


class Command(BaseCommand):
    help = 'Simulate N Rollin 3x3 slot spins offline and report RTP/hit-rate/volatility statistics.'

    def add_arguments(self, parser):
        parser.add_argument('--spins', type=int, default=1_000_000, help='Number of spins to simulate.')
        parser.add_argument('--wager', type=int, default=100, help='Wager used for every simulated spin (RTP/hit-rate are wager-invariant; only affects the reported average payout figures).')

    def handle(self, *args, **options):
        spins = options['spins']
        wager = options['wager']

        start = time.monotonic()

        total_multiplier_sum = Decimal('0')
        total_payout_sum = Decimal('0')
        max_payout = Decimal('0')
        hit_count = 0
        multi_line_hit_count = 0
        symbol_win_counts = Counter()
        payline_hit_counts = Counter()
        bucket_counts = Counter()

        for _ in range(spins):
            stops = spin_reel_stops()
            grid = derive_grid(stops)
            winning_lines, spin_multiplier = evaluate_paylines(grid)

            spin_payout = wager * spin_multiplier
            total_multiplier_sum += spin_multiplier
            total_payout_sum += spin_payout
            if spin_payout > max_payout:
                max_payout = spin_payout

            if winning_lines:
                hit_count += 1
                if len(winning_lines) > 1:
                    multi_line_hit_count += 1
                for entry in winning_lines:
                    symbol_win_counts[entry['symbol']] += 1
                    payline_hit_counts[entry['line_index']] += 1

            bucket_counts[bucket_for_multiplier(spin_multiplier)] += 1

        elapsed = time.monotonic() - start

        total_wagered = wager * spins
        rtp = (total_payout_sum / total_wagered) if total_wagered else Decimal('0')
        hit_rate = hit_count / spins
        loss_rate = 1 - hit_rate
        avg_payout = total_payout_sum / spins
        avg_multiplier = total_multiplier_sum / spins

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Rollin 3x3 Slot RTP Simulation ({elapsed:.1f}s)'))
        self.stdout.write('=' * 50)
        self.stdout.write(f'Spins:               {spins:,}')
        self.stdout.write(f'Wager per spin:      {wager} RP')
        self.stdout.write(f'RTP:                 {rtp * 100:.2f}%')
        self.stdout.write(f'Hit Rate:            {hit_rate * 100:.2f}%')
        self.stdout.write(f'Loss Rate:           {loss_rate * 100:.2f}%')
        self.stdout.write(f'Multi-line win rate: {(multi_line_hit_count / spins) * 100:.2f}%')
        self.stdout.write(f'Average payout:      {avg_payout:.4f} RP')
        self.stdout.write(f'Average multiplier:  {avg_multiplier:.4f}x')
        self.stdout.write(f'Max observed payout: {max_payout:.2f} RP ({(max_payout / wager):.2f}x)')

        self.stdout.write('')
        self.stdout.write('Payout distribution:')
        for label in BUCKET_LABELS:
            count = bucket_counts.get(label, 0)
            self.stdout.write(f'  {label:<8} {count / spins * 100:6.2f}%  ({count:,})')

        self.stdout.write('')
        self.stdout.write('Symbol win frequency (share of all winning lines):')
        total_symbol_wins = sum(symbol_win_counts.values()) or 1
        for symbol in SYMBOLS:
            count = symbol_win_counts.get(symbol, 0)
            self.stdout.write(f'  {symbol:<8} {count / total_symbol_wins * 100:6.2f}%  ({count:,})')

        self.stdout.write('')
        self.stdout.write('Payline hit frequency (share of all winning lines):')
        for line_index in range(len(PAYLINES)):
            count = payline_hit_counts.get(line_index, 0)
            self.stdout.write(f'  Line {line_index}    {count / total_symbol_wins * 100:6.2f}%  ({count:,})')

        self.stdout.write('')
