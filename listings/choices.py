from django.db import models


class RoomType(models.TextChoices):
    SINGLE = "single_room", "Single Room"
    DOUBLE = "double_room", "Double Room"
    ONE_BHK = "1bhk", "1BHK"
    TWO_BHK = "2bhk", "2BHK"


class Furnishing(models.TextChoices):
    FURNISHED = "furnished", "Furnished"
    UNFURNISHED = "unfurnished", "Unfurnished"
