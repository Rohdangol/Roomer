from django.utils.formats import localize

from listings.services import DRAFT_FIELDS


def display_value(revision, name):
    if revision is None:
        return "Not published"
    value = getattr(revision, name)
    if name in ("room_type", "furnishing"):
        return getattr(revision, "get_" + name + "_display")()
    if isinstance(value, bool):
        return "Allowed" if value else "Not allowed"
    return "Not provided" if value is None or value == "" else localize(value)


def pending_changes(published, pending):
    # Call only with snapshots from an ownership-checked listing; nothing here mutates them.
    if pending is None:
        return {"fields": [], "photos": []}
    fields = []
    for name in DRAFT_FIELDS:
        if published is None or getattr(published, name) != getattr(pending, name):
            fields.append({"label": pending._meta.get_field(name).verbose_name.capitalize(),
                "approved": display_value(published, name), "proposed": display_value(pending, name)})
    before = sorted(published.amenity_links.values_list("amenity__name", flat=True)) if published else []
    after = sorted(pending.amenity_links.values_list("amenity__name", flat=True))
    if before != after:
        fields.append({"label": "Amenities", "approved": ", ".join(before) or ("None" if published else "Not published"),
            "proposed": ", ".join(after) or "None"})
    old_photos = list(published.photos.all()) if published else []
    new_photos = list(pending.photos.all())
    old_by_name = {photo.image.name: photo for photo in old_photos}
    new_by_name = {photo.image.name: photo for photo in new_photos}
    removed = {photo.position: photo for photo in old_photos if photo.image.name not in new_by_name}
    added = {photo.position: photo for photo in new_photos if photo.image.name not in old_by_name}
    photos = []
    for position in sorted(removed.keys() | added.keys()):
        old, new = removed.get(position), added.get(position)
        photos.append({"label": "Replaced photo" if old and new else ("Added photo" if new else "Removed photo"),
            "approved": old, "proposed": new})
    for new in new_photos:
        old = old_by_name.get(new.image.name)
        if old and old.position != new.position:
            photos.append({"label": "Photo order changed", "approved": old, "proposed": new})
    return {"fields": fields, "photos": photos}
