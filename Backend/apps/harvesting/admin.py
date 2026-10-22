from django.contrib import admin
from . import models

for model in [
    models.Schedule,
    models.ScheduleEvent,
    models.Harvest,
]:
    admin.site.register(model)
