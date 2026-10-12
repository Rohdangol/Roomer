from django.db import migrations


def seed_amenities(apps, schema_editor):
    Amenity = apps.get_model("listings", "Amenity")
    for name in ("Wi-Fi", "Water Supply", "Attached Bathroom", "Parking", "Laundry"):
        Amenity.objects.using(schema_editor.connection.alias).get_or_create(name=name)


class Migration(migrations.Migration):
    dependencies = [("listings", "0001_initial")]
    # Keep catalog rows on reversal rather than deleting referenced data.
    operations = [migrations.RunPython(seed_amenities, migrations.RunPython.noop)]
