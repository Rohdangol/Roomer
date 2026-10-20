from django.core.management.base import BaseCommand

from rentals.agreement_services import activate_scheduled, local_today
from rentals.models import RentalAgreement


class Command(BaseCommand):
    help = "Activate binding Scheduled agreements due on or before today in Asia/Kathmandu. Safe to repeat."

    def handle(self, *args, **options):
        ids = RentalAgreement.objects.filter(status="scheduled", current_terms__start_date__lte=local_today()).values_list("pk", flat=True)
        activated = sum(activate_scheduled(pk) for pk in ids.iterator())
        self.stdout.write(self.style.SUCCESS(f"Activated {activated} scheduled agreement(s)."))
