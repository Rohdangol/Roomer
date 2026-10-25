from django.core.management.base import BaseCommand
from django.core.exceptions import ValidationError

from rentals.agreement_services import activate_scheduled
from rentals.models import RentalAgreement


class Command(BaseCommand):
    help = "Activate approved due agreements and complete expired rentals using inclusive Nepal dates. Safe to repeat."

    def handle(self, *args, **options):
        counts = {"activated": 0, "completed": 0, "skipped": 0}
        # Legacy records require explicit review; never manufacture Admin approval.
        ids = list(RentalAgreement.objects.filter(workflow_version=2, status__in=["scheduled", "active"]).values_list("pk", flat=True))
        for pk in ids:
            try:
                result = activate_scheduled(pk)
            except ValidationError:
                counts["skipped"] += 1
                self.stderr.write(f"Agreement #{pk} requires review; no transition was applied.")
            else:
                if result:
                    counts[result] += 1
        self.stdout.write(self.style.SUCCESS(f"Activated {counts['activated']}; completed {counts['completed']}; skipped {counts['skipped']}."))
