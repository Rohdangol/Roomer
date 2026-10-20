from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("listings", "0002_seed_amenities")]

    operations = [
        migrations.AlterField(
            model_name="listingrevision",
            name="locality",
            field=models.CharField(blank=True, max_length=100),
        ),
    ]
