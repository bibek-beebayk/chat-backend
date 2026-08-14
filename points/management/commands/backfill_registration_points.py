from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from points.models import PointAction
from points.services import award_points

BACKFILL_ACTION_SLUG = 'registration_backfill_2026_08'


class Command(BaseCommand):
    help = (
        'One-time +1000 RP grandfather grant for existing users, so players '
        'who registered before the registration bonus existed receive it '
        'exactly once. Idempotent and safe to re-run - already-granted '
        'users are skipped automatically via the points ledger.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Report the eligible user count without granting anything.')
        parser.add_argument('--batch-size', type=int, default=500, help='DB fetch chunk size.')

    def handle(self, *args, **options):
        User = get_user_model()

        if not PointAction.objects.filter(slug=BACKFILL_ACTION_SLUG, is_active=True).exists():
            raise CommandError(
                f'PointAction "{BACKFILL_ACTION_SLUG}" is not configured/active - '
                'run migrations first (points.0006_seed_redemption_config_and_actions).'
            )

        # Eligible: verified, non-test player accounts. Never-verified
        # (is_active=False) accounts are excluded deliberately - granting
        # real spendable currency to accounts that never completed
        # verification is a fraud-surface question, not a technical one.
        qs = User.objects.filter(user_type='player', is_active=True, is_test_user=False).order_by('id')
        total = qs.count()
        self.stdout.write(f'{total} eligible users (player, active, non-test).')

        if options['dry_run']:
            self.stdout.write('Dry run - no points granted.')
            return

        before_count = self._granted_count()
        processed = 0
        for user in qs.iterator(chunk_size=options['batch_size']):
            award_points(
                user,
                BACKFILL_ACTION_SLUG,
                idempotency_key=f'backfill_2026_08:{user.id}',
                note='One-time grandfather RP grant',
            )
            processed += 1
            if processed % 1000 == 0:
                self.stdout.write(f'... {processed}/{total}')

        after_count = self._granted_count()
        self.stdout.write(self.style.SUCCESS(
            f'Done. Processed {processed} users. New grants this run: {after_count - before_count}.'
        ))

    def _granted_count(self):
        from points.models import PointsLedgerEntry
        return PointsLedgerEntry.objects.filter(action__slug=BACKFILL_ACTION_SLUG).count()
